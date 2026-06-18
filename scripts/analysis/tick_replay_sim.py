#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Execution-realistic tick-replay simulator (causal, no look-ahead).

Unlike the event-driven backtests, this STREAMS each stock-day's ticks in
chronological order and makes every decision using ONLY the current tick + state
built from past ticks. Forward ticks are seen only as they arrive (to trigger
targets/stops), never indexed ahead for a decision. It models realistic fills:
entry/exit slippage + round-trip commission/stamp.

It answers: under realistic execution, does filtering mega_buy by the one
rigorously-validated factor (前日振幅>=8, "in-play" stock) + a pullback entry +
scale-out exit actually beat the current "all signals, buy now, hold to close"?

Causality contract (audited):
  - entry filter uses only prior-day klines + today's OPEN (known at 09:30).
  - signal consumed at its real timestamp; entry fills at the FIRST tick at/after
    the decision, or (pullback) the first tick that reaches the limit.
  - exits trigger on the streaming tick that crosses the level; fill at that tick.
  - one forward pass per stock-day; no random access to future prices for decisions.
"""
from __future__ import annotations
import argparse, json, sqlite3
from datetime import date, datetime, timedelta, timezone

HK = timezone(timedelta(hours=8))


def connect(db):
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row; return c


def tick_days(conn, min_ticks=50000):
    return [r["trade_date"] for r in conn.execute(
        "SELECT trade_date,COUNT(*) n FROM ticker_data GROUP BY trade_date "
        "HAVING n>=? ORDER BY trade_date", (min_ticks,))]


def daily_factors(conn, td, code):
    """Causal: only prior-day klines + today's open."""
    b = [dict(r) for r in conn.execute(
        "SELECT substr(time_key,1,10) d,open_price o,high_price h,low_price l,close_price c "
        "FROM kline_data WHERE stock_code=? AND substr(time_key,1,10)<=? "
        "ORDER BY time_key DESC LIMIT 8", (code, td))]
    if len(b) < 6:
        return None
    today = b[0] if b[0]["d"] == td else None
    idx = 1 if today else 0
    if len(b) < idx + 6:
        return None
    prev = b[idx]
    f = {
        "prev_amp": (prev["h"] - prev["l"]) / prev["o"] * 100 if prev["o"] else 0,
        "prev_chg": (prev["c"] - prev["o"]) / prev["o"] * 100 if prev["o"] else 0,
        "today_open": today["o"] if today else None,
    }
    return f


def load_ticks(conn, td, code):
    return [(int(r["timestamp"]), float(r["price"]))
            for r in conn.execute(
                "SELECT timestamp,price FROM ticker_data WHERE trade_date=? AND "
                "stock_code=? AND price>0 ORDER BY timestamp", (td, code)).fetchall()]


def signals(conn, td):
    out = []; seen = set()
    for r in conn.execute(
            "SELECT time,stock_code,price FROM sniper_signals WHERE trade_date=? AND "
            "signal_type='mega_buy' AND is_red=0 ORDER BY time", (td,)):
        if r["stock_code"] in seen:
            continue
        seen.add(r["stock_code"])
        try:
            h, m = r["time"].split(":")[:2]; d = date.fromisoformat(td)
            ep = int(datetime(d.year, d.month, d.day, int(h), int(m), tzinfo=HK).timestamp() * 1000)
        except (ValueError, IndexError):
            continue
        out.append({"code": r["stock_code"], "ep": ep,
                    "price": float(r["price"]) if (r["price"] and r["price"] > 0) else None})
    return out


# ---- the causal replay of ONE trade ----
def replay_trade(ticks, sig_ep, sig_price, strat, slip, cost_bps, extra_exit_bps):
    """Single forward pass. Returns (net_pct, exit_reason) or (None, 'no_fill')."""
    entry_style = strat["entry"]; exit_style = strat["exit"]
    state = "FLAT"; entry = None; deadline = sig_ep + strat.get("pb_timeout_min", 30) * 60_000
    rem = 1.0; realized = 0.0; peak = 0.0; n_exits = 0
    pend = list(strat.get("tranches", []))
    limit = (sig_price * (1 - strat.get("pb_pct", 1.0) / 100)) if (sig_price and entry_style == "pullback") else None
    for ts, p in ticks:
        if state == "FLAT":
            if ts < sig_ep:
                continue
            if entry_style == "immediate":
                entry = p * (1 + slip / 10000); peak = entry; state = "LONG"
            elif entry_style == "pullback":
                if limit is None:
                    return None, "no_limit"
                state = "WAIT"
        if state == "WAIT":
            if ts > deadline:
                return None, "no_fill"
            if p <= limit:
                entry = p * (1 + slip / 10000); peak = entry; state = "LONG"
            else:
                continue
        if state == "LONG":
            if p > peak:
                peak = p
            r = (p / entry - 1) * 100
            # hard stop
            if r <= strat["hard_stop"]:
                realized += rem * r; n_exits += 1; rem = 0; return _net(realized, n_exits, cost_bps, extra_exit_bps), "stop"
            if exit_style == "scaleout":
                sold_now = False
                while pend and rem > 0 and r >= pend[0][1]:
                    fr = min(pend[0][0], rem); realized += fr * r; rem -= fr; pend.pop(0); n_exits += 1; sold_now = True
                if rem > 0 and (rem < 1.0) and (p / peak - 1) * 100 <= -strat["trail"]:
                    realized += rem * r; n_exits += 1; rem = 0
                    return _net(realized, n_exits, cost_bps, extra_exit_bps), "trail"
            # hold_close: nothing intraday
    # close remainder at last tick
    if state == "LONG" and rem > 0:
        r = (ticks[-1][1] / entry - 1) * 100
        realized += rem * r; n_exits += 1
        return _net(realized, n_exits, cost_bps, extra_exit_bps), "close"
    return None, "no_fill"


