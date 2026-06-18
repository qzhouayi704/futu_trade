#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backtest the NEW system's BUY signals over one or more trading days.

Question answered: if you had acted on the buy suggestions/signals the new
system surfaced, at what minute did each first fire, and what was the return to
the *intraday peak* (best exit), to the *close* (hold-to-EOD), and to the
*next-day close* (hold overnight)?

BUY signal sources (all reflect the live new-system stack):
  sniper_mega_buy         sniper_signals  signal_type='mega_buy' is_red=0  (V1 巨量抢筹)
  pipe_strategy           signal_pipeline source='strategy'      dir=BUY   (V2 StockScorer 评分广播)
  pipe_sniper             signal_pipeline source='sniper'        dir=BUY   (狙击进 DecisionEngine)
  pipe_absorption_scanner signal_pipeline source='absorption_scanner' dir=BUY
  pipe_momentum_engine    signal_pipeline source='momentum_engine' dir=BUY (动量 STRONG/MODERATE)

Per stock+source+DAY we take the FIRST buy signal of that day as the entry.
Entry price = first tick at/after the signal time (realistic fill), or the
signal's own price if present.

Baseline = same stock universe, "buy at open, hold": open->peak / open->close /
open->next-close. Shows whether entering *at the signal* beat just buying these
names at the open.

Timezones: ticker_data.timestamp = UTC epoch ms; HK = UTC+8. kline_data.time_key
is daily 'YYYY-MM-DD ...'. Conversions are tz-explicit.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Optional

HK = timezone(timedelta(hours=8))


