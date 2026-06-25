#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把线上实际触发的 R10(量价背离)按"触发时已开盘多少分钟"分桶, 看各时段 lift over 随机,
回答: 开盘预热门该切在几分钟。只读, 复用 warning harness 方法学。
用法: python3 - --db 'file:/opt/.../trade.db?mode=ro' --days 8 --controls 6 < backtest_r10_by_time.py
"""
from __future__ import annotations
import argparse, sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/opt/futu_trade_sys/scripts/analysis")
import backtest_warning_signals as H  # noqa: E402

HK = timezone(timedelta(hours=8))
BUCKETS = [(0, 10), (10, 30), (30, 60), (60, 150), (150, 999)]  # elapsed trading minutes


def elapsed_min(epoch_ms: int) -> float:
    dt = datetime.fromtimestamp(epoch_ms / 1000, HK)
    m = dt.hour * 60 + dt.minute + dt.second / 60.0
    o, mc, no = 9 * 60 + 30, 12 * 60, 13 * 60
    if m < o:
        return 0.0
    if m <= mc:
        return m - o
    if m < no:
        return 150.0
    return 150.0 + (m - no)


def bucket_name(em: float) -> str:
    for lo, hi in BUCKETS:
        if lo <= em < hi:
            return f"t{lo:03d}_{hi if hi != 999 else 'EOD'}"
    return "tEOD"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=H.DEFAULT_DB_PATH)
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--controls", type=int, default=6)
    ap.add_argument("--hit-threshold", type=float, default=1.0)
    a = ap.parse_args()

    bt = H.WarningSignalBacktester(
        db_path=a.db, days=a.days, include_today=False, min_tick_rows=1000,
        cooldown_minutes=15, controls=a.controls, hit_threshold=a.hit_threshold,
        categories={"flow_sell"}, seed=20260615, max_per_category=None)
    dates = bt._load_trade_dates()
    print(f"trade_dates: {dates}")

    # 线上实际触发的 R10, 按时段重新打 category
    r10 = [e for e in bt._dedupe(bt._load_flow_sell(dates)) if e.category == "flow_sell_r10"]
    evs = [H.WarningEvent(e.trade_date, e.stock_code, e.stock_name,
                          bucket_name(elapsed_min(e.epoch_ms)), e.direction,
                          e.epoch_ms, e.signal_price, e.detail, e.event_id) for e in r10]
    # 全量(对照基准)再加一个 all 桶
    evs_all = evs + [H.WarningEvent(e.trade_date, e.stock_code, e.stock_name, "ALL",
                                    e.direction, e.epoch_ms, e.signal_price, e.detail, e.event_id)
                     for e in r10]

    groups: dict = {}
    for e in evs_all:
        groups.setdefault((e.trade_date, e.stock_code), []).append(e)
    results: dict = {}
    for (td, code), gevs in groups.items():
        ticks = bt._load_ticks(td, code)
        if not ticks:
            continue
        ts_list = [t[0] for t in ticks]
        real_ts = sorted(e.epoch_ms for e in gevs)
        for e in gevs:
            b = results.setdefault(e.category, {"direction": e.direction, "signal": [], "control": []})
            so = bt._evaluate(ticks, ts_list, e.epoch_ms, e.signal_price, td, code)
            if so:
                b["signal"].append(so)
            for cts in bt._control_times(ts_list, real_ts):
                co = bt._evaluate(ticks, ts_list, cts, 0.0, td, code)
                if co:
                    b["control"].append(co)

    thr = a.hit_threshold
    print(f"\n{'bucket(开盘后分钟)':18s} {'n':>5s} {'hit%':>6s} {'ctlHit':>7s} {'liftpp':>7s} {'retLift':>8s} {'verdict':>14s}")
    print("-" * 70)
    order = {"t000_10": 0, "t010_30": 1, "t030_60": 2, "t060_150": 3, "t150_EOD": 4, "ALL": 9}
    for cat in sorted(results, key=lambda x: order.get(x, 8)):
        d = results[cat]["direction"]
        s = H._stats(results[cat]["signal"], d, thr)
        c = H._stats(results[cat]["control"], d, thr)
        rl = H._sub(s["hit_eod"], c["hit_eod"])
        rt = H._sub(c["avg_eod"], s["avg_eod"]) if d == H.BEARISH else H._sub(s["avg_eod"], c["avg_eod"])
        f = lambda x: "NA" if x is None else f"{x:+.2f}"
        print(f"{cat:18s} {s['n']:>5d} {f(s['hit_eod']):>6s} {f(c['hit_eod']):>7s} {f(rl):>7s} {f(rt):>8s} {H._verdict(s['n'], rl, rt):>14s}")
    print("\n读法: 各桶=触发时已开盘N分钟的 R10; lift 越低=该时段越像噪声。看预热门切哪里能去掉低 lift 桶又保住整体。")
    bt.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
