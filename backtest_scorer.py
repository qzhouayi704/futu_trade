#!/usr/bin/env python3
"""回测评分系统 v2：去重 + 扩大样本 + 分析评分反转原因"""

import sqlite3
import sys
sys.path.insert(0, '.')

from simple_trade.services.strategy.stock_scorer import StockScorer

db_path = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Get BUY signals with performance - DEDUPLICATED (one per stock per day)
cur = conn.execute("""
    SELECT ts.id, s.code, s.name, ts.signal_price, ts.created_at,
           sp.day1_max_rise, sp.day1_max_drop, 
           sp.day3_max_rise, sp.day3_max_drop,
           sp.day5_max_rise, sp.day5_max_drop
    FROM trade_signals ts
    JOIN stocks s ON ts.stock_id = s.id
    JOIN signal_performance sp ON sp.signal_id = ts.id
    WHERE ts.signal_type = 'BUY'
      AND sp.tracking_status = 'completed'
      AND sp.day3_max_rise IS NOT NULL
    GROUP BY s.code, DATE(ts.created_at)
    ORDER BY ts.created_at DESC
    LIMIT 500
""")
signals = cur.fetchall()
print(f"Found {len(signals)} deduplicated BUY signals\n")

if not signals:
    conn.close()
    sys.exit(0)

scorer = StockScorer()
results = []

for sig in signals:
    stock_code = sig['code']
    signal_price = sig['signal_price']
    signal_time = sig['created_at']
    signal_date = signal_time[:10]

    # Get klines up to signal date
    klines = conn.execute("""
        SELECT time_key, open_price, close_price, high_price, low_price, volume
        FROM kline_data
        WHERE stock_code = ? AND DATE(time_key) <= ?
        ORDER BY time_key DESC
        LIMIT 30
    """, (stock_code, signal_date)).fetchall()

    if len(klines) < 6:
        continue

    klines = list(reversed(klines))
    closes = [k['close_price'] for k in klines if k['close_price'] and k['close_price'] > 0]

    if len(closes) < 6:
        continue

    indicators = {}
    indicators['change_5d'] = (closes[-1] - closes[-6]) / closes[-6] * 100
    indicators['prev_day_change'] = (closes[-1] - closes[-2]) / closes[-2] * 100

    recent = klines[-20:] if len(klines) >= 20 else klines
    highs = [k['high_price'] for k in recent if k['high_price']]
    lows = [k['low_price'] for k in recent if k['low_price']]
    if highs and lows:
        max_h = max(highs)
        min_l = min(lows)
        if max_h > min_l:
            indicators['kline_pos_20d'] = (closes[-1] - min_l) / (max_h - min_l)

    buy_day = klines[-1]
    if buy_day['high_price'] and buy_day['low_price'] and closes[-2] > 0:
        indicators['day_amplitude'] = (buy_day['high_price'] - buy_day['low_price']) / closes[-2] * 100

    volumes = [k['volume'] for k in klines if k['volume'] and k['volume'] > 0]
    if len(volumes) >= 6:
        today_vol = volumes[-1]
        avg_5d = sum(volumes[-6:-1]) / 5
        if avg_5d > 0:
            indicators['vol_ratio'] = today_vol / avg_5d

    flow_row = conn.execute("""
        SELECT net_inflow_ratio FROM capital_flow_daily
        WHERE stock_code = ? AND date <= ?
        ORDER BY date DESC LIMIT 1
    """, (stock_code, signal_date)).fetchone()
    indicators['flow_ratio'] = flow_row['net_inflow_ratio'] if flow_row else None

    result = scorer.score_stock(stock_code, sig['name'] or stock_code, indicators)

    day3_max_rise = sig['day3_max_rise'] or 0
    day3_max_drop = sig['day3_max_drop'] or 0
    outcome = 'WIN' if day3_max_rise >= 3.0 else ('LOSS' if day3_max_drop <= -3.0 else 'FLAT')

    results.append({
        'code': stock_code,
        'name': sig['name'] or '',
        'date': signal_date,
        'score': result.total_score,
        'passed': result.passed,
        'veto': result.veto_reason,
        'day3_rise': day3_max_rise,
        'day3_drop': day3_max_drop,
        'outcome': outcome,
        'indicators': indicators,
        'details': [(d.dimension, d.score, d.max_score, d.value) for d in result.details],
    })

# Analysis
print(f"Successfully scored {len(results)} unique trades\n")

# Score distribution
print("--- 分数段胜率分析 ---")
brackets = [(80, 100), (60, 79), (40, 59), (20, 39), (0, 19)]
for lo, hi in brackets:
    br = [r for r in results if lo <= r['score'] <= hi]
    if br:
        bw = sum(1 for r in br if r['outcome'] == 'WIN')
        bl = sum(1 for r in br if r['outcome'] == 'LOSS')
        avg_rise = sum(r['day3_rise'] for r in br) / len(br)
        avg_drop = sum(r['day3_drop'] for r in br) / len(br)
        print(f"  {lo:>3}-{hi}分: {len(br):>3}笔 | 胜率{bw/len(br)*100:>5.1f}% | 败率{bl/len(br)*100:>5.1f}% | 3日均涨{avg_rise:>5.1f}% | 3日均跌{avg_drop:>6.1f}%")

# Show high-score losses to understand why
print("\n--- 高分(>=60)但亏损的案例 ---")
high_losses = [r for r in results if r['score'] >= 60 and r['outcome'] == 'LOSS']
for r in high_losses[:10]:
    print(f"  {r['code']} {r['name'][:8]} | {r['date']} | score={r['score']} | 3日涨{r['day3_rise']:.1f}% 跌{r['day3_drop']:.1f}%")
    for dim, score, max_s, val in r['details']:
        print(f"    {dim}: {score}/{max_s} (val={val})")

# Show low-score wins to understand why
print("\n--- 低分(<40)但盈利的案例(前5) ---")
low_wins = [r for r in results if r['score'] < 40 and r['outcome'] == 'WIN']
for r in low_wins[:5]:
    print(f"  {r['code']} {r['name'][:8]} | {r['date']} | score={r['score']} | 3日涨{r['day3_rise']:.1f}% 跌{r['day3_drop']:.1f}%")
    for dim, score, max_s, val in r['details']:
        print(f"    {dim}: {score}/{max_s} (val={val})")

# Overall stats
wins = sum(1 for r in results if r['outcome'] == 'WIN')
losses = sum(1 for r in results if r['outcome'] == 'LOSS')
print(f"\n{'='*60}")
print(f"总计: {len(results)}笔 | WIN: {wins} ({wins/len(results)*100:.1f}%) | LOSS: {losses} ({losses/len(results)*100:.1f}%)")

conn.close()