def _parse_dt(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def _pct(p: float, b: float) -> Optional[float]:
    if not b or b <= 0:
        return None
    return round((p / b - 1) * 100, 3)


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(median(xs), 3) if xs else None


def _rate(xs, pred):
    xs = [x for x in xs if x is not None]
    return round(sum(1 for x in xs if pred(x)) / len(xs) * 100, 1) if xs else None


# ---- exit-rule simulation -------------------------------------------------
# Compare "hold to close" vs fixed take-profit vs trailing stop ("let winners
# run"). All share one hard stop. Trailing arms only after a min gain so small
# movers fall to the hard stop while big movers ride the trend.
HARD_STOP_PCT = -2.5
EXIT_POLICIES = [
    ("hold_to_close", {"kind": "close"}),
    ("tp+3/sl-2.5", {"kind": "fixed", "tp": 3.0, "sl": HARD_STOP_PCT}),
    ("tp+5/sl-2.5", {"kind": "fixed", "tp": 5.0, "sl": HARD_STOP_PCT}),
    ("trail2@arm2/sl-2.5", {"kind": "trail", "arm": 2.0, "trail": 2.0, "sl": HARD_STOP_PCT}),
    ("trail3@arm3/sl-2.5", {"kind": "trail", "arm": 3.0, "trail": 3.0, "sl": HARD_STOP_PCT}),
]


def _sim_exit(fwd_prices: list, entry: float, spec: dict):
    """Walk the post-entry tick path; return (realized_pct, exit_reason)."""
    if not fwd_prices or entry <= 0:
        return None, "na"
    kind = spec["kind"]
    if kind == "close":
        return _pct(fwd_prices[-1], entry), "close"
    if kind == "fixed":
        tp, sl = spec["tp"], spec["sl"]
        for p in fwd_prices:
            r = (p / entry - 1) * 100
            if r <= sl:
                return round(r, 3), "stop"
            if r >= tp:
                return round(r, 3), "tp"
        return _pct(fwd_prices[-1], entry), "close"
    arm, trail, sl = spec["arm"], spec["trail"], spec["sl"]
    peak, armed = entry, False
    for p in fwd_prices:
        r = (p / entry - 1) * 100
        if r <= sl:
            return round(r, 3), "stop"
        if p > peak:
            peak = p
        if not armed and r >= arm:
            armed = True
        if armed and (p / peak - 1) * 100 <= -trail:
            return round(r, 3), "trail"
    return _pct(fwd_prices[-1], entry), "close"


class BuySignalBacktester:
    def __init__(self, db: str, days: int, include_today: bool, min_ticks: int,
                 exclude_sources: Optional[set] = None) -> None:
        self.conn = sqlite3.connect(db)
        self.conn.row_factory = sqlite3.Row
        self.days = days
        self.include_today = include_today
        self.min_ticks = min_ticks
        # signal_pipeline 'source' values to skip (e.g. deprecated legacy strategies)
        self.exclude_sources = exclude_sources or set()
        self._ticks: dict = {}
        self._next_close: dict = {}

    def close(self):
        self.conn.close()

    def _table_exists(self, name: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None

    def trade_dates(self) -> list[str]:
        today = date.today().isoformat()
        rows = self.conn.execute(
            "SELECT trade_date, COUNT(*) n FROM ticker_data GROUP BY trade_date "
            "HAVING n >= ? ORDER BY trade_date DESC", (self.min_ticks,)).fetchall()
        dates = [r["trade_date"] for r in rows
                 if self.include_today or r["trade_date"] < today]
        return list(reversed(dates[: self.days]))

    def ticks(self, td: str, code: str):
        key = (td, code)
        if key not in self._ticks:
            rows = self.conn.execute(
                "SELECT timestamp, price FROM ticker_data "
                "WHERE trade_date=? AND stock_code=? AND price>0 ORDER BY timestamp",
                (td, code)).fetchall()
            self._ticks[key] = [(int(r["timestamp"]), float(r["price"])) for r in rows]
        return self._ticks[key]

    def next_close(self, td: str, code: str) -> Optional[float]:
        key = (td, code)
        if key not in self._next_close:
            row = self.conn.execute(
                "SELECT close_price FROM kline_data WHERE stock_code=? "
                "AND substr(time_key,1,10) > ? ORDER BY time_key LIMIT 1",
                (code, td)).fetchone()
            cp = float(row["close_price"] or 0) if row else 0.0
            self._next_close[key] = cp if cp > 0 else None
        return self._next_close[key]

    def load_events(self, td: str) -> list[dict]:
        events: list[dict] = []
        if self._table_exists("sniper_signals"):
            rows = self.conn.execute(
                "SELECT time, stock_code, stock_name, price, strength, detail "
                "FROM sniper_signals WHERE trade_date=? AND signal_type='mega_buy' "
                "AND is_red=0 ORDER BY time", (td,)).fetchall()
            seen = set()
            for r in rows:
                if r["stock_code"] in seen:
                    continue
                ep = self._hhmm(td, r["time"])
                if ep is None:
                    continue
                events.append({"date": td, "cat": "sniper_mega_buy",
                               "code": r["stock_code"],
                               "name": r["stock_name"] or r["stock_code"], "epoch": ep,
                               "time": r["time"], "strength": r["strength"],
                               "price": float(r["price"] or 0)})
                seen.add(r["stock_code"])
        if self._table_exists("signal_pipeline"):
            rows = self.conn.execute(
                "SELECT timestamp, stock_code, stock_name, source, strength "
                "FROM signal_pipeline WHERE trade_date=? AND direction='BUY' "
                "ORDER BY timestamp", (td,)).fetchall()
            seen = set()
            for r in rows:
                if r["source"] in self.exclude_sources:
                    continue
                key = (r["source"], r["stock_code"])
                if key in seen:
                    continue
                dt = _parse_dt(r["timestamp"])
                if dt is None:
                    continue
                ep = int(dt.replace(tzinfo=HK).timestamp() * 1000)
                events.append({"date": td, "cat": "pipe_" + (r["source"] or "?"),
                               "code": r["stock_code"],
                               "name": r["stock_name"] or r["stock_code"], "epoch": ep,
                               "time": dt.strftime("%H:%M"), "strength": r["strength"],
                               "price": 0.0})
                seen.add(key)
        return events

    def _hhmm(self, td: str, hhmm: Optional[str]) -> Optional[int]:
        if not hhmm:
            return None
        try:
            parts = hhmm.split(":")
            h, m = int(parts[0]), int(parts[1])
            s = int(parts[2]) if len(parts) > 2 else 0
            d = date.fromisoformat(td)
            return int(datetime(d.year, d.month, d.day, h, m, s, tzinfo=HK).timestamp() * 1000)
        except (ValueError, IndexError):
            return None

    def evaluate(self, ev: dict) -> Optional[dict]:
        ticks = self.ticks(ev["date"], ev["code"])
        if not ticks:
            return None
        ts = [t[0] for t in ticks]
        i = bisect_left(ts, ev["epoch"])
        if i >= len(ticks):
            return None
        entry = ev["price"] if ev.get("price", 0) > 0 else ticks[i][1]
        if entry <= 0:
            return None
        fwd = ticks[i:]
        peak = max(p for _, p in fwd)
        trough = min(p for _, p in fwd)
        close = ticks[-1][1]
        peak_ts = max(fwd, key=lambda tp: tp[1])[0]
        mins_to_peak = round((peak_ts - ev["epoch"]) / 60000)
        open_px = ticks[0][1]
        nxt = self.next_close(ev["date"], ev["code"])
        return {
            "entry": entry,
            "peak_ret": _pct(peak, entry),
            "eod_ret": _pct(close, entry),
            "nd_ret": _pct(nxt, entry) if nxt else None,
            "maxdd": _pct(trough, entry),
            "mins_to_peak": mins_to_peak,
            "base_peak": _pct(peak, open_px),
            "base_eod": _pct(close, open_px),
            "base_nd": _pct(nxt, open_px) if nxt else None,
        }

    def run(self) -> dict:
        dates = self.trade_dates()
        by_cat: dict = {}
        all_evs = []
        base_by_stockday: dict = {}
        per_day: dict = {}
        for td in dates:
            for ev in self.load_events(td):
                o = self.evaluate(ev)
                if not o:
                    continue
                ev2 = {**ev, **o}
                all_evs.append(ev2)
                by_cat.setdefault(ev["cat"], []).append(ev2)
                base_by_stockday[(td, ev["code"])] = (o["base_peak"], o["base_eod"], o["base_nd"])
                per_day.setdefault(td, []).append(ev2)

        cats = [self._agg(cat, evs) for cat, evs in sorted(by_cat.items())]
        cats.append(self._agg("ALL_SIGNALS", all_evs))

        base_vals = list(base_by_stockday.values())
        baseline = {
            "n_stockdays": len(base_vals),
            "avg_open_to_peak": _avg(v[0] for v in base_vals),
            "avg_open_to_eod": _avg(v[1] for v in base_vals),
            "avg_open_to_nd": _avg(v[2] for v in base_vals),
        }
        days = []
        for td in dates:
            evs = per_day.get(td, [])
            bvals = [v for (d, _), v in base_by_stockday.items() if d == td]
            days.append({
                "date": td, "n": len(evs),
                "sig_avg_peak": _avg(e["peak_ret"] for e in evs),
                "sig_avg_eod": _avg(e["eod_ret"] for e in evs),
                "sig_avg_nd": _avg(e["nd_ret"] for e in evs),
                "base_avg_peak": _avg(v[0] for v in bvals),
                "base_avg_eod": _avg(v[1] for v in bvals),
                "base_avg_nd": _avg(v[2] for v in bvals),
            })
        return {"trade_dates": dates, "categories": cats, "baseline": baseline,
                "per_day": days, "events": all_evs}

    def _agg(self, cat: str, evs: list[dict]) -> dict:
        return {
            "category": cat, "n": len(evs),
            "avg_peak": _avg(e["peak_ret"] for e in evs),
            "med_peak": _med(e["peak_ret"] for e in evs),
            "avg_eod": _avg(e["eod_ret"] for e in evs),
            "med_eod": _med(e["eod_ret"] for e in evs),
            "avg_nd": _avg(e["nd_ret"] for e in evs),
            "avg_maxdd": _avg(e["maxdd"] for e in evs),
            "pct_peak_ge1": _rate((e["peak_ret"] for e in evs), lambda x: x >= 1.0),
            "pct_peak_ge2": _rate((e["peak_ret"] for e in evs), lambda x: x >= 2.0),
            "pct_eod_pos": _rate((e["eod_ret"] for e in evs), lambda x: x > 0),
            "pct_nd_pos": _rate((e["nd_ret"] for e in evs), lambda x: x > 0),
            "avg_mins_to_peak": _avg(e["mins_to_peak"] for e in evs),
        }


def print_report(s: dict, top: int) -> None:
    print(f"=== NEW-system BUY signals — multi-day intraday backtest ===")
    print(f"trade_dates: {s['trade_dates']}\n")
    hdr = (f"{'source':24s} {'n':>5s} {'avgPk':>7s} {'medPk':>7s} {'avgEOD':>7s} "
           f"{'medEOD':>7s} {'avgND':>7s} {'avgDD':>7s} {'pk1%':>6s} {'pk2%':>6s} "
           f"{'eod>0':>6s} {'nd>0':>6s} {'~mPk':>6s}")
    print(hdr)
    print("-" * len(hdr))
    for c in s["categories"]:
        mark = "  <ALL>" if c["category"] == "ALL_SIGNALS" else ""
        print(f"{c['category']:24s} {c['n']:>5d} {_f(c['avg_peak']):>7s} "
              f"{_f(c['med_peak']):>7s} {_f(c['avg_eod']):>7s} {_f(c['med_eod']):>7s} "
              f"{_f(c['avg_nd']):>7s} {_f(c['avg_maxdd']):>7s} {_f(c['pct_peak_ge1']):>6s} "
              f"{_f(c['pct_peak_ge2']):>6s} {_f(c['pct_eod_pos']):>6s} "
              f"{_f(c['pct_nd_pos']):>6s} {_f(c['avg_mins_to_peak']):>6s}{mark}")
    b = s["baseline"]
    print("-" * len(hdr))
    print(f"{'BASELINE buy@open hold':24s} {b['n_stockdays']:>5d} "
          f"{_f(b['avg_open_to_peak']):>7s} {'':>7s} {_f(b['avg_open_to_eod']):>7s} "
          f"{'':>7s} {_f(b['avg_open_to_nd']):>7s}")
    print("\nLegend: avgPk/medPk = entry->intraday high. avgEOD = entry->close. "
          "avgND = entry->next-day close (overnight).")
    print("        avgDD = avg max drawdown after entry. pk1%/2% = share peaking >= that.")
    print("        eod>0 / nd>0 = share green at close / next close. ~mPk = avg min to peak.")
    print("        BASELINE = same stock-days bought at open & held.")

    print("\n--- per-day (signal avg vs buy@open baseline) ---")
    dh = (f"{'date':12s} {'nSig':>5s} {'sigPk':>7s} {'sigEOD':>7s} {'sigND':>7s} | "
          f"{'basePk':>7s} {'baseEOD':>7s} {'baseND':>7s}")
    print(dh)
    print("-" * len(dh))
    for d in s["per_day"]:
        print(f"{d['date']:12s} {d['n']:>5d} {_f(d['sig_avg_peak']):>7s} "
              f"{_f(d['sig_avg_eod']):>7s} {_f(d['sig_avg_nd']):>7s} | "
              f"{_f(d['base_avg_peak']):>7s} {_f(d['base_avg_eod']):>7s} "
              f"{_f(d['base_avg_nd']):>7s}")


def _f(v) -> str:
    if v is None:
        return "NA"
    if isinstance(v, float):
        return f"{v:+.2f}"
    return str(v)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="simple_trade/data/trade.db")
    p.add_argument("--days", type=int, default=8)
    p.add_argument("--min-ticks", type=int, default=50000,
                   help="min ticker rows for a day to count as a full session")
    p.add_argument("--exclude-today", action="store_true")
    p.add_argument("--exclude-sources", default="低吸高抛策略,趋势反转策略,强势板块激进策略",
                   help="comma-separated signal_pipeline 'source' values to skip "
                        "(default = the deprecated legacy StrategyDispatcher strategies)")
    p.add_argument("--top", type=int, default=0)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    excl = {s.strip() for s in a.exclude_sources.split(",") if s.strip()}
    bt = BuySignalBacktester(a.db, a.days, not a.exclude_today, a.min_ticks,
                             exclude_sources=excl)
    try:
        s = bt.run()
    finally:
        bt.close()
    if a.json:
        s.pop("events", None)
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        print_report(s, a.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
