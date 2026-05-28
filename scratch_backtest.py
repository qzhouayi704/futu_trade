#!/usr/bin/env python3
"""
IntradaySniper 回测脚本 — 用2026-05-26真实逐笔数据逐分钟模拟

模拟规则：
1. 每3分钟扫描一次活跃股
2. 检测：单分钟异常净卖出(>日均10倍)、资金反转、出货陷阱
3. 输出：如果当天有这个系统，会在什么时间推送什么信号
"""

import sqlite3
import json
from datetime import date, datetime
from collections import defaultdict

DB_PATH = "/opt/futu_trade_sys/simple_trade/data/trade.db"
TODAY = date.today().isoformat()

# 我们关注的股票（今天交易过的 + TOP活跃股）
FOCUS_STOCKS = [
    'HK.00981',  # 中芯国际 (亏1475)
    'HK.00100',  # MINIMAX (亏920)
    'HK.06651',  # 五一视界 (亏320但涨22%)
    'HK.00992',  # 联想集团 (赚4280)
    'HK.01879',  # 曦智科技 (浮亏442)
    'HK.02631',  # 天岳先进
    'HK.00068',  # 群核科技
    'HK.03033',  # 南方科技
]

def load_minute_data(db, stock_code):
    """加载某只股票的分钟级聚合数据"""
    rows = db.execute("""
        SELECT
            substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
            direction,
            SUM(turnover) as total_turnover,
            SUM(volume) as total_volume,
            AVG(price) as avg_price,
            COUNT(*) as tick_count
        FROM ticker_data
        WHERE stock_code = ? AND trade_date = ?
        GROUP BY minute, direction
        ORDER BY minute
    """, (stock_code, TODAY)).fetchall()

    # 按分钟聚合
    minutes = {}
    for row in rows:
        minute, direction, turnover, volume, avg_price, tick_count = row
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

    # 构建有序时间线
    timeline = []
    cum_buy = 0.0
    cum_sell = 0.0
    for minute in sorted(minutes.keys()):
        e = minutes[minute]
        buy_t = e['buy']
        sell_t = e['sell']
        cum_buy += buy_t
        cum_sell += sell_t
        net = buy_t - sell_t
        cum_net = cum_buy - cum_sell
        price = round(e['price'] / e['price_n'], 3) if e['price_n'] > 0 else 0
        timeline.append({
            'time': minute,
            'buy': round(buy_t / 10000, 1),      # 万
            'sell': round(sell_t / 10000, 1),      # 万
            'net': round(net / 10000, 1),           # 万
            'cum_net': round(cum_net / 10000, 1),   # 万
            'price': price,
        })
    return timeline


