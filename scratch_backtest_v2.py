#!/usr/bin/env python3
"""
IntradaySniper 参数优化回测
测试多组参数，找到"信号最少但关键时刻全能捕获"的最优组合
"""
import sqlite3
from datetime import date
from collections import defaultdict

DB_PATH = "/opt/futu_trade_sys/simple_trade/data/trade.db"
TODAY = date.today().isoformat()

FOCUS_STOCKS = [
    'HK.00981', 'HK.00100', 'HK.06651', 'HK.00992',
    'HK.01879', 'HK.02631', 'HK.00068', 'HK.03033',
]

# 5个关键时刻（ground truth）
KEY_MOMENTS = [
    {'desc': '中芯09:38前预警', 'stock': 'HK.00981', 'type': 'red', 'before': '09:45', 'must': True},
    {'desc': '联想09:37加速信号', 'stock': 'HK.00992', 'type': 'green', 'before': '10:00', 'must': True},
    {'desc': 'MINIMAX开盘流出', 'stock': 'HK.00100', 'type': 'red', 'before': '10:00', 'must': True},
    {'desc': '五一视界午后加速', 'stock': 'HK.06651', 'type': 'green', 'after': '13:30', 'before': '14:30', 'must': True},
    {'desc': '曦智砸盘预警', 'stock': 'HK.01879', 'type': 'red', 'before': '10:30', 'must': False},
]

# 误报检测（这些信号如果触发了是错的）
FALSE_POSITIVES = [
    {'desc': '联想红色信号(实际赚钱)', 'stock': 'HK.00992', 'type': 'red', 'penalty': 2},
    {'desc': '五一视界早盘红色(实际涨22%)', 'stock': 'HK.06651', 'type': 'red', 'before': '12:00', 'penalty': 3},
    {'desc': 'MINIMAX午后绿色(实际暴跌)', 'stock': 'HK.00100', 'type': 'green', 'after': '13:00', 'before': '14:00', 'penalty': 3},
]


def load_minute_data(db, stock_code):
    rows = db.execute("""
        SELECT
            substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
            direction, SUM(turnover) as total_turnover,
            AVG(price) as avg_price
        FROM ticker_data
        WHERE stock_code = ? AND trade_date = ?
        GROUP BY minute, direction ORDER BY minute
    """, (stock_code, TODAY)).fetchall()

    minutes = {}
    for row in rows:
        minute, direction, turnover, avg_price = row
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
        cum_net = cum_buy - cum_sell
        price = round(e['price'] / e['price_n'], 3) if e['price_n'] > 0 else 0
        timeline.append({
            'time': minute,
            'net': round(net / 10000, 1),
            'cum_net': round(cum_net / 10000, 1),
            'price': price,
            'turnover': round((e['buy'] + e['sell']) / 10000, 1),
        })

    # 计算该股票的日均分钟成交额（用于相对阈值）
    turnovers = [p['turnover'] for p in timeline if p['turnover'] > 0]
    avg_turnover = sum(turnovers) / len(turnovers) if turnovers else 100
    return timeline, avg_turnover


