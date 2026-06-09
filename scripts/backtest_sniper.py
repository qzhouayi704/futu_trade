#!/usr/bin/env python3
"""
巨量抢筹信号回测 — 对比修复前后效果

用服务器 DB 中最近 5 个交易日的 ticker_data 数据，
模拟信号检测逻辑，评估去重+冷却修复后的信号质量变化。

使用方式: cd /opt/futu_trade_sys && .venv/bin/python scripts/backtest_sniper.py
"""

import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

# ============================================================
# 回测参数（与 intraday_sniper.py 保持一致）
# ============================================================
MEGA_MULTIPLIER = 5
MEGA_FLOOR_PCT = 0.02
MEGA_FLOOR_MIN = 50
MIN_DAILY_TURNOVER = 100
COOLDOWN_MINUTES = 15
CONFLICT_WINDOW_MINUTES = 15


def load_minute_data(conn, stock_code, trade_date):
    """从 ticker_data 加载分钟级聚合数据 (同 intraday_sniper)"""
    rows = conn.execute("""
        SELECT
            substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
            direction, SUM(turnover) as tv, AVG(price) as ap
        FROM ticker_data
        WHERE stock_code = ? AND trade_date = ?
        GROUP BY minute, direction
        ORDER BY minute
    """, (stock_code, trade_date)).fetchall()

    minutes = {}
    for minute, direction, turnover, avg_price in rows:
        if not ('09:15' <= minute <= '16:10'):
            continue
        if minute not in minutes:
            minutes[minute] = {'buy': 0.0, 'sell': 0.0, 'price': 0, 'price_n': 0}
        entry = minutes[minute]
        tv = float(turnover or 0)
        if direction == 'BUY':
            entry['buy'] += tv
        elif direction == 'SELL':
            entry['sell'] += tv
        if avg_price and float(avg_price) > 0:
            entry['price'] += float(avg_price)
            entry['price_n'] += 1

    timeline = []
    cum_buy, cum_sell = 0.0, 0.0
    for minute in sorted(minutes.keys()):
        e = minutes[minute]
        cum_buy += e['buy']
        cum_sell += e['sell']
        net = e['buy'] - e['sell']
        price = round(e['price'] / e['price_n'], 3) if e['price_n'] > 0 else 0
        timeline.append({
            'time': minute,
            'net': round(net / 10000, 1),
            'cum_net': round((cum_buy - cum_sell) / 10000, 1),
            'price': price,
            'turnover': round((e['buy'] + e['sell']) / 10000, 1),
        })

    turnovers = [p['turnover'] for p in timeline if p['turnover'] > 0]
    avg_turnover = sum(turnovers) / len(turnovers) if turnovers else 0
    day_total = sum(p['turnover'] for p in timeline)
    return timeline, avg_turnover, day_total


def time_diff_minutes(t1, t2):
    """HH:MM 时间差"""
    h1, m1 = int(t1[:2]), int(t1[3:])
    h2, m2 = int(t2[:2]), int(t2[3:])
    return (h2 * 60 + m2) - (h1 * 60 + m1)


def detect_mega_buy_old(timeline, avg_turnover, day_total):
    """旧逻辑: 冷却用索引，无去重"""
    mega_floor = max(MEGA_FLOOR_MIN, day_total * MEGA_FLOOR_PCT)
    abs_nets = [abs(p['net']) for p in timeline if p['net'] != 0]
    avg_abs_net = sum(abs_nets) / len(abs_nets) if abs_nets else avg_turnover
    dynamic_mega = max(mega_floor, avg_abs_net * MEGA_MULTIPLIER)

    signals = []
    cooldown_idx = {}  # signal_type -> last index

    for i, point in enumerate(timeline):
        if point['net'] > dynamic_mega:
            # 旧冷却: 索引差
            if 'mega_buy' in cooldown_idx:
                if i - cooldown_idx['mega_buy'] < COOLDOWN_MINUTES:
                    continue
            mult = point['net'] / avg_turnover if avg_turnover > 0 else 0
            cooldown_idx['mega_buy'] = i
            signals.append({
                'time': point['time'],
                'price': point['price'],
                'net': point['net'],
                'mult': mult,
            })
    return signals


