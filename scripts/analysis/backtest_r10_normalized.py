#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R10 量价背离 — 旧口径 vs 时段归一化(L2)口径 的回放对比回测 (只读)。

问题: R10 用「累计成交额 / 日均成交额 < 0.7」判缩量, 开盘几分钟累计天然极小 → 必判缩量,
开盘假信号 (用户案例: 09:33 @458 "量仅6%")。L2: 把分母换成「日均 × 该时点应有累计占比(U型剖面)」,
并加最小数据地板, 使"缩量"是相对当下时点的真缩量。

本脚本在历史逐笔上回放 R10, 复用现有 warning harness 的安慰剂对照 lift 方法学, 对比三列:
  r10_live      : capital_flow_signals 里实际触发的 R10 (旧口径,精确) — 基准/harness自检
  r10_recon_old : 从 ticker_data 重建 + 旧口径 — 校验重建保真度(应≈live)
  r10_recon_new : 重建 + 时段归一化 + 数据地板(elapsed≥WARMUP) — 候选

口径变更必须重测后才上线; 本脚本只读、不改任何生产规则。
用法: python3 - --db 'file:/opt/.../trade.db?mode=ro' --days 8 < backtest_r10_normalized.py
"""
from __future__ import annotations

import argparse
import os
import sys
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone

# 复用现有 harness 的方法学(安慰剂对照 + EOD命中 lift + verdict)
sys.path.insert(0, "/opt/futu_trade_sys/scripts/analysis")
sys.path.insert(0, os.path.join(os.getcwd(), "scripts", "analysis"))
import backtest_warning_signals as H  # noqa: E402

HK = timezone(timedelta(hours=8))

# R10 参数(与生产一致)
NEAR_HIGH_PCT = 0.98
MIN_CHANGE_PCT = 1.0
SHRINK_RATIO = 0.7
COOLDOWN_MS = 900 * 1000   # R10 cooldown 900s
WARMUP_MIN = 10            # L2 数据地板: 开盘后 ≥10 分钟才判(避开 phase1 + 极小样本方差)

# 日内累计成交量 U 型剖面: elapsed_trading_minutes -> 应有累计占全天比
# (HK 连续竞价 330 分钟; 开盘/收盘重, 午间轻; 粗略全市场近似)
PROFILE = [(0, 0.0), (15, 0.12), (30, 0.20), (60, 0.31), (90, 0.39),
           (120, 0.46), (150, 0.52), (180, 0.58), (210, 0.64),
           (240, 0.71), (270, 0.79), (300, 0.88), (330, 1.0)]


def expected_fraction(elapsed_min: float) -> float:
    if elapsed_min <= 0:
        return 0.001
    if elapsed_min >= 330:
        return 1.0
    for i in range(1, len(PROFILE)):
        m0, f0 = PROFILE[i - 1]
        m1, f1 = PROFILE[i]
        if elapsed_min <= m1:
            return f0 + (f1 - f0) * (elapsed_min - m0) / (m1 - m0)
    return 1.0


def elapsed_trading_minutes(epoch_ms: int) -> float:
    dt = datetime.fromtimestamp(epoch_ms / 1000, HK)
    mins = dt.hour * 60 + dt.minute + dt.second / 60.0
    open_m, morn_close, noon_open = 9 * 60 + 30, 12 * 60, 13 * 60
    if mins < open_m:
        return 0.0
    if mins <= morn_close:
        return mins - open_m
    if mins < noon_open:
        return 150.0
    return 150.0 + (mins - noon_open)


def load_ticks_tv(conn, trade_date, stock_code):
    """(ts, price, turnover_increment) 当日逐笔。"""
    rows = conn.execute(
        "SELECT timestamp, price, turnover FROM ticker_data "
        "WHERE trade_date=? AND stock_code=? AND price>0 ORDER BY timestamp",
        (trade_date, stock_code)).fetchall()
    return [(int(r["timestamp"]), float(r["price"]), float(r["turnover"] or 0)) for r in rows]


def avg_daily_turnover_map(conn, dates, stocks):
    """每股: 在窗口内(各天)日总成交额的均值。用于 ratio 分母(留一: 评估日用其它天均值)。"""
    ph_d = ",".join("?" for _ in dates)
    rows = conn.execute(
        f"SELECT trade_date, stock_code, SUM(turnover) tot FROM ticker_data "
        f"WHERE trade_date IN ({ph_d}) AND price>0 GROUP BY trade_date, stock_code",
        list(dates)).fetchall()
    by_stock: dict = {}
    for r in rows:
        by_stock.setdefault(r["stock_code"], {})[r["trade_date"]] = float(r["tot"] or 0)
    return by_stock


def prev_close_map(conn, dates, stocks):
    """每(日,股) 的前收(取 kline_data 上一日 close); 没有则 None(回退用当日开盘)。"""
    out: dict = {}
    for code in stocks:
        krows = conn.execute(
            "SELECT substr(time_key,1,10) d, close_price FROM kline_data "
            "WHERE stock_code=? ORDER BY time_key", (code,)).fetchall()
        kl = [(r["d"], float(r["close_price"] or 0)) for r in krows if r["close_price"]]
        for d in dates:
            prev = [c for (dd, c) in kl if dd < d]
            out[(d, code)] = prev[-1] if prev else None
    return out


def replay_r10(conn, dates, normalized: bool, adt_map, pc_map):
    """回放 R10, 返回 WarningEvent 列表(category=固定名)。"""
    cat = "r10_recon_new" if normalized else "r10_recon_old"
    events = []
    ph_d = ",".join("?" for _ in dates)
    pairs = conn.execute(
        f"SELECT DISTINCT trade_date, stock_code FROM ticker_data "
        f"WHERE trade_date IN ({ph_d}) AND price>0", list(dates)).fetchall()
    for pr in pairs:
        td, code = pr["trade_date"], pr["stock_code"]
        name = code
        # 日均(留一): 该股其它天的日总额均值
        days_tot = adt_map.get(code, {})
        others = [v for d, v in days_tot.items() if d != td and v > 0]
        if not others:
            continue
        adt = sum(others) / len(others)
        if adt <= 0:
            continue
        base = pc_map.get((td, code))   # 前收
        ticks = load_ticks_tv(conn, td, code)
        if len(ticks) < 50:
            continue
        if not base or base <= 0:
            base = ticks[0][1]          # 回退: 当日开盘价
        cum_tv = 0.0
        day_high = 0.0
        last_fire = -10 ** 15
        for ts, price, tvi in ticks:
            cum_tv += tvi
            if price > day_high:
                day_high = price
            if day_high <= 0 or price <= 0:
                continue
            # 价格接近日高 + 涨幅≥1
            if price < day_high * NEAR_HIGH_PCT:
                continue
            if base <= 0 or (price / base - 1) * 100 < MIN_CHANGE_PCT:
                continue
            if cum_tv <= 0:
                continue
            if normalized:
                em = elapsed_trading_minutes(ts)
                if em < WARMUP_MIN:           # 数据地板
                    continue
                denom = adt * expected_fraction(em)
            else:
                denom = adt
            if denom <= 0:
                continue
            ratio = cum_tv / denom
            if ratio >= SHRINK_RATIO:
                continue
            if ts - last_fire < COOLDOWN_MS:   # 冷却
                continue
            last_fire = ts
            events.append(H.WarningEvent(td, code, name, cat, H.BEARISH, ts,
                                         price, f"recon ratio={ratio:.2f}", f"{cat}:{td}:{code}:{ts}"))
    return events


def run_events(bt, events_by_cat, dates):
    """复用 harness 的分组+评估+对照+统计(照搬 run() 的循环)。"""
    groups: dict = {}
    for cat, evs in events_by_cat.items():
        for e in evs:
            groups.setdefault((e.trade_date, e.stock_code), []).append(e)
    results: dict = {}
    for (td, code), evs in groups.items():
        ticks = bt._load_ticks(td, code)
        if not ticks:
            continue
        ts_list = [t[0] for t in ticks]
        real_ts = sorted(e.epoch_ms for e in evs)
        for e in evs:
            b = results.setdefault(e.category, {"direction": e.direction, "signal": [], "control": []})
            so = bt._evaluate(ticks, ts_list, e.epoch_ms, e.signal_price, td, code)
            if so:
                b["signal"].append(so)
            for cts in bt._control_times(ts_list, real_ts):
                co = bt._evaluate(ticks, ts_list, cts, 0.0, td, code)
                if co:
                    b["control"].append(co)
    return results


def summarize(results, thr):
    rows = []
    for cat, data in sorted(results.items()):
        d = data["direction"]
        s = H._stats(data["signal"], d, thr)
        c = H._stats(data["control"], d, thr)
        rate_lift = H._sub(s["hit_eod"], c["hit_eod"])
        ret_lift = H._sub(c["avg_eod"], s["avg_eod"]) if d == H.BEARISH else H._sub(s["avg_eod"], c["avg_eod"])
        rows.append((cat, s["n"], s["hit_eod"], c["hit_eod"], rate_lift, ret_lift,
                     s["hit_next"], c["hit_next"], H._verdict(s["n"], rate_lift, ret_lift)))
    return rows


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
    conn = bt.conn
    conn.row_factory = __import__("sqlite3").Row
    dates = bt._load_trade_dates()
    print(f"trade_dates: {dates}")

    # 列1: live-fired R10 (旧口径,精确) via harness
    live_events = [e for e in bt._load_flow_sell(dates) if e.category == "flow_sell_r10"]
    for e in live_events:
        object.__setattr__(e, "category", "r10_live") if False else None
    live_events = [H.WarningEvent(e.trade_date, e.stock_code, e.stock_name, "r10_live",
                                  e.direction, e.epoch_ms, e.signal_price, e.detail, e.event_id)
                   for e in live_events]

    # 列2/3: 重建 old / new
    pairs = conn.execute(
        f"SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date IN ({','.join('?' for _ in dates)}) AND price>0",
        list(dates)).fetchall()
    stocks = [r["stock_code"] for r in pairs]
    adt_map = avg_daily_turnover_map(conn, dates, stocks)
    pc_map = prev_close_map(conn, dates, stocks)
    recon_old = replay_r10(conn, dates, False, adt_map, pc_map)
    recon_new = replay_r10(conn, dates, True, adt_map, pc_map)

    results = run_events(bt, {"r10_live": live_events,
                              "r10_recon_old": recon_old,
                              "r10_recon_new": recon_new}, dates)
    rows = summarize(results, a.hit_threshold)

    print(f"\n{'category':16s} {'n':>5s} {'hit%':>6s} {'ctlHit':>7s} {'liftpp':>7s} {'retLift':>8s} {'ndHit':>6s} {'verdict':>16s}")
    print("-" * 78)
    for cat, n, hit, ch, lp, rl, ndh, ndc, v in rows:
        f = lambda x: "NA" if x is None else f"{x:+.2f}"
        print(f"{cat:16s} {n:>5d} {f(hit):>6s} {f(ch):>7s} {f(lp):>7s} {f(rl):>8s} {f(ndh):>6s} {v:>16s}")
    print("\nliftpp = EOD命中率 − 对照命中率(pp); retLift = 比随机多跌(看跌,%); verdict: keep/demote/anti/insufficient")
    print("校验: r10_recon_old 应≈r10_live(重建保真); 对比: r10_recon_new vs r10_recon_old(归一化效果)")
    bt.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
