#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest warning-style intraday signals against a placebo control.

The script treats these events as risk/edge warnings, not buy/sell strategies,
and answers one question per signal: *does acting on this warning beat acting at
a random moment in the same stock-day?* (i.e. is there any edge over noise?)

Categories (each tagged bearish/bullish by what "correct" means):
- broker_trap      (bearish): mega_buy downgraded by a broker-seat distribution warning
- distribution_trap(bearish): sniper signal_type=distribution_trap (disabled 2026-06-12; the
                              live engine guard still runs the same detection -> re-validate it)
- accumulation_sig (bullish): sniper signal_type=accumulation_signal (disabled 2026-06-12)
- absorption       (bearish): absorption_scanner WARN, "买入吸收/压单吸收"
- dump             (bearish): absorption_scanner WARN, "放量下跌"
- flow_sell_rN     (bearish): capital-flow SELL rules (R2/R3/R10/R13/...)

For every real event we also draw N placebo controls = the SAME stock & day at random
times (away from any real event), measured with the identical pipeline. The verdict is
driven by *lift over control*, not the raw post-event move (which is dominated by how the
market moved that day). This is the baseline that commit 16ffaff's "near random" claim lacked.

Time zones (verified against production):
  ticker_data.timestamp        -> UTC epoch ms (HK = UTC+8)
  sniper_signals.time          -> HK wall 'HH:MM'
  signal_pipeline.timestamp    -> HK wall ISO '...T13:51:43'
  capital_flow_signals.created_at -> UTC 'YYYY-MM-DD HH:MM:SS'
  kline_data.time_key          -> daily 'YYYY-MM-DD 00:00:00'
Conversions are tz-explicit so results are identical on a UTC server or a UTC+8 laptop.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import statistics
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

HK = timezone(timedelta(hours=8))
UTC = timezone.utc

DEFAULT_DB_PATH = os.environ.get("FUTU_DATABASE_PATH", "simple_trade/data/trade.db")
DEFAULT_MIN_TICK_ROWS = 1000
DEFAULT_COOLDOWN_MINUTES = 30
DEFAULT_CONTROLS = 3
DEFAULT_HIT_THRESHOLD = 1.0          # |return| >= 1% counts as a directional hit
HORIZONS_MINUTES = (15, 30, 60)
CONTROL_GUARD_MINUTES = 20           # keep control entries this far from any real event
MIN_VERDICT_COUNT = 30               # below this -> "insufficient_data"
KEEP_RATE_LIFT_PP = 8.0              # hit-rate lift (pp) over control to "keep"
KEEP_RET_LIFT_PCT = 0.3             # avg-return lift (%) over control to "keep"
ANTI_RATE_LIFT_PP = -8.0            # below this -> worse than random ("anti")

BEARISH = "bearish"   # correct == price falls
BULLISH = "bullish"   # correct == price rises


@dataclass(frozen=True)
class WarningEvent:
    trade_date: str
    stock_code: str
    stock_name: str
    category: str
    direction: str        # BEARISH / BULLISH
    epoch_ms: int
    signal_price: float
    detail: str
    event_id: str


@dataclass(frozen=True)
class Outcome:
    """Forward outcome of one entry (real signal or placebo control)."""
    entry_price: float
    rets: dict          # {minutes/'eod': pct or None}
    max_gain: Optional[float]
    max_drawdown: Optional[float]
    next_day: Optional[float]