def _net(gross, n_exits, cost_bps, extra_exit_bps):
    # slippage already in fill prices; subtract round-trip commission/stamp + per-extra-exit fee
    return round(gross - cost_bps / 100 - max(0, n_exits - 1) * extra_exit_bps / 100, 3)


STRATEGIES = {
    "A_现状(全部/立即/死拿)": {"filter": "all", "entry": "immediate", "exit": "hold_close", "hard_stop": -99},
    "B_振幅过滤/立即/死拿": {"filter": "amp8", "entry": "immediate", "exit": "hold_close", "hard_stop": -99},
    "C_振幅过滤/回踩-1/分批": {"filter": "amp8", "entry": "pullback", "pb_pct": 1.0, "exit": "scaleout",
                       "tranches": [[0.5, 3], [0.25, 6]], "trail": 4, "hard_stop": -5},
    "D_全部/回踩-1/分批": {"filter": "all", "entry": "pullback", "pb_pct": 1.0, "exit": "scaleout",
                     "tranches": [[0.5, 3], [0.25, 6]], "trail": 4, "hard_stop": -5},
    "E_振幅过滤/立即/分批": {"filter": "amp8", "entry": "immediate", "exit": "scaleout",
                     "tranches": [[0.5, 3], [0.25, 6]], "trail": 4, "hard_stop": -5},
}


def passes_filter(strat, f):
    if strat["filter"] == "all":
        return True
    if strat["filter"] == "amp8":
        return f["prev_amp"] >= 8
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="simple_trade/data/trade.db")
    ap.add_argument("--slip-bps", type=float, default=5.0, help="per-side slippage")
    ap.add_argument("--cost-bps", type=float, default=20.0, help="round-trip commission+stamp")
    ap.add_argument("--extra-exit-bps", type=float, default=3.0, help="fee per extra partial exit")
    a = ap.parse_args()
    conn = connect(a.db); dates = tick_days(conn)
    agg = {s: {"net": [], "by_day": {}, "fills": 0, "eligible": 0, "reasons": {}} for s in STRATEGIES}
    for td in dates:
        sigs = signals(conn, td)
        for sg in sigs:
            f = daily_factors(conn, td, sg["code"])
            if not f:
                continue
            ticks = load_ticks(conn, td, sg["code"])
            if len(ticks) < 20:
                continue
            sig_price = sg["price"] if sg["price"] else None
            for sname, strat in STRATEGIES.items():
                if not passes_filter(strat, f):
                    continue
                agg[sname]["eligible"] += 1
                sp = sig_price
                if sp is None:
                    # use first tick at/after signal as ref for pullback limit
                    sp = next((p for ts, p in ticks if ts >= sg["ep"]), None)
                net, reason = replay_trade(ticks, sg["ep"], sp, strat,
                                           a.slip_bps, a.cost_bps, a.extra_exit_bps)
                agg[sname]["reasons"][reason] = agg[sname]["reasons"].get(reason, 0) + 1
                if net is None:
                    continue
                agg[sname]["fills"] += 1
                agg[sname]["net"].append(net)
                agg[sname]["by_day"].setdefault(td, []).append(net)
    out = {"dates": dates, "slip_bps": a.slip_bps, "cost_bps": a.cost_bps,
           "extra_exit_bps": a.extra_exit_bps, "strategies": []}
    for sname, d in agg.items():
        net = d["net"]; n = len(net)
        if not n:
            out["strategies"].append({"strategy": sname, "n_fills": 0}); continue
        wins = [x for x in net if x > 0]; losses = [x for x in net if x <= 0]
        per_day = {td: round(sum(v) / len(v), 3) for td, v in d["by_day"].items()}
        out["strategies"].append({
            "strategy": sname, "eligible": d["eligible"], "n_fills": n,
            "fill_rate": round(n / d["eligible"] * 100, 1) if d["eligible"] else 0,
            "net_avg": round(sum(net) / n, 3), "net_total": round(sum(net), 1),
            "win_rate": round(len(wins) / n * 100, 1),
            "avg_win": round(sum(wins) / len(wins), 3) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 3) if losses else 0,
            "per_day_net_avg": per_day, "exit_reasons": d["reasons"],
        })
    conn.close()
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