def run_backtest(all_data, params):
    """用指定参数运行一次回测"""
    accel_threshold = params['accel_threshold']       # 加速倍数阈值
    accel_min_amount = params['accel_min_amount']     # 加速最小金额(万)
    mega_multiplier = params['mega_multiplier']       # 巨量砸盘倍数阈值
    mega_min_amount = params['mega_min_amount']       # 巨量最小金额(万)
    sustained_ratio = params['sustained_ratio']       # 持续流出：占日均成交额的比例
    sustained_minutes = params['sustained_minutes']   # 持续流出检查窗口(分钟)
    reversal_min = params['reversal_min']             # 资金反转最小变化量(万)
    cooldown_min = params['cooldown_min']             # 同类信号冷却期(分钟)
    conflict_window = params['conflict_window']       # 红绿互斥窗口(分钟)

    all_signals = []

    for code, (timeline, avg_turnover) in all_data.items():
        if len(timeline) < 10:
            continue

        # 动态阈值：按该股日均分钟成交额调整
        day_total_turnover = sum(p['turnover'] for p in timeline)
        dynamic_mega_min = max(mega_min_amount, day_total_turnover * 0.005)  # 至少占全天0.5%
        dynamic_sustained = max(sustained_ratio * avg_turnover * sustained_minutes, 3000)

        cooldown = {}
        prev_cum_direction = 'neutral'
        recent_signals = []  # 用于冲突检测

        for i, point in enumerate(timeline):
            minute = point['time']
            is_scan = (i % 3 == 0 and i > 0)

            def can_emit(sig_type, is_red):
                # 冷却检查
                key = f"{sig_type}_{code}"
                if key in cooldown and i - cooldown[key] < cooldown_min:
                    return False
                # 冲突检查：conflict_window分钟内不出相反信号
                cutoff_idx = max(0, i - conflict_window)
                for rs in recent_signals:
                    if rs['stock'] == code and rs['idx'] >= cutoff_idx:
                        if (is_red and rs['is_green']) or (not is_red and rs['is_red']):
                            return False
                return True

            def emit(sig_type, is_red, detail, action):
                key = f"{sig_type}_{code}"
                cooldown[key] = i
                sig = {
                    'time': minute, 'stock': code, 'type': sig_type,
                    'detail': detail, 'action': action, 'price': point['price'],
                    'is_red': is_red, 'is_green': not is_red, 'idx': i,
                }
                all_signals.append(sig)
                recent_signals.append(sig)

            # 信号1: 巨量砸盘
            if point['net'] < -max(dynamic_mega_min, avg_turnover * mega_multiplier):
                if can_emit('mega_sell', True):
                    mult = abs(point['net'] / avg_turnover) if avg_turnover > 0 else 0
                    emit('🔴 巨量砸盘', True,
                         f"净卖{point['net']:.0f}万(均值{mult:.0f}倍)",
                         '❌ 不买/止损')

            # 信号2: 巨量抢筹
            if point['net'] > max(dynamic_mega_min, avg_turnover * mega_multiplier):
                if can_emit('mega_buy', False):
                    mult = point['net'] / avg_turnover if avg_turnover > 0 else 0
                    emit('🟢 巨量抢筹', False,
                         f"净买+{point['net']:.0f}万(均值{mult:.0f}倍)",
                         '✅ 关注买入')

            if is_scan:
                curr_dir = 'positive' if point['cum_net'] > 0 else 'negative' if point['cum_net'] < 0 else 'neutral'

                # 信号3: 资金反转
                if prev_cum_direction == 'negative' and curr_dir == 'positive' and point['cum_net'] > reversal_min:
                    if can_emit('reversal_bull', False):
                        emit('🟢 资金转正', False,
                             f"累计净{point['cum_net']:.0f}万",
                             '✅ 关注入场')

                if prev_cum_direction == 'positive' and curr_dir == 'negative' and point['cum_net'] < -reversal_min:
                    if can_emit('reversal_bear', True):
                        emit('🔴 资金转负', True,
                             f"累计净{point['cum_net']:.0f}万",
                             '❌ 考虑减仓')

                # 信号4: 加速流入/流出
                if i >= 6:
                    recent_3 = sum(timeline[j]['net'] for j in range(i-2, i+1))
                    prev_3 = sum(timeline[j]['net'] for j in range(i-5, i-2))
                    if prev_3 > 0 and recent_3 > prev_3 * accel_threshold and recent_3 > accel_min_amount:
                        if can_emit('accel_in', False):
                            emit('🟢 资金加速', False,
                                 f"3分钟净买+{recent_3:.0f}万({recent_3/prev_3:.0f}倍加速)",
                                 '✅ 强势')

                # 信号5: 持续流出
                if i >= sustained_minutes:
                    window_net = sum(timeline[j]['net'] for j in range(i-sustained_minutes+1, i+1))
                    if window_net < -dynamic_sustained:
                        if can_emit('sustained_out', True):
                            emit('🔴 持续流出', True,
                                 f"最近{sustained_minutes}分钟净卖{window_net:.0f}万",
                                 '❌ 不宜入场')

                prev_cum_direction = curr_dir

    all_signals.sort(key=lambda x: x['time'])
    return all_signals


def evaluate(signals, params_name):
    """评估信号质量"""
    total = len(signals)
    reds = sum(1 for s in signals if s['is_red'])
    greens = sum(1 for s in signals if s['is_green'])

    # 关键时刻捕获率
    captured = 0
    missed = []
    for km in KEY_MOMENTS:
        hit = False
        for s in signals:
            if s['stock'] != km['stock']:
                continue
            is_right_color = (km['type'] == 'red' and s['is_red']) or (km['type'] == 'green' and s['is_green'])
            if not is_right_color:
                continue
            if 'before' in km and s['time'] > km['before']:
                continue
            if 'after' in km and s['time'] < km['after']:
                continue
            hit = True
            break
        if hit:
            captured += 1
        else:
            missed.append(km['desc'])

    # 误报计数
    false_pos_count = 0
    false_pos_penalty = 0
    for fp in FALSE_POSITIVES:
        for s in signals:
            if s['stock'] != fp['stock']:
                continue
            is_match_color = (fp['type'] == 'red' and s['is_red']) or (fp['type'] == 'green' and s['is_green'])
            if not is_match_color:
                continue
            if 'before' in fp and s['time'] > fp['before']:
                continue
            if 'after' in fp and s['time'] < fp['after']:
                continue
            false_pos_count += 1
            false_pos_penalty += fp['penalty']
            break

    # 综合得分
    # 目标：信号少 + 关键时刻全捕获 + 误报少
    score = captured * 20 - false_pos_penalty * 5
    if total <= 15:
        score += 10
    elif total <= 25:
        score += 5
    elif total > 50:
        score -= 10
    if total > 0:
        score -= max(0, total - 15) * 0.5  # 超过15条每条扣0.5

    return {
        'name': params_name,
        'total': total,
        'reds': reds,
        'greens': greens,
        'captured': captured,
        'capture_rate': f"{captured}/{len(KEY_MOMENTS)}",
        'missed': missed,
        'false_pos': false_pos_count,
        'false_penalty': false_pos_penalty,
        'score': round(score, 1),
    }


