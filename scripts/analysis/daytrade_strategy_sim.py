#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Execution-realistic replay of the validated day-trade strategy (causal, no look-ahead).

Strategy (all decisions use only data up to the current streaming tick):
  Screener @10:00  : prev-day amplitude >= 8% (in-play) AND first-30min net-buy/turnover
                     >= THRESH (net-buy dominance). Evaluated from 09:30-10:00 ticks only.
  Entry            : buy at the first tick after 10:00, filled at price*(1+slip).
  Hybrid exit (two profit modes, no mode prediction needed):
     - scale out 50% @ +2%, 25% @ +4%   (locks the SPIKE before it gives back)
     - last 25% "runner": hold to close UNLESS a violent ramp (3-min trailing rise
       >= VTHR%) fires -> sell the runner (catches the SPIKE top / lets the GRIND ride)
     - hard stop -5%.
  Each sell fills at price*(1-slip). Round-trip cost = buy-side + sell-side
  (HK stamp 0.1%/side + commission + reg fees).

Causality: one forward pass per stock-day; trigger logic reads the observed price;
fills apply slippage; nothing indexes future ticks for a decision.
"""
from __future__ import annotations
import argparse, json, sqlite3
from collections import deque
from datetime import date, datetime, timezone

UTC = timezone.utc


def connect(db):
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row; return c


def ep(td, h, m=0):
    d = date.fromisoformat(td)
    return int(datetime(d.year, d.month, d.day, h, m, tzinfo=UTC).timestamp() * 1000)


def resample(ts, px, sec):
    """Resample a tick series to last-price-per-N-second snapshots (simulates the
    live 5s monitoring cadence). sec<=0 returns the tick series unchanged."""
    if sec <= 0 or not ts:
        return ts, px
    bucket = sec * 1000
    out = {}
    for t, p in zip(ts, px):
        out[t // bucket] = p
    keys = sorted(out)
    return [k * bucket for k in keys], [out[k] for k in keys]


def prev_amp(conn, td, code):
    r = conn.execute("SELECT high_price h,low_price l,open_price o FROM kline_data "
                     "WHERE stock_code=? AND substr(time_key,1,10)<? ORDER BY time_key DESC LIMIT 1",
                     (code, td)).fetchone()
    return (r["h"] - r["l"]) / r["o"] * 100 if (r and r["o"]) else None


def hybrid_net(ts, px, entry_raw, slip, cost_side, vthr):
    """Return net realized % after slippage + round-trip cost. Causal single pass."""
    entry = entry_raw * (1 + slip / 10000)        # buy fill (slippage)
    rem = 1.0; realized = 0.0; peak = entry
    pend = [(0.5, 2.0), (0.25, 4.0)]
    dq = deque()
    done = False
    for i in range(len(px)):
        p = px[i]
        while dq and px[dq[-1]] >= p:
            dq.pop()
        dq.append(i)
        while ts[i] - ts[dq[0]] > 180000:
            dq.popleft()
        rise3 = (p / px[dq[0]] - 1) * 100
        if p > peak:
            peak = p
        r_obs = (p / entry - 1) * 100                 # decision uses observed price
        fill = p * (1 - slip / 10000)                 # sell fill (slippage)
        r_fill = (fill / entry - 1) * 100
        if rem > 0 and r_obs <= -5:
            realized += rem * r_fill; rem = 0; done = True; break
        while pend and rem > 0 and r_obs >= pend[0][1]:
            f = min(pend[0][0], rem); realized += f * r_fill; rem -= f; pend.pop(0)
        if rem > 0 and not pend and rise3 >= vthr and r_obs > 0.5:
            realized += rem * r_fill; rem = 0; done = True; break
    if not done and rem > 0:
        realized += rem * ((px[-1] * (1 - slip / 10000) / entry - 1) * 100)
    return realized - 2 * cost_side / 100             # buy-side + sell-side cost


def fast_net(ts, px, entry_raw, slip, cost_side):
    entry = entry_raw * (1 + slip / 10000)
    rem = 1.0; realized = 0.0; peak = entry; pend = [(0.5, 2.0), (0.5, 4.0)]; sold = False; done = False
    for p in px:
        if p > peak:
            peak = p
        r_obs = (p / entry - 1) * 100; r_fill = (p * (1 - slip / 10000) / entry - 1) * 100
        if rem > 0 and r_obs <= -3:
            realized += rem * r_fill; rem = 0; done = True; break
        while pend and rem > 0 and r_obs >= pend[0][1]:
            f = min(pend[0][0], rem); realized += f * r_fill; rem -= f; pend.pop(0); sold = True
        if rem > 0 and sold and (p / peak - 1) * 100 <= -1.5:
            realized += rem * r_fill; rem = 0; done = True; break
    if not done and rem > 0:
        realized += rem * ((px[-1] * (1 - slip / 10000) / entry - 1) * 100)
    return realized - 2 * cost_side / 100


def run(conn, net_thr, slip, cost_side, vthr, resample_sec=0):
    dates = [r["trade_date"] for r in conn.execute(
        "SELECT trade_date,COUNT(*) n FROM ticker_data GROUP BY trade_date HAVING n>=50000 ORDER BY trade_date")]
    rows = []
    for td in dates:
        t0930 = ep(td, 1, 30); t1000 = ep(td, 2, 0)
        agg = conn.execute(
            """SELECT stock_code,
               SUM(CASE WHEN timestamp BETWEEN ? AND ? THEN (CASE direction WHEN 'BUY' THEN turnover WHEN 'SELL' THEN -turnover ELSE 0 END) ELSE 0 END)/10000.0 net30,
               SUM(CASE WHEN timestamp BETWEEN ? AND ? THEN turnover ELSE 0 END)/10000.0 turn30
               FROM ticker_data WHERE trade_date=? AND price>0 GROUP BY stock_code""",
            (t0930, t1000, t0930, t1000, td)).fetchall()
        for a in agg:
            if not a["turn30"] or a["turn30"] <= 0 or a["net30"] / a["turn30"] * 100 < net_thr:
                continue
            if (prev_amp(conn, td, a["stock_code"]) or 0) < 8:
                continue
            rs = conn.execute("SELECT timestamp,price FROM ticker_data WHERE trade_date=? AND "
                              "stock_code=? AND price>0 ORDER BY timestamp", (td, a["stock_code"])).fetchall()
            fts = [int(r["timestamp"]) for r in rs if int(r["timestamp"]) > t1000]
            fpx = [float(r["price"]) for r in rs if int(r["timestamp"]) > t1000]
            pcr = conn.execute("SELECT price FROM ticker_data WHERE trade_date=? AND stock_code=? AND "
                               "timestamp<=? AND price>0 ORDER BY timestamp DESC LIMIT 1",
                               (td, a["stock_code"], t1000)).fetchone()
            if not pcr or len(fpx) < 10:
                continue
            entry = float(pcr["price"]); peak = max(fpx); pr = (peak / entry - 1) * 100
            cr = (fpx[-1] / entry - 1) * 100; cap = cr / pr if pr > 0.5 else None
            mode = "dud" if pr < 2 else ("grind" if (cap and cap >= 0.55)
                                         else ("spike" if (cap is not None and cap < 0.3) else "mixed"))
            # mode classification uses full ticks (ground truth of what the stock did);
            # the EXIT execution runs on the resampled series (what the live 5s loop sees)
            xts, xpx = resample(fts, fpx, resample_sec)
            rows.append({"td": td, "mode": mode,
                         "hyb": hybrid_net(xts, xpx, entry, slip, cost_side, vthr),
                         "fast": fast_net(xts, xpx, entry, slip, cost_side)})
    return dates, rows


def _agg(rows, key):
    n = len(rows)
    if not n:
        return None
    vals = [r[key] for r in rows]
    wins = [v for v in vals if v > 0]
    return {"n": n, "avg_net": round(sum(vals) / n, 3), "total_net": round(sum(vals), 1),
            "win_rate": round(len(wins) / n * 100, 1),
            "avg_win": round(sum(wins) / len(wins), 3) if wins else 0,
            "avg_loss": round(sum(v for v in vals if v <= 0) / max(1, n - len(wins)), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="simple_trade/data/trade.db")
    ap.add_argument("--net-thr", type=float, default=5.0, help="early net-buy/turnover %% screen")
    ap.add_argument("--slip-bps", type=float, default=8.0, help="per-side slippage bps")
    ap.add_argument("--cost-side-bps", type=float, default=14.0, help="per-side stamp+comm+fee bps")
    ap.add_argument("--vthr", type=float, default=4.0, help="runner velocity trigger (3min rise %%)")
    ap.add_argument("--resample-sec", type=int, default=0, help="resample exit to N-sec snapshots (0=tick; 5=live cadence)")
    a = ap.parse_args()
    conn = connect(a.db)
    dates, rows = run(conn, a.net_thr, a.slip_bps, a.cost_side_bps, a.vthr, a.resample_sec)
    conn.close()
    mv = [r for r in rows if r["mode"] != "dud"]
    out = {"dates": dates, "params": {"net_thr": a.net_thr, "slip_bps": a.slip_bps,
                                      "cost_side_bps": a.cost_side_bps, "round_trip_friction_pct": round((2 * a.cost_side_bps + 2 * a.slip_bps) / 100, 3),
                                      "vthr": a.vthr},
           "n_candidates": len(rows),
           "mode_counts": {m: sum(1 for r in rows if r["mode"] == m) for m in ["spike", "grind", "mixed", "dud"]},
           "hybrid": {"all": _agg(rows, "hyb"), "movers": _agg(mv, "hyb"),
                      "spike": _agg([r for r in rows if r["mode"] == "spike"], "hyb"),
                      "grind": _agg([r for r in rows if r["mode"] == "grind"], "hyb"),
                      "per_day": {td: round(sum(r["hyb"] for r in rows if r["td"] == td) / max(1, len([r for r in rows if r["td"] == td])), 3) for td in dates}},
           "fast_for_compare": {"all": _agg(rows, "fast"), "movers": _agg(mv, "fast")}}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
