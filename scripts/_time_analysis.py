"""分析开盘前10分钟 vs 之后的交易表现"""
import json

perf = json.load(open('scripts/buy_performance_analysis.json','r',encoding='utf-8'))

# 按买入时间分段
buckets = {
    '09:30-09:40': [], '09:40-09:50': [], '09:50-10:00': [],
    '10:00-10:15': [], '10:15-10:30': [], '10:30-11:00': [],
    '11:00+': [],
}

for t in perf['trade_patterns']:
    bt = t.get('buy_time', '')[11:16]
    if bt < '09:40': buckets['09:30-09:40'].append(t)
    elif bt < '09:50': buckets['09:40-09:50'].append(t)
    elif bt < '10:00': buckets['09:50-10:00'].append(t)
    elif bt < '10:15': buckets['10:00-10:15'].append(t)
    elif bt < '10:30': buckets['10:15-10:30'].append(t)
    elif bt < '11:00': buckets['10:30-11:00'].append(t)
    else: buckets['11:00+'].append(t)

print(f"{'时段':<16} {'笔数':>4} {'胜率':>6} {'平均盈亏%':>9} {'平均潜在%':>9} {'捕获率':>7} {'平均持仓':>8}")
print("-" * 70)
for bk, trades in buckets.items():
    if not trades: continue
    wins = sum(1 for t in trades if t['result'] == 'WIN')
    wr = wins / len(trades) * 100
    avg_pnl = sum(t['actual_pct'] for t in trades) / len(trades)
    avg_pot = sum(t['potential_pct'] for t in trades) / len(trades)
    avg_hold = sum(t['hold_minutes'] for t in trades) / len(trades)
    cap = sum(t['capture_ratio'] for t in trades) / len(trades)
    print(f"{bk:<16} {len(trades):4d} {wr:5.1f}% {avg_pnl:+8.2f}% {avg_pot:+8.2f}% {cap:+6.1f}% {avg_hold:7.1f}m")

# 开盘10分钟内的赚钱案例
print(f"\n=== 09:30-09:40 WIN cases ===")
early = [t for t in buckets['09:30-09:40'] if t['result'] == 'WIN']
for t in early:
    print(f"  {t['code']} {t['date']} buy@{t['buy_price']} sell@{t['sell_price']} {t['actual_pct']:+.2f}% hold={t['hold_minutes']}min")

print(f"\n=== 09:30-09:40 LOSS cases ===")
early_l = [t for t in buckets['09:30-09:40'] if t['result'] == 'LOSS']
for t in early_l[:8]:
    print(f"  {t['code']} {t['date']} buy@{t['buy_price']} sell@{t['sell_price']} {t['actual_pct']:+.2f}% hold={t['hold_minutes']}min")