def simulate_sniper(stock_code, timeline):
    """模拟IntradaySniper对单只股票的3分钟扫描"""
    if len(timeline) < 5:
        return []

    signals = []
    # 计算日均分钟净流量（用前30分钟的均值作为基准）
    first_30 = [abs(p['net']) for p in timeline[:30] if p['net'] != 0]
    avg_minute_net = sum(first_30) / len(first_30) if first_30 else 100

    # 状态追踪
    prev_cum_net = 0
    prev_cum_direction = 'neutral'  # positive/negative/neutral
    prev_scan_cum_net = 0
    cooldown = {}  # signal_type -> last_trigger_minute_index

    for i, point in enumerate(timeline):
        minute = point['time']

        # 每3分钟扫描一次（或在任何分钟检测异常大单）
        is_scan_minute = (i % 3 == 0 and i > 0)

        # ========== 信号1: 单分钟异常净卖出 ==========
        # 条件：单分钟净卖出 > avg_minute_net * 10 (即日均10倍)
        threshold_sell = max(avg_minute_net * 8, 2000)  # 至少2000万
        if point['net'] < -threshold_sell:
            sig_key = f"mega_sell_{stock_code}"
            if sig_key not in cooldown or i - cooldown[sig_key] >= 10:
                signals.append({
                    'time': minute,
                    'type': '🔴 巨量砸盘',
                    'stock': stock_code,
                    'detail': f"单分钟净卖出 {point['net']:.0f}万 (日均{avg_minute_net:.0f}万的{abs(point['net']/avg_minute_net):.0f}倍)，累计净{point['cum_net']:.0f}万",
                    'action': '❌ 不要买入/立即止损',
                    'price': point['price'],
                })
                cooldown[sig_key] = i

        # ========== 信号2: 单分钟异常净买入 ==========
        threshold_buy = max(avg_minute_net * 8, 2000)
        if point['net'] > threshold_buy:
            sig_key = f"mega_buy_{stock_code}"
            if sig_key not in cooldown or i - cooldown[sig_key] >= 10:
                signals.append({
                    'time': minute,
                    'type': '🟢 巨量抢筹',
                    'stock': stock_code,
                    'detail': f"单分钟净买入 +{point['net']:.0f}万 (日均{avg_minute_net:.0f}万的{point['net']/avg_minute_net:.0f}倍)，累计净{point['cum_net']:.0f}万",
                    'action': '✅ 关注买入机会',
                    'price': point['price'],
                })
                cooldown[sig_key] = i

        # ========== 每3分钟扫描 ==========
        if is_scan_minute:
            # 信号3: 资金流反转
            curr_direction = 'positive' if point['cum_net'] > 0 else 'negative' if point['cum_net'] < 0 else 'neutral'

            # 从负转正（反转买入信号）
            if prev_cum_direction == 'negative' and curr_direction == 'positive' and abs(point['cum_net']) > 500:
                sig_key = f"reversal_bull_{stock_code}"
                if sig_key not in cooldown or i - cooldown[sig_key] >= 30:
                    signals.append({
                        'time': minute,
                        'type': '🟢 资金反转(由负转正)',
                        'stock': stock_code,
                        'detail': f"累计净流入从负转正: {prev_scan_cum_net:.0f}万 → {point['cum_net']:.0f}万",
                        'action': '✅ 关注入场机会',
                        'price': point['price'],
                    })
                    cooldown[sig_key] = i

            # 从正转负（反转卖出信号）
            if prev_cum_direction == 'positive' and curr_direction == 'negative' and abs(point['cum_net']) > 500:
                sig_key = f"reversal_bear_{stock_code}"
                if sig_key not in cooldown or i - cooldown[sig_key] >= 30:
                    signals.append({
                        'time': minute,
                        'type': '🔴 资金反转(由正转负)',
                        'stock': stock_code,
                        'detail': f"累计净流入从正转负: {prev_scan_cum_net:.0f}万 → {point['cum_net']:.0f}万",
                        'action': '❌ 考虑减仓',
                        'price': point['price'],
                    })
                    cooldown[sig_key] = i

            # 信号4: 加速流入（最近3分钟净流入 > 前3分钟 × 2）
            if i >= 6:
                recent_3 = sum(timeline[j]['net'] for j in range(i-2, i+1))
                prev_3 = sum(timeline[j]['net'] for j in range(i-5, i-2))
                if recent_3 > 0 and prev_3 > 0 and recent_3 > prev_3 * 2 and recent_3 > 1000:
                    sig_key = f"accel_{stock_code}"
                    if sig_key not in cooldown or i - cooldown[sig_key] >= 15:
                        signals.append({
                            'time': minute,
                            'type': '🟢 资金加速流入',
                            'stock': stock_code,
                            'detail': f"最近3分钟净买 +{recent_3:.0f}万 (前3分钟 +{prev_3:.0f}万，加速{recent_3/max(prev_3,1):.1f}倍)",
                            'action': '✅ 强势信号',
                            'price': point['price'],
                        })
                        cooldown[sig_key] = i

            # 信号5: 持续流出预警（连续15分钟累计净流出）
            if i >= 15:
                last_15_net = sum(timeline[j]['net'] for j in range(i-14, i+1))
                if last_15_net < -3000:
                    sig_key = f"sustained_out_{stock_code}"
                    if sig_key not in cooldown or i - cooldown[sig_key] >= 30:
                        signals.append({
                            'time': minute,
                            'type': '🔴 持续流出',
                            'stock': stock_code,
                            'detail': f"最近15分钟累计净卖出 {last_15_net:.0f}万",
                            'action': '❌ 不宜入场',
                            'price': point['price'],
                        })
                        cooldown[sig_key] = i

            prev_cum_direction = curr_direction
            prev_scan_cum_net = point['cum_net']

        prev_cum_net = point['cum_net']

    return signals


def generate_top3(all_timelines, scan_index):
    """在某个扫描时刻，生成TOP3推荐"""
    scores = []
    for code, timeline in all_timelines.items():
        if scan_index >= len(timeline):
            continue
        point = timeline[scan_index]

        # 评分逻辑
        score = 0
        # 累计净流入正向 +分
        if point['cum_net'] > 0:
            score += min(point['cum_net'] / 1000, 30)  # 最多30分
        else:
            score -= min(abs(point['cum_net']) / 1000, 20)

        # 最近动能
        if scan_index >= 5:
            recent_net = sum(timeline[j]['net'] for j in range(max(0, scan_index-4), scan_index+1))
            if recent_net > 0:
                score += min(recent_net / 500, 20)
            else:
                score -= min(abs(recent_net) / 500, 15)

        # 买卖比
        total_buy = sum(p['buy'] for p in timeline[:scan_index+1])
        total_sell = sum(abs(p['sell']) for p in timeline[:scan_index+1])
        if total_sell > 0:
            ratio = total_buy / total_sell
            if ratio > 1.2:
                score += 15
            elif ratio > 1.0:
                score += 5
            elif ratio < 0.8:
                score -= 10

        scores.append((code, score, point))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:3]