def detect_mega_buy_new(timeline, avg_turnover, day_total):
    """新逻辑: 冷却用真实时间"""
    mega_floor = max(MEGA_FLOOR_MIN, day_total * MEGA_FLOOR_PCT)
    abs_nets = [abs(p['net']) for p in timeline if p['net'] != 0]
    avg_abs_net = sum(abs_nets) / len(abs_nets) if abs_nets else avg_turnover
    dynamic_mega = max(mega_floor, avg_abs_net * MEGA_MULTIPLIER)

    signals = []
    cooldown_time = {}  # signal_type -> last HH:MM

    for i, point in enumerate(timeline):
        if point['net'] > dynamic_mega:
            # 新冷却: 真实时间差
            if 'mega_buy' in cooldown_time:
                gap = time_diff_minutes(cooldown_time['mega_buy'], point['time'])
                if gap < COOLDOWN_MINUTES:
                    continue
            mult = point['net'] / avg_turnover if avg_turnover > 0 else 0
            cooldown_time['mega_buy'] = point['time']
            signals.append({
                'time': point['time'],
                'price': point['price'],
                'net': point['net'],
                'mult': mult,
            })
    return signals


def calc_signal_performance(timeline, sig_time, sig_price):
    """计算信号后30分钟和收盘价的表现"""
    # 信号后30分钟
    price_30m = None
    price_close = timeline[-1]['price'] if timeline else 0

    for p in timeline:
        gap = time_diff_minutes(sig_time, p['time'])
        if gap >= 30 and price_30m is None:
            price_30m = p['price']

    chg_30m = round((price_30m - sig_price) / sig_price * 100, 2) if price_30m and sig_price > 0 else None
    chg_close = round((price_close - sig_price) / sig_price * 100, 2) if price_close and sig_price > 0 else None

    return chg_30m, chg_close


def simulate_restart_duplicates(signals, num_restarts=5):
    """模拟旧逻辑下重启导致的重复信号"""
    return len(signals) * num_restarts