class WarningSignalBacktester:
    def __init__(self, db_path: str, days: int, include_today: bool,
                 min_tick_rows: int, cooldown_minutes: int, controls: int,
                 hit_threshold: float, categories: Optional[set], seed: int,
                 max_per_category: Optional[int]) -> None:
        self.db_path = db_path
        self.days = days
        self.include_today = include_today
        self.min_tick_rows = min_tick_rows
        self.cooldown = timedelta(minutes=cooldown_minutes)
        self.controls = controls
        self.hit_threshold = hit_threshold
        self.categories = categories      # None == all
        self.max_per_category = max_per_category
        self.rng = random.Random(seed)
        # uri=True lets callers pass 'file:/path?mode=ro' for a safe read-only run
        # against the live production DB (SELECT-only, no sidecar writes, no writer lock).
        self.conn = sqlite3.connect(db_path, uri=db_path.startswith("file:"))
        self.conn.row_factory = sqlite3.Row
        self._next_close_cache: dict = {}   # (trade_date, stock_code) -> next-day close or None

    def close(self) -> None:
        self.conn.close()

    # ---- public ---------------------------------------------------------
    def probe(self) -> dict:
        dates = self._load_trade_dates()
        out = {"trade_dates": dates, "categories": {}}
        for ev in self._all_loaders():
            name, _direction, loader = ev
            if self.categories and not any(name.startswith(c) for c in self.categories):
                continue
            try:
                events = loader(dates)
            except Exception as e:  # noqa: BLE001
                out["categories"][name] = {"error": str(e)}
                continue
            by_cat: dict = {}
            for e in events:
                by_cat.setdefault(e.category, []).append(e)
            for cat, rows in by_cat.items():
                out["categories"][cat] = {
                    "count": len(rows),
                    "sample_detail": rows[0].detail[:120] if rows else "",
                }
        return out

    def run(self) -> dict:
        dates = self._load_trade_dates()
        events: list[WarningEvent] = []
        for name, _direction, loader in self._all_loaders():
            if self.categories and not any(name.startswith(c) for c in self.categories):
                continue
            loaded = loader(dates)
            loaded = self._dedupe(loaded)
            if self.max_per_category:
                # keep a random representative sample to bound runtime on huge categories
                buckets: dict = {}
                for e in loaded:
                    buckets.setdefault(e.category, []).append(e)
                loaded = []
                for cat, rows in buckets.items():
                    if len(rows) > self.max_per_category:
                        rows = self.rng.sample(rows, self.max_per_category)
                    loaded.extend(rows)
            events.extend(loaded)

        # group by (date, stock) so each stock-day's ticks load exactly once
        groups: dict = {}
        for e in events:
            groups.setdefault((e.trade_date, e.stock_code), []).append(e)

        results: dict = {}   # category -> {"signal": [Outcome], "control": [Outcome]}
        for (trade_date, stock_code), evs in groups.items():
            ticks = self._load_ticks(trade_date, stock_code)
            if not ticks:
                continue
            ts_list = [t[0] for t in ticks]
            real_ts = sorted(e.epoch_ms for e in evs)
            for e in evs:
                bucket = results.setdefault(e.category, {"direction": e.direction,
                                                         "signal": [], "control": []})
                so = self._evaluate(ticks, ts_list, e.epoch_ms, e.signal_price,
                                    trade_date, stock_code)
                if so:
                    bucket["signal"].append(so)
                for cts in self._control_times(ts_list, real_ts):
                    co = self._evaluate(ticks, ts_list, cts, 0.0, trade_date, stock_code)
                    if co:
                        bucket["control"].append(co)
        return self._summarize(results, dates)

    # ---- loaders --------------------------------------------------------
    def _all_loaders(self) -> list[tuple]:
        return [
            ("broker_trap", BEARISH, self._load_broker_trap),
            ("distribution_trap", BEARISH, self._load_sniper_type_factory(
                "distribution_trap", BEARISH)),
            ("accumulation_signal", BULLISH, self._load_sniper_type_factory(
                "accumulation_signal", BULLISH)),
            ("absorption", BEARISH, self._load_absorption),
            ("flow_sell", BEARISH, self._load_flow_sell),
        ]

    def _load_trade_dates(self) -> list[str]:
        today = date.today().isoformat()
        rows = self.conn.execute(
            """
            SELECT trade_date, COUNT(*) AS n
            FROM ticker_data
            GROUP BY trade_date
            HAVING n >= ?
            ORDER BY trade_date DESC
            """,
            (self.min_tick_rows,),
        ).fetchall()
        dates = [r["trade_date"] for r in rows
                 if self.include_today or r["trade_date"] < today]
        return list(reversed(dates[: self.days]))

    def _load_broker_trap(self, dates: list[str]) -> list[WarningEvent]:
        if not dates or not self._table_exists("sniper_signals"):
            return []
        ph = ",".join("?" for _ in dates)
        rows = self.conn.execute(
            f"""
            SELECT id, trade_date, time, stock_code, stock_name, price, detail
            FROM sniper_signals
            WHERE trade_date IN ({ph}) AND signal_type = 'mega_buy'
              AND (detail LIKE '%出货迹象%' OR detail LIKE '%席位警示%'
                   OR detail LIKE '%散户/未知席位%')
            ORDER BY trade_date, stock_code, time, id
            """,
            dates,
        ).fetchall()
        out = []
        for r in rows:
            ep = self._hk_hhmm_to_epoch(r["trade_date"], r["time"])
            if ep is None:
                continue
            out.append(WarningEvent(
                r["trade_date"], r["stock_code"], r["stock_name"] or r["stock_code"],
                "broker_trap", BEARISH, ep, float(r["price"] or 0),
                r["detail"] or "", f"sniper:{r['id']}"))
        return out

    def _load_sniper_type_factory(self, signal_type: str, direction: str) -> Callable:
        def loader(dates: list[str]) -> list[WarningEvent]:
            if not dates or not self._table_exists("sniper_signals"):
                return []
            ph = ",".join("?" for _ in dates)
            rows = self.conn.execute(
                f"""
                SELECT id, trade_date, time, stock_code, stock_name, price, detail
                FROM sniper_signals
                WHERE trade_date IN ({ph}) AND signal_type = ?
                ORDER BY trade_date, stock_code, time, id
                """,
                (*dates, signal_type),
            ).fetchall()
            out = []
            for r in rows:
                ep = self._hk_hhmm_to_epoch(r["trade_date"], r["time"])
                if ep is None:
                    continue
                out.append(WarningEvent(
                    r["trade_date"], r["stock_code"], r["stock_name"] or r["stock_code"],
                    signal_type, direction, ep, float(r["price"] or 0),
                    r["detail"] or "", f"sniper:{r['id']}"))
            return out
        return loader

    def _load_absorption(self, dates: list[str]) -> list[WarningEvent]:
        if not dates or not self._table_exists("signal_pipeline"):
            return []
        ph = ",".join("?" for _ in dates)
        rows = self.conn.execute(
            f"""
            SELECT id, trade_date, timestamp, stock_code, stock_name, final_reason, raw_detail
            FROM signal_pipeline
            WHERE trade_date IN ({ph})
              AND source = 'absorption_scanner' AND direction = 'WARN'
            ORDER BY trade_date, stock_code, timestamp, id
            """,
            dates,
        ).fetchall()
        out = []
        for r in rows:
            raw = _loads_json(r["raw_detail"])
            reason = r["final_reason"] or raw.get("reason") or ""
            ep = self._hk_iso_to_epoch(r["timestamp"], r["trade_date"])
            if ep is None:
                continue
            # split bearish WARN into absorption (压单吸收) vs dump (放量下跌)
            cat = "dump" if "放量下跌" in reason else "absorption"
            out.append(WarningEvent(
                r["trade_date"], r["stock_code"], r["stock_name"] or r["stock_code"],
                cat, BEARISH, ep, float(raw.get("price") or 0),
                reason, f"pipeline:{r['id']}"))
        return out

    def _load_flow_sell(self, dates: list[str]) -> list[WarningEvent]:
        if not dates or not self._table_exists("capital_flow_signals"):
            return []
        valid = set(dates)
        # created_at is UTC; widen the BETWEEN by a day on each side then filter by HK date
        lo = (date.fromisoformat(dates[0]) - timedelta(days=1)).isoformat()
        hi = (date.fromisoformat(dates[-1]) + timedelta(days=1)).isoformat()
        # SELL + ALERT: ALERT rules (e.g. R4 资金转正高抛) are bearish warnings too and
        # were previously dropped by a SELL-only filter -> never validated. Each rule_id
        # gets its own bucket (flow_sell_rN) so per-rule keep/demote/anti verdicts fall out.
        rows = self.conn.execute(
            """
            SELECT id, rule_id, rule_name, stock_code, stock_name, price, reason, created_at
            FROM capital_flow_signals
            WHERE signal_type IN ('SELL', 'ALERT') AND date(created_at) BETWEEN ? AND ?
            ORDER BY created_at, stock_code, id
            """,
            (lo, hi),
        ).fetchall()
        out = []
        for r in rows:
            dt_utc = _parse_dt(r["created_at"])
            if not dt_utc:
                continue
            dt_utc = dt_utc.replace(tzinfo=UTC)
            dt_hk = dt_utc.astimezone(HK)
            trade_date = dt_hk.date().isoformat()
            if trade_date not in valid:
                continue
            rid = (r["rule_id"] or "R?").lower()
            out.append(WarningEvent(
                trade_date, r["stock_code"], r["stock_name"] or r["stock_code"],
                f"flow_sell_{rid}", BEARISH, int(dt_utc.timestamp() * 1000),
                float(r["price"] or 0), f"{r['rule_name']}: {r['reason'] or ''}",
                f"flow:{r['id']}"))
        return out

    # ---- evaluation -----------------------------------------------------
    def _evaluate(self, ticks, ts_list, entry_ts, signal_price, trade_date, stock_code) -> Optional[Outcome]:
        idx = bisect_left(ts_list, entry_ts)
        if idx >= len(ticks):
            return None
        entry = signal_price if signal_price > 0 else ticks[idx][1]
        if entry <= 0:
            return None
        rets = {}
        for m in HORIZONS_MINUTES:
            j = bisect_right(ts_list, entry_ts + m * 60_000) - 1
            rets[m] = _pct(ticks[j][1], entry) if j >= idx else None
        future = [ticks[k][1] for k in range(idx, len(ticks)) if ticks[k][1] > 0]
        rets["eod"] = _pct(ticks[-1][1], entry) if ticks else None
        nd = self._next_day(trade_date, stock_code, entry)
        return Outcome(
            entry_price=entry,
            rets=rets,
            max_gain=_pct(max(future), entry) if future else None,
            max_drawdown=_pct(min(future), entry) if future else None,
            next_day=nd,
        )

    def _control_times(self, ts_list, real_ts) -> list[int]:
        if not ts_list or self.controls <= 0:
            return []
        guard = CONTROL_GUARD_MINUTES * 60_000
        lo, hi = ts_list[0], ts_list[-1]
        picks, attempts = [], 0
        while len(picks) < self.controls and attempts < self.controls * 12:
            attempts += 1
            t = self.rng.randint(lo, hi)
            if any(abs(t - rt) < guard for rt in real_ts):
                continue
            if any(abs(t - p) < guard for p in picks):
                continue
            picks.append(t)
        return picks

    def _next_day(self, trade_date: str, stock_code: str, entry: float) -> Optional[float]:
        if entry <= 0:
            return None
        key = (trade_date, stock_code)
        if key not in self._next_close_cache:
            row = self.conn.execute(
                """
                SELECT close_price FROM kline_data
                WHERE stock_code = ? AND substr(time_key, 1, 10) > ?
                ORDER BY time_key LIMIT 1
                """,
                (stock_code, trade_date),
            ).fetchone()
            cp = float(row["close_price"] or 0) if row else 0.0
            self._next_close_cache[key] = cp if cp > 0 else None
        cp = self._next_close_cache[key]
        return _pct(cp, entry) if cp else None

    def _load_ticks(self, trade_date: str, stock_code: str):
        rows = self.conn.execute(
            """
            SELECT timestamp, price FROM ticker_data
            WHERE trade_date = ? AND stock_code = ? AND price > 0
            ORDER BY timestamp
            """,
            (trade_date, stock_code),
        ).fetchall()
        return [(int(r["timestamp"]), float(r["price"])) for r in rows]

    def _dedupe(self, events: list[WarningEvent]) -> list[WarningEvent]:
        kept, last = [], {}
        for e in sorted(events, key=lambda x: (x.trade_date, x.stock_code, x.category, x.epoch_ms)):
            key = (e.trade_date, e.stock_code, e.category)
            prev = last.get(key)
            if prev is not None and e.epoch_ms - prev < self.cooldown.total_seconds() * 1000:
                continue
            kept.append(e)
            last[key] = e.epoch_ms
        return kept

    # ---- summary --------------------------------------------------------
    def _summarize(self, results: dict, dates: list[str]) -> dict:
        thr = self.hit_threshold
        cats = []
        for cat, data in sorted(results.items()):
            direction = data["direction"]
            sig, ctl = data["signal"], data["control"]
            s = _stats(sig, direction, thr)
            c = _stats(ctl, direction, thr)
            rate_lift = _sub(s["hit_eod"], c["hit_eod"])
            ret_lift = (_sub(c["avg_eod"], s["avg_eod"]) if direction == BEARISH
                        else _sub(s["avg_eod"], c["avg_eod"]))
            nd_rate_lift = _sub(s["hit_next"], c["hit_next"])
            cats.append({
                "category": cat,
                "direction": direction,
                "n_signal": s["n"],
                "n_control": c["n"],
                "avg_eod": s["avg_eod"],
                "ctl_avg_eod": c["avg_eod"],
                "ret_lift_vs_ctl": _round(ret_lift),
                "hit_eod_rate": s["hit_eod"],            # % moved >= thr in the "correct" direction by close
                "ctl_hit_eod_rate": c["hit_eod"],
                "hit_rate_lift_pp": _round(rate_lift, 1),
                "avg_next_day": s["avg_next"],
                "next_hit_rate": s["hit_next"],
                "ctl_next_hit_rate": c["hit_next"],
                "next_hit_lift_pp": _round(nd_rate_lift, 1),
                "verdict": _verdict(s["n"], rate_lift, ret_lift),
            })
        return {"trade_dates": dates, "hit_threshold_pct": thr,
                "controls_per_event": self.controls, "categories": cats}

    def _table_exists(self, name: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None

    # ---- tz helpers -----------------------------------------------------
    @staticmethod
    def _hk_hhmm_to_epoch(trade_date: str, hhmm: Optional[str]) -> Optional[int]:
        if not hhmm:
            return None
        try:
            parts = hhmm.split(":")
            h, m = int(parts[0]), int(parts[1])
            s = int(parts[2]) if len(parts) > 2 else 0
            d = date.fromisoformat(trade_date)
            return int(datetime(d.year, d.month, d.day, h, m, s, tzinfo=HK).timestamp() * 1000)
        except (ValueError, TypeError, IndexError):
            return None

    @staticmethod
    def _hk_iso_to_epoch(iso: Optional[str], trade_date: str) -> Optional[int]:
        dt = _parse_dt(iso)
        if dt is None:
            return None
        return int(dt.replace(tzinfo=HK).timestamp() * 1000)


# ---- module helpers -----------------------------------------------------
def _loads_json(value: Optional[str]) -> dict:
    if not value:
        return {}
    try:
        p = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return p if isinstance(p, dict) else {}


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _pct(price: float, base: float) -> Optional[float]:
    if base <= 0:
        return None
    return round((price / base - 1) * 100, 3)


def _avg(values: Iterable[Optional[float]]) -> Optional[float]:
    clean = [v for v in values if v is not None]
    return round(sum(clean) / len(clean), 3) if clean else None


def _rate(values: Iterable[Optional[float]], predicate) -> Optional[float]:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return round(sum(1 for v in clean if predicate(v)) / len(clean) * 100, 1)


def _sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b


def _round(v: Optional[float], n: int = 3) -> Optional[float]:
    return None if v is None else round(v, n)


def _stats(outcomes: list, direction: str, thr: float) -> dict:
    n = len(outcomes)
    if direction == BEARISH:
        hit = lambda x: x <= -thr
    else:
        hit = lambda x: x >= thr
    return {
        "n": n,
        "avg_eod": _avg(o.rets.get("eod") for o in outcomes),
        "hit_eod": _rate((o.rets.get("eod") for o in outcomes), hit),
        "avg_next": _avg(o.next_day for o in outcomes),
        "hit_next": _rate((o.next_day for o in outcomes), hit),
    }


def _verdict(n: int, rate_lift: Optional[float], ret_lift: Optional[float]) -> str:
    if n < MIN_VERDICT_COUNT:
        return "insufficient_data"
    if rate_lift is None or ret_lift is None:
        return "insufficient_data"
    if rate_lift <= ANTI_RATE_LIFT_PP and ret_lift < 0:
        return "anti_predictive"          # worse than random -> disable (or flip)
    if rate_lift >= KEEP_RATE_LIFT_PP and ret_lift >= KEEP_RET_LIFT_PCT:
        return "keep"                     # real edge over random timing
    return "demote"                       # no meaningful edge -> info-only


# ---- reporting ----------------------------------------------------------
def print_report(summary: dict) -> None:
    print("=== Warning Signal Backtest (vs placebo control) ===")
    print(f"trade_dates: {summary['trade_dates']}")
    print(f"hit threshold: |{summary['hit_threshold_pct']}%|   "
          f"controls/event: {summary['controls_per_event']}\n")
    hdr = (f"{'category':18s} {'dir':7s} {'n':>5s} {'avgEOD':>8s} {'ctlEOD':>8s} "
           f"{'retLift':>8s} {'hit%':>6s} {'ctlHit':>7s} {'liftpp':>7s} "
           f"{'ndLift':>7s} {'verdict':>16s}")
    print(hdr)
    print("-" * len(hdr))
    for c in summary["categories"]:
        print(f"{c['category']:18s} {c['direction']:7s} {c['n_signal']:>5d} "
              f"{_f(c['avg_eod']):>8s} {_f(c['ctl_avg_eod']):>8s} "
              f"{_f(c['ret_lift_vs_ctl']):>8s} {_f(c['hit_eod_rate']):>6s} "
              f"{_f(c['ctl_hit_eod_rate']):>7s} {_f(c['hit_rate_lift_pp']):>7s} "
              f"{_f(c['next_hit_lift_pp']):>7s} {c['verdict']:>16s}")
    print("\nLegend: retLift = how much MORE the signal moved in its 'correct' direction")
    print("        than a random same-day entry (bearish: control_eod - signal_eod).")
    print("        liftpp = EOD hit-rate minus control hit-rate (percentage points).")
    print("        verdict: keep / demote(info-only) / anti_predictive / insufficient_data")
    print("\n--- JSON ---")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _f(v: Optional[float]) -> str:
    return "NA" if v is None else f"{v:+.2f}" if isinstance(v, float) else str(v)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--days", type=int, default=15)
    p.add_argument("--include-today", action="store_true")
    p.add_argument("--min-tick-rows", type=int, default=DEFAULT_MIN_TICK_ROWS)
    p.add_argument("--cooldown-minutes", type=int, default=DEFAULT_COOLDOWN_MINUTES)
    p.add_argument("--controls", type=int, default=DEFAULT_CONTROLS,
                   help="placebo controls drawn per real event")
    p.add_argument("--hit-threshold", type=float, default=DEFAULT_HIT_THRESHOLD,
                   help="abs %% move counted as a directional hit")
    p.add_argument("--categories", default="",
                   help="comma-separated prefixes, e.g. 'flow_sell,absorption' (default all)")
    p.add_argument("--max-per-category", type=int, default=0,
                   help="cap events per category (random sample) to bound runtime; 0 = no cap")
    p.add_argument("--seed", type=int, default=20260615)
    p.add_argument("--probe", action="store_true",
                   help="only print per-category event counts + a sample, then exit")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    cats = {c.strip() for c in a.categories.split(",") if c.strip()} or None
    t = WarningSignalBacktester(
        db_path=a.db, days=a.days, include_today=a.include_today,
        min_tick_rows=a.min_tick_rows, cooldown_minutes=a.cooldown_minutes,
        controls=a.controls, hit_threshold=a.hit_threshold, categories=cats,
        seed=a.seed, max_per_category=(a.max_per_category or None))
    try:
        if a.probe:
            print(json.dumps(t.probe(), ensure_ascii=False, indent=2))
            return 0
        summary = t.run()
    finally:
        t.close()
    print_report(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
