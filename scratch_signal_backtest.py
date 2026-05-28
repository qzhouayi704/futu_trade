#!/usr/bin/env python3
"""
各信号类型回测 — 逐分钟模拟实盘（无上帝视角）

核心区别：
  - 每分钟只用"截至当前"的数据计算 avg_abs_net / dynamic_mega
  - 信号检测逻辑与 intraday_sniper.py 完全一致
  - 信号触发后，用后续真实价格评估盈亏
"""
import sqlite3
import os
from collections import defaultdict

DB_PATH = os.environ.get("DB_PATH", "/opt/futu_trade_sys/simple_trade/data/trade.db")

# 与 intraday_sniper.py 完全一致的参数
MEGA_MULTIPLIER = 3
ACCEL_THRESHOLD = 3.0
SUSTAINED_RATIO = 0.35
SUSTAINED_MINUTES = 20
COOLDOWN_MINUTES = 15
CONFLICT_WINDOW = 15
SCAN_INTERVAL = 3

TIER_THRESHOLDS = {
    'large':  (50000, 3000, 5000, 5000),
    'mid':    (10000, 1500, 2000, 2000),
    'small':  (1000,  500,  800,  500),
}
MIN_DAILY_TURNOVER = 1000

HOLD_MINUTES = [5, 10, 15, 30]
TRADE_COST_PCT = 0.32


