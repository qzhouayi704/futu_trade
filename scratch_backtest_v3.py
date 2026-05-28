#!/usr/bin/env python3
"""
IntradaySniper 全量回测 — 231只股票按市值分组验证参数
"""
import sqlite3
from datetime import date
from collections import defaultdict

DB_PATH = "/opt/futu_trade_sys/simple_trade/data/trade.db"
TODAY = date.today().isoformat()

def load_all_stocks(db):
    """加载所有有今日逐笔数据的股票"""
    rows = db.execute("""
        SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date = ?
    """, (TODAY,)).fetchall()
    return [r[0] for r in rows]

def load_minute_data(db, stock_code):
    rows = db.execute("""
        SELECT
            substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
            direction, SUM(turnover) as total_turnover, AVG(price) as avg_price
        FROM ticker_data WHERE stock_code = ? AND trade_date = ?
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


def run_backtest_single(timeline, avg_turnover, day_total, params):
    """对单只股票运行回测"""
    if len(timeline) < 10 or avg_turnover <= 0:
        return []

    accel_threshold = params['accel_threshold']
    accel_min_amount = params['accel_min_amount']
    mega_multiplier = params['mega_multiplier']
    mega_min_amount = params['mega_min_amount']
    sustained_ratio = params['sustained_ratio']
    sustained_minutes = params['sustained_minutes']
    reversal_min = params['reversal_min']
    cooldown_min = params['cooldown_min']
    conflict_window = params['conflict_window']

    dynamic_mega_min = max(mega_min_amount, day_total * 0.005)
    dynamic_sustained = max(sustained_ratio * avg_turnover * sustained_minutes, 3000)

    signals = []
    cooldown = {}
    prev_cum_direction = 'neutral'
    recent_signals = []

    for i, point in enumerate(timeline):
        is_scan = (i % 3 == 0 and i > 0)

        def can_emit(sig_type, is_red):
            key = sig_type
            if key in cooldown and i - cooldown[key] < cooldown_min:
                return False
            cutoff_idx = max(0, i - conflict_window)
            for rs in recent_signals:
                if rs['idx'] >= cutoff_idx:
                    if (is_red and not rs['is_red']) or (not is_red and rs['is_red']):
                        return False
            return True

        def emit(sig_type, is_red):
            cooldown[sig_type] = i
            sig = {'time': point['time'], 'is_red': is_red, 'idx': i, 'type': sig_type}
            signals.append(sig)
            recent_signals.append(sig)

        # 巨量砸盘
        if point['net'] < -max(dynamic_mega_min, avg_turnover * mega_multiplier):
            if can_emit('mega_sell', True):
                emit('mega_sell', True)

        # 巨量抢筹
        if point['net'] > max(dynamic_mega_min, avg_turnover * mega_multiplier):
            if can_emit('mega_buy', False):
                emit('mega_buy', False)

        if is_scan:
            curr_dir = 'positive' if point['cum_net'] > 0 else 'negative' if point['cum_net'] < 0 else 'neutral'

            # 资金反转
            if prev_cum_direction == 'negative' and curr_dir == 'positive' and point['cum_net'] > reversal_min:
                if can_emit('reversal_bull', False):
                    emit('reversal_bull', False)
            if prev_cum_direction == 'positive' and curr_dir == 'negative' and point['cum_net'] < -reversal_min:
                if can_emit('reversal_bear', True):
                    emit('reversal_bear', True)

            # 加速流入
            if i >= 6:
                recent_3 = sum(timeline[j]['net'] for j in range(i-2, i+1))
                prev_3 = sum(timeline[j]['net'] for j in range(i-5, i-2))
                if prev_3 > 0 and recent_3 > prev_3 * accel_threshold and recent_3 > accel_min_amount:
                    if can_emit('accel_in', False):
                        emit('accel_in', False)

            # 持续流出
            if i >= sustained_minutes:
                window_net = sum(timeline[j]['net'] for j in range(i-sustained_minutes+1, i+1))
                if window_net < -dynamic_sustained:
                    if can_emit('sustained_out', True):
                        emit('sustained_out', True)

            prev_cum_direction = curr_dir

    return signals


# ==================== MAIN ====================
db = sqlite3.connect(DB_PATH)
all_codes = load_all_stocks(db)
print(f"找到 {len(all_codes)} 只有今日逐笔数据的股票")

# 加载并按日成交额分组
groups = {'大盘(>5亿)': [], '中盘(1-5亿)': [], '小盘(1000万-1亿)': [], '微盘(<1000万)': []}

stock_data = {}
for code in all_codes:
    tl, avg, day_total = load_minute_data(db, code)
    if len(tl) < 10:
        continue
    stock_data[code] = (tl, avg, day_total)
    if day_total > 50000:       # >5亿
        groups['大盘(>5亿)'].append(code)
    elif day_total > 10000:     # 1-5亿
        groups['中盘(1-5亿)'].append(code)
    elif day_total > 1000:      # 1000万-1亿
        groups['小盘(1000万-1亿)'].append(code)
    else:
        groups['微盘(<1000万)'].append(code)

db.close()

print(f"\n按日成交额分组:")
for g, codes in groups.items():
    print(f"  {g}: {len(codes)} 只")

# 最优参数C
PARAMS_C = {
    'accel_threshold': 8.0, 'accel_min_amount': 3000,
    'mega_multiplier': 15, 'mega_min_amount': 5000,
    'sustained_ratio': 0.35, 'sustained_minutes': 20,
    'reversal_min': 5000, 'cooldown_min': 30, 'conflict_window': 20,
}

# 自适应参数：按市值动态调整阈值
PARAMS_ADAPTIVE = {
    'accel_threshold': 8.0,
    'accel_min_amount': 'dynamic',  # 由下面逻辑动态设置
    'mega_multiplier': 15,
    'mega_min_amount': 'dynamic',
    'sustained_ratio': 0.35,
    'sustained_minutes': 20,
    'reversal_min': 'dynamic',
    'cooldown_min': 30,
    'conflict_window': 20,
}

print(f"\n{'='*100}")
print(f"  参数C(固定阈值) vs 自适应阈值 — 分组对比")
print(f"{'='*100}")
print(f"{'分组':<20} {'股票数':>6} | {'C固定-信号':>8} {'C每股':>6} {'C有信号':>6} | {'自适应-信号':>8} {'自每股':>6} {'自有信号':>6}")
print(f"{'-'*100}")

for group_name, codes in groups.items():
    if not codes:
        continue

    # 方案C固定阈值
    total_signals_c = 0
    stocks_with_signals_c = 0
    # 自适应阈值
    total_signals_a = 0
    stocks_with_signals_a = 0

    for code in codes:
        tl, avg, day_total = stock_data[code]

        # C固定
        sigs_c = run_backtest_single(tl, avg, day_total, PARAMS_C)
        total_signals_c += len(sigs_c)
        if sigs_c:
            stocks_with_signals_c += 1

        # 自适应：阈值按日成交额动态调整
        if day_total > 50000:  # 大盘股
            adaptive = {**PARAMS_C, 'accel_min_amount': 3000, 'mega_min_amount': 5000, 'reversal_min': 5000}
        elif day_total > 10000:  # 中盘
            adaptive = {**PARAMS_C, 'accel_min_amount': 1500, 'mega_min_amount': 2000, 'reversal_min': 2000}
        elif day_total > 1000:  # 小盘
            adaptive = {**PARAMS_C, 'accel_min_amount': 500, 'mega_min_amount': 800, 'reversal_min': 500}
        else:  # 微盘
            adaptive = {**PARAMS_C, 'accel_min_amount': 100, 'mega_min_amount': 200, 'reversal_min': 100}

        sigs_a = run_backtest_single(tl, avg, day_total, adaptive)
        total_signals_a += len(sigs_a)
        if sigs_a:
            stocks_with_signals_a += 1

    avg_c = total_signals_c / len(codes) if codes else 0
    avg_a = total_signals_a / len(codes) if codes else 0
    print(f"{group_name:<20} {len(codes):>6} | {total_signals_c:>8} {avg_c:>6.1f} {stocks_with_signals_c:>6} | {total_signals_a:>8} {avg_a:>6.1f} {stocks_with_signals_a:>6}")

# 详细看小盘股和微盘股的信号
print(f"\n{'='*100}")
print(f"  小盘股信号样例（自适应阈值）")
print(f"{'='*100}")

sample_count = 0
for code in groups.get('小盘(1000万-1亿)', [])[:50]:
    tl, avg, day_total = stock_data[code]
    adaptive = {**PARAMS_C, 'accel_min_amount': 500, 'mega_min_amount': 800, 'reversal_min': 500}
    sigs = run_backtest_single(tl, avg, day_total, adaptive)
    if sigs and sample_count < 8:
        # 计算该股票的日涨跌幅
        first_price = next((p['price'] for p in tl if p['price'] > 0), 0)
        last_price = next((p['price'] for p in reversed(tl) if p['price'] > 0), 0)
        chg = (last_price - first_price) / first_price * 100 if first_price > 0 else 0
        reds = sum(1 for s in sigs if s['is_red'])
        greens = len(sigs) - reds
        print(f"\n  {code} | 日成交{day_total:.0f}万 | 涨跌{chg:+.1f}% | 信号{len(sigs)}条(🔴{reds}/🟢{greens})")
        for s in sigs:
            color = '🔴' if s['is_red'] else '🟢'
            print(f"    [{s['time']}] {color} {s['type']}")
        sample_count += 1

# 总结
print(f"\n{'='*100}")
print(f"  最终建议：自适应阈值参数")
print(f"{'='*100}")
print("""
  大盘股(日成交>5亿):   accel_min=3000万, mega_min=5000万, reversal_min=5000万
  中盘股(1-5亿):        accel_min=1500万, mega_min=2000万, reversal_min=2000万
  小盘股(1000万-1亿):   accel_min=500万,  mega_min=800万,  reversal_min=500万
  微盘股(<1000万):      accel_min=100万,  mega_min=200万,  reversal_min=100万

  通用参数(所有股票):
    accel_threshold: 8.0倍      (3分钟加速倍数)
    mega_multiplier: 15倍       (单分钟异常净流量对日均的倍数)
    sustained_ratio: 0.35       (持续流出强度)
    sustained_minutes: 20       (持续流出窗口)
    cooldown_min: 30分钟        (同类信号冷却)
    conflict_window: 20分钟     (红绿互斥窗口)
""")