def main():
    conn = sqlite3.connect("simple_trade/data/trade.db")

    # 获取最近有数据的交易日
    dates = conn.execute(
        "SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date DESC LIMIT 10"
    ).fetchall()
    trade_dates = [d[0] for d in dates]
    print(f"Found {len(trade_dates)} trading days: {trade_dates}")

    # 获取有 ticker 数据的股票
    all_stocks = conn.execute(
        "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date IN ({})".format(
            ','.join('?' * len(trade_dates))
        ), trade_dates
    ).fetchall()
    stock_codes = [r[0] for r in all_stocks]
    print(f"Total stocks with data: {len(stock_codes)}")

    # 按日回测
    old_total_signals = 0
    new_total_signals = 0
    old_total_with_dup = 0  # 假设5次重启
    old_wins_30m = 0
    old_loses_30m = 0
    new_wins_30m = 0
    new_loses_30m = 0
    old_wins_close = 0
    old_loses_close = 0
    new_wins_close = 0
    new_loses_close = 0

    old_cooldown_violations = 0
    new_cooldown_violations = 0

    per_day_stats = []

    for td in trade_dates:
        print(f"\n=== {td} ===")
        day_old_sigs = 0
        day_new_sigs = 0
        day_old_cd_viol = 0
        day_new_cd_viol = 0

        day_old_perf = []
        day_new_perf = []

        for code in stock_codes:
            tl, avg_tv, day_total = load_minute_data(conn, code, td)
            if len(tl) < 10 or avg_tv <= 0 or day_total < MIN_DAILY_TURNOVER:
                continue

            old_sigs = detect_mega_buy_old(tl, avg_tv, day_total)
            new_sigs = detect_mega_buy_new(tl, avg_tv, day_total)

            day_old_sigs += len(old_sigs)
            day_new_sigs += len(new_sigs)

            # 检查冷却违规 (连续信号间隔 < 15分钟)
            for j in range(1, len(old_sigs)):
                gap = time_diff_minutes(old_sigs[j-1]['time'], old_sigs[j]['time'])
                if 0 < gap < 15:
                    day_old_cd_viol += 1

            for j in range(1, len(new_sigs)):
                gap = time_diff_minutes(new_sigs[j-1]['time'], new_sigs[j]['time'])
                if 0 < gap < 15:
                    day_new_cd_viol += 1

            # 信号表现
            for sig in old_sigs:
                chg_30m, chg_close = calc_signal_performance(tl, sig['time'], sig['price'])
                if chg_30m is not None:
                    day_old_perf.append(('30m', chg_30m))
                if chg_close is not None:
                    day_old_perf.append(('close', chg_close))

            for sig in new_sigs:
                chg_30m, chg_close = calc_signal_performance(tl, sig['time'], sig['price'])
                if chg_30m is not None:
                    day_new_perf.append(('30m', chg_30m))
                if chg_close is not None:
                    day_new_perf.append(('close', chg_close))

        # 统计
        old_total_signals += day_old_sigs
        new_total_signals += day_new_sigs
        old_total_with_dup += day_old_sigs * 5  # 假设5次重启
        old_cooldown_violations += day_old_cd_viol
        new_cooldown_violations += day_new_cd_viol

        for metric, chg in day_old_perf:
            if metric == '30m':
                if chg > 0: old_wins_30m += 1
                else: old_loses_30m += 1
            else:
                if chg > 0: old_wins_close += 1
                else: old_loses_close += 1

        for metric, chg in day_new_perf:
            if metric == '30m':
                if chg > 0: new_wins_30m += 1
                else: new_loses_30m += 1
            else:
                if chg > 0: new_wins_close += 1
                else: new_loses_close += 1

        old_30m_wr = old_wins_30m / max(1, old_wins_30m + old_loses_30m) * 100
        new_30m_wr = new_wins_30m / max(1, new_wins_30m + new_loses_30m) * 100

        per_day_stats.append({
            'date': td,
            'old_sigs': day_old_sigs,
            'new_sigs': day_new_sigs,
            'old_cd_viol': day_old_cd_viol,
            'new_cd_viol': day_new_cd_viol,
        })

        print(f"  Old: {day_old_sigs} signals (with dup: ~{day_old_sigs * 5}), cooldown violations: {day_old_cd_viol}")
        print(f"  New: {day_new_sigs} signals, cooldown violations: {day_new_cd_viol}")

    # ============================================================
    # 总结报告
    # ============================================================
    print("\n" + "=" * 70)
    print("                    回测总结报告")
    print("=" * 70)

    print(f"\n回测范围: {trade_dates[-1]} ~ {trade_dates[0]} ({len(trade_dates)} 个交易日)")
    print(f"覆盖股票: {len(stock_codes)} 只")

    print(f"\n--- 信号数量 ---")
    print(f"  旧逻辑信号:     {old_total_signals} 条 (重启5次后实际写入: ~{old_total_with_dup} 条)")
    print(f"  新逻辑信号:     {new_total_signals} 条")
    reduction = (1 - new_total_signals / max(1, old_total_signals)) * 100
    print(f"  信号精简率:     {reduction:.1f}%")
    dup_reduction = (1 - new_total_signals / max(1, old_total_with_dup)) * 100
    print(f"  含去重精简率:   {dup_reduction:.1f}%")

    print(f"\n--- 冷却期违规 ---")
    print(f"  旧逻辑违规:     {old_cooldown_violations} 次")
    print(f"  新逻辑违规:     {new_cooldown_violations} 次")

    print(f"\n--- 30分钟胜率 ---")
    old_30m_total = old_wins_30m + old_loses_30m
    new_30m_total = new_wins_30m + new_loses_30m
    old_30m_wr = old_wins_30m / max(1, old_30m_total) * 100
    new_30m_wr = new_wins_30m / max(1, new_30m_total) * 100
    print(f"  旧逻辑:         {old_wins_30m}W/{old_loses_30m}L = {old_30m_wr:.1f}%")
    print(f"  新逻辑:         {new_wins_30m}W/{new_loses_30m}L = {new_30m_wr:.1f}%")

    print(f"\n--- 收盘胜率 ---")
    old_close_total = old_wins_close + old_loses_close
    new_close_total = new_wins_close + new_loses_close
    old_close_wr = old_wins_close / max(1, old_close_total) * 100
    new_close_wr = new_wins_close / max(1, new_close_total) * 100
    print(f"  旧逻辑:         {old_wins_close}W/{old_loses_close}L = {old_close_wr:.1f}%")
    print(f"  新逻辑:         {new_wins_close}W/{new_loses_close}L = {new_close_wr:.1f}%")

    print(f"\n--- 每日明细 ---")
    print(f"  {'日期':<12} {'旧信号':>6} {'新信号':>6} {'旧违规':>6} {'新违规':>6}")
    for d in per_day_stats:
        print(f"  {d['date']:<12} {d['old_sigs']:>6} {d['new_sigs']:>6} {d['old_cd_viol']:>6} {d['new_cd_viol']:>6}")

    conn.close()
    print("\n✅ 回测完成")


if __name__ == '__main__':
    main()