def load_minute_data(db, stock_code, trade_date):
    rows = db.execute("""
        SELECT
            substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
            direction, SUM(turnover) as tv, AVG(price) as ap
        FROM ticker_data
        WHERE stock_code = ? AND trade_date = ?
        GROUP BY minute, direction ORDER BY minute
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
    return timeline


def get_tier_thresholds(day_total):
    for _, (min_tv, accel_min, mega_min, reversal_min) in TIER_THRESHOLDS.items():
        if day_total >= min_tv:
            return accel_min, mega_min, reversal_min
    return 500, 800, 500


def detect_signals_realtime(timeline):
    """逐分钟模拟实盘信号检测 — 每一步只用截至当前的数据"""
    signals = []
    cooldown = {}
    prev_cum_direction = 'neutral'
    recent_signals = []

    for i, point in enumerate(timeline):
        # ====== 关键：只用截至当前分钟的数据计算动态阈值 ======
        past_data = timeline[:i + 1]

        # 当前累计成交额（模拟实盘中的 day_total）
        day_total_so_far = sum(p['turnover'] for p in past_data)
        if day_total_so_far < MIN_DAILY_TURNOVER * 0.1:  # 开盘前几分钟数据太少
            continue

        turnovers = [p['turnover'] for p in past_data if p['turnover'] > 0]
        avg_turnover = sum(turnovers) / len(turnovers) if turnovers else 0
        if avg_turnover <= 0:
            continue

        # 动态阈值 — 只用过去数据
        accel_min, mega_min, reversal_min = get_tier_thresholds(day_total_so_far)
        abs_nets = [abs(p['net']) for p in past_data if p['net'] != 0]
        avg_abs_net = sum(abs_nets) / len(abs_nets) if abs_nets else avg_turnover
        dynamic_mega = max(mega_min, avg_abs_net * MEGA_MULTIPLIER)
        dynamic_sustained = max(
            SUSTAINED_RATIO * avg_turnover * SUSTAINED_MINUTES,
            mega_min * 0.6,
        )

        is_scan = (i % SCAN_INTERVAL == 0 and i > 0)

        def can_emit(sig_type, is_red):
            if sig_type in cooldown and i - cooldown[sig_type] < COOLDOWN_MINUTES:
                return False
            cutoff = max(0, i - CONFLICT_WINDOW)
            for rs in recent_signals:
                if rs['idx'] >= cutoff:
                    if (is_red and not rs['is_red']) or (not is_red and rs['is_red']):
                        return False
            return True

        def emit(sig_type, is_red):
            cooldown[sig_type] = i
            sig = {'time': point['time'], 'is_red': is_red, 'idx': i,
                   'type': sig_type, 'price': point['price']}
            signals.append(sig)
            recent_signals.append(sig)

        # 巨量砸盘
        if point['net'] < -dynamic_mega:
            if can_emit('mega_sell', True):
                emit('mega_sell', True)

        # 巨量抢筹
        if point['net'] > dynamic_mega:
            if can_emit('mega_buy', False):
                emit('mega_buy', False)

        if is_scan:
            curr_dir = (
                'positive' if point['cum_net'] > 0
                else 'negative' if point['cum_net'] < 0
                else 'neutral'
            )

            if (prev_cum_direction == 'negative'
                    and curr_dir == 'positive'
                    and point['cum_net'] > reversal_min):
                if can_emit('reversal_bull', False):
                    emit('reversal_bull', False)

            if (prev_cum_direction == 'positive'
                    and curr_dir == 'negative'
                    and point['cum_net'] < -reversal_min):
                if can_emit('reversal_bear', True):
                    emit('reversal_bear', True)

            if i >= 6:
                recent_3 = sum(timeline[j]['net'] for j in range(i - 2, i + 1))
                prev_3 = sum(timeline[j]['net'] for j in range(i - 5, i - 2))
                if (prev_3 > 0
                        and recent_3 > prev_3 * ACCEL_THRESHOLD
                        and recent_3 > accel_min):
                    if can_emit('accel_in', False):
                        emit('accel_in', False)

            if i >= SUSTAINED_MINUTES:
                window_net = sum(
                    timeline[j]['net']
                    for j in range(i - SUSTAINED_MINUTES + 1, i + 1)
                )
                if window_net < -dynamic_sustained:
                    if can_emit('sustained_out', True):
                        emit('sustained_out', True)

            prev_cum_direction = curr_dir

    return signals


def main():
    db = sqlite3.connect(DB_PATH)

    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date DESC LIMIT 14"
    ).fetchall()]
    print(f"回测日期: {dates[-1]} ~ {dates[0]} ({len(dates)}天)")

    signal_stats = defaultdict(lambda: {
        'count': 0,
        'by_hold': defaultdict(lambda: {'correct': 0, 'total': 0, 'pcts': []}),
    })

    total_signals = 0
    for di, trade_date in enumerate(dates):
        day_codes = [r[0] for r in db.execute(
            "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date = ?",
            (trade_date,)
        ).fetchall()]

        day_count = 0
        for code in day_codes:
            tl = load_minute_data(db, code, trade_date)
            if len(tl) < 10:
                continue

            sigs = detect_signals_realtime(tl)
            for sig in sigs:
                sig_idx = sig['idx']
                sig_price = sig['price']
                if sig_price <= 0:
                    continue

                st = signal_stats[sig['type']]
                st['count'] += 1
                day_count += 1

                for hold_min in HOLD_MINUTES:
                    target_idx = min(sig_idx + hold_min, len(tl) - 1)
                    if target_idx <= sig_idx:
                        continue
                    exit_price = tl[target_idx]['price']
                    if exit_price <= 0:
                        continue

                    pct = (exit_price - sig_price) / sig_price * 100
                    bh = st['by_hold'][hold_min]
                    bh['total'] += 1
                    bh['pcts'].append(round(pct, 3))
                    if sig['is_red']:
                        if pct < 0:
                            bh['correct'] += 1
                    else:
                        if pct > 0:
                            bh['correct'] += 1

        total_signals += day_count
        print(f"  [{di+1}/{len(dates)}] {trade_date}: {len(day_codes)}只, {day_count}条信号")

    db.close()

    # 输出结果
    print(f"\n{'='*90}")
    print(f"  逐分钟实盘模拟回测结果 ({len(dates)}天, {total_signals}条信号)")
    print(f"  阈值计算方式: 每分钟只用截至当前的数据(无未来数据泄露)")
    print(f"{'='*90}")

    for sig_type in ['mega_buy', 'accel_in', 'reversal_bull',
                     'mega_sell', 'reversal_bear', 'sustained_out']:
        st = signal_stats.get(sig_type)
        if not st or st['count'] == 0:
            print(f"\n  {sig_type}: 无信号")
            continue

        is_red = sig_type in ('mega_sell', 'reversal_bear', 'sustained_out')
        label = "🔴卖出/警告" if is_red else "🟢买入"

        print(f"\n  {sig_type} ({label}) — 共{st['count']}条")
        print(f"  {'持有':<6} {'数量':<6} {'准确率':<8} {'平均%':<10} {'中位%':<9} {'最好%':<9} {'最差%':<9}")
        print(f"  {'-'*60}")

        for hm in HOLD_MINUTES:
            bh = st['by_hold'].get(hm)
            if not bh or bh['total'] == 0:
                continue
            pcts = sorted(bh['pcts'])
            avg = sum(pcts) / len(pcts)
            med = pcts[len(pcts) // 2]
            acc = bh['correct'] / bh['total'] * 100
            print(f"  {hm:>3}m   {bh['total']:<6} {acc:>5.1f}%   {avg:>+7.3f}%   {med:>+6.3f}%  {max(pcts):>+6.3f}%  {min(pcts):>+6.3f}%")

    # 建议
    print(f"\n{'='*90}")
    print(f"  综合建议 (基于15分钟持有期, 扣除{TRADE_COST_PCT}%交易成本)")
    print(f"{'='*90}")

    for sig_type in ['mega_buy', 'accel_in', 'reversal_bull']:
        st = signal_stats.get(sig_type)
        if not st or st['count'] == 0:
            continue
        bh = st['by_hold'].get(15, st['by_hold'].get(10, {}))
        if not bh or bh.get('total', 0) == 0:
            continue
        pcts = bh['pcts']
        avg = sum(pcts) / len(pcts)
        net = avg - TRADE_COST_PCT
        acc = bh['correct'] / bh['total'] * 100
        if net > 0.3 and acc > 55:
            v = "✅ 可独立触发"
        elif net > 0 and acc > 50:
            v = "⚠️ 辅助确认信号"
        else:
            v = "❌ 不宜触发(负收益)"
        print(f"  {sig_type:<16} 净收益={net:+.3f}%  准确率={acc:.1f}%  → {v}")

    for sig_type in ['mega_sell', 'reversal_bear', 'sustained_out']:
        st = signal_stats.get(sig_type)
        if not st or st['count'] == 0:
            continue
        bh = st['by_hold'].get(15, {})
        if not bh or bh.get('total', 0) == 0:
            continue
        pcts = bh['pcts']
        avg = sum(pcts) / len(pcts)
        acc = bh['correct'] / bh['total'] * 100
        if acc > 65 and avg < -0.3:
            v = "✅ 有效风险信号"
        elif acc > 55:
            v = "⚠️ 弱风险信号"
        else:
            v = "❌ 无效(≈随机)"
        print(f"  {sig_type:<16} 后续跌幅={avg:+.3f}%  准确率={acc:.1f}%  → {v}")

    print()


if __name__ == '__main__':
    main()