# ==================== MAIN ====================
print("=" * 80)
print("  IntradaySniper 回测 — 2026-05-26 实盘逐笔数据")
print("=" * 80)

db = sqlite3.connect(DB_PATH)

# 加载所有股票数据
all_timelines = {}
for code in FOCUS_STOCKS:
    tl = load_minute_data(db, code)
    if tl:
        all_timelines[code] = tl
        print(f"  {code}: {len(tl)} 分钟数据点, 价格 {tl[0]['price']:.3f} → {tl[-1]['price']:.3f}")

# 获取股票名称
name_map = {}
try:
    rows = db.execute("SELECT code, name FROM stocks WHERE code IN ({})".format(
        ','.join(['?' for _ in FOCUS_STOCKS])
    ), FOCUS_STOCKS).fetchall()
    name_map = {r[0]: r[1] for r in rows}
except:
    pass

print(f"\n加载完成: {len(all_timelines)} 只股票")

# 逐股票模拟
all_signals = []
for code, timeline in all_timelines.items():
    signals = simulate_sniper(code, timeline)
    for s in signals:
        s['stock_name'] = name_map.get(code, '')
    all_signals.extend(signals)

# 按时间排序
all_signals.sort(key=lambda x: x['time'])

# 输出信号时间线
print(f"\n{'=' * 80}")
print(f"  信号时间线 — 如果今天有IntradaySniper，它会推送这些信号：")
print(f"{'=' * 80}")

for sig in all_signals:
    name = sig.get('stock_name', '')
    print(f"\n  [{sig['time']}] {sig['type']}")
    print(f"  股票: {sig['stock']} {name} @ {sig['price']}")
    print(f"  详情: {sig['detail']}")
    print(f"  建议: {sig['action']}")

# TOP3 快照：在几个关键时间点输出
print(f"\n{'=' * 80}")
print(f"  TOP3 推荐快照（关键时间点）")
print(f"{'=' * 80}")

# 找到对应的分钟索引
# 用联想的时间线作为参考（数据点最多）
ref_code = 'HK.00992'
ref_tl = all_timelines.get(ref_code, [])

snapshot_times = ['09:45', '10:00', '10:30', '11:00', '13:00', '14:00', '14:30', '15:00', '15:30']
for snap_time in snapshot_times:
    # 找到最接近的索引
    best_idx = None
    for i, p in enumerate(ref_tl):
        if p['time'] >= snap_time:
            best_idx = i
            break
    if best_idx is None:
        continue

    top3 = generate_top3(all_timelines, min(best_idx, min(len(tl)-1 for tl in all_timelines.values())))
    print(f"\n  📊 {snap_time} TOP3:")
    for rank, (code, score, point) in enumerate(top3, 1):
        name = name_map.get(code, '')
        emoji = ['🥇', '🥈', '🥉'][rank-1]
        print(f"    {emoji} {code} {name} | 评分{score:.0f} | 价格{point['price']} | 累计净{point['cum_net']:.0f}万")

# 最终统计
print(f"\n{'=' * 80}")
print(f"  回测结论")
print(f"{'=' * 80}")
print(f"  总信号数: {len(all_signals)}")
print(f"  🔴 风险信号: {sum(1 for s in all_signals if '🔴' in s['type'])}")
print(f"  🟢 机会信号: {sum(1 for s in all_signals if '🟢' in s['type'])}")

# 验证关键时刻
key_moments = {
    '中芯09:38砸盘': any(s['stock'] == 'HK.00981' and '砸盘' in s['type'] and s['time'] <= '09:45' for s in all_signals),
    '联想开盘资金涌入': any(s['stock'] == 'HK.00992' and '🟢' in s['type'] and s['time'] <= '10:00' for s in all_signals),
    '五一视界午后反转': any(s['stock'] == 'HK.06651' and '反转' in s['type'] and '13:' in s['time'] or '14:' in s['time'] for s in all_signals),
    'MINIMAX开盘流出': any(s['stock'] == 'HK.00100' and '🔴' in s['type'] and s['time'] <= '10:00' for s in all_signals),
}
print(f"\n  关键时刻验证:")
for desc, hit in key_moments.items():
    status = "✅ 能捕获" if hit else "❌ 未捕获"
    print(f"    {status} — {desc}")

db.close()