# ==================== MAIN ====================
db = sqlite3.connect(DB_PATH)
all_data = {}
for code in FOCUS_STOCKS:
    tl, avg = load_minute_data(db, code)
    if tl:
        all_data[code] = (tl, avg)
db.close()

print(f"加载 {len(all_data)} 只股票数据\n")

# 参数组合
PARAM_SETS = {
    'A_原始(太灵敏)': {
        'accel_threshold': 2.0, 'accel_min_amount': 1000,
        'mega_multiplier': 8, 'mega_min_amount': 2000,
        'sustained_ratio': 0.15, 'sustained_minutes': 15,
        'reversal_min': 500, 'cooldown_min': 10, 'conflict_window': 0,
    },
    'B_中等降噪': {
        'accel_threshold': 5.0, 'accel_min_amount': 2000,
        'mega_multiplier': 12, 'mega_min_amount': 3000,
        'sustained_ratio': 0.25, 'sustained_minutes': 20,
        'reversal_min': 2000, 'cooldown_min': 20, 'conflict_window': 15,
    },
    'C_强降噪': {
        'accel_threshold': 8.0, 'accel_min_amount': 3000,
        'mega_multiplier': 15, 'mega_min_amount': 5000,
        'sustained_ratio': 0.35, 'sustained_minutes': 20,
        'reversal_min': 5000, 'cooldown_min': 30, 'conflict_window': 20,
    },
    'D_极简模式': {
        'accel_threshold': 15.0, 'accel_min_amount': 5000,
        'mega_multiplier': 20, 'mega_min_amount': 8000,
        'sustained_ratio': 0.5, 'sustained_minutes': 25,
        'reversal_min': 10000, 'cooldown_min': 45, 'conflict_window': 30,
    },
    'E_平衡方案': {
        'accel_threshold': 6.0, 'accel_min_amount': 2500,
        'mega_multiplier': 10, 'mega_min_amount': 3000,
        'sustained_ratio': 0.3, 'sustained_minutes': 20,
        'reversal_min': 3000, 'cooldown_min': 25, 'conflict_window': 20,
    },
    'F_微调平衡': {
        'accel_threshold': 5.0, 'accel_min_amount': 2000,
        'mega_multiplier': 10, 'mega_min_amount': 2500,
        'sustained_ratio': 0.25, 'sustained_minutes': 20,
        'reversal_min': 2000, 'cooldown_min': 25, 'conflict_window': 20,
    },
}

results = []
best_signals = None
best_score = -999

for name, params in PARAM_SETS.items():
    signals = run_backtest(all_data, params)
    result = evaluate(signals, name)
    results.append(result)
    if result['score'] > best_score:
        best_score = result['score']
        best_signals = signals
        best_name = name

# 输出对比表
print(f"{'='*90}")
print(f"  参数组合对比")
print(f"{'='*90}")
print(f"{'方案':<18} {'信号数':>6} {'🔴红':>5} {'🟢绿':>5} {'捕获':>6} {'误报':>4} {'得分':>6}  {'遗漏'}")
print(f"{'-'*90}")
for r in results:
    missed_str = ', '.join(r['missed']) if r['missed'] else '无'
    marker = ' ⭐' if r['score'] == best_score else ''
    print(f"{r['name']:<18} {r['total']:>6} {r['reds']:>5} {r['greens']:>5} {r['capture_rate']:>6} {r['false_pos']:>4} {r['score']:>6.1f}  {missed_str}{marker}")

# 输出最优方案的信号详情
print(f"\n{'='*90}")
print(f"  最优方案 [{best_name}] 信号详情 (得分{best_score})")
print(f"{'='*90}")

for sig in best_signals:
    stock_short = sig['stock'].split('.')[1]
    print(f"  [{sig['time']}] {sig['type']:<12} {stock_short:<6} @ {sig['price']:>8} | {sig['detail']}")

# 输出最优参数
print(f"\n{'='*90}")
print(f"  最优参数值")
print(f"{'='*90}")
best_params = PARAM_SETS[best_name]
for k, v in best_params.items():
    print(f"  {k}: {v}")
