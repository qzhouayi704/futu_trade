#!/usr/bin/env python3
"""深入分析低分盈利和高分亏损的指标特征，找优化方向"""

import sqlite3, sys, statistics
sys.path.insert(0, '.')
from simple_trade.services.strategy.stock_scorer import StockScorer

db_path = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

cur = conn.execute("""
    SELECT ts.id, s.code, s.name, ts.signal_price, ts.created_at,
           sp.day3_max_rise, sp.day3_max_drop
    FROM trade_signals ts
    JOIN stocks s ON ts.stock_id = s.id
    JOIN signal_performance sp ON sp.signal_id = ts.id
    WHERE ts.signal_type = 'BUY' AND sp.tracking_status = 'completed' AND sp.day3_max_rise IS NOT NULL
    GROUP BY s.code, DATE(ts.created_at)
    ORDER BY ts.created_at DESC LIMIT 500
""")
signals = cur.fetchall()

scorer = StockScorer()
results = []

for sig in signals:
    stock_code, signal_date = sig['code'], sig['created_at'][:10]
    klines = conn.execute(
        "SELECT * FROM kline_data WHERE stock_code=? AND DATE(time_key)<=? ORDER BY time_key DESC LIMIT 30",
        (stock_code, signal_date)).fetchall()
    if len(klines) < 6: continue
    klines = list(reversed(klines))
    closes = [k['close_price'] for k in klines if k['close_price'] and k['close_price'] > 0]
    if len(closes) < 6: continue

    ind = {}
    ind['change_5d'] = (closes[-1] - closes[-6]) / closes[-6] * 100
    ind['prev_day_change'] = (closes[-1] - closes[-2]) / closes[-2] * 100
    recent = klines[-20:] if len(klines) >= 20 else klines
    highs = [k['high_price'] for k in recent if k['high_price']]
    lows = [k['low_price'] for k in recent if k['low_price']]
    if highs and lows and max(highs) > min(lows):
        ind['kline_pos_20d'] = (closes[-1] - min(lows)) / (max(highs) - min(lows))
    bd = klines[-1]
    if bd['high_price'] and bd['low_price'] and closes[-2] > 0:
        ind['day_amplitude'] = (bd['high_price'] - bd['low_price']) / closes[-2] * 100
    volumes = [k['volume'] for k in klines if k['volume'] and k['volume'] > 0]
    if len(volumes) >= 6:
        avg_5d = sum(volumes[-6:-1]) / 5
        if avg_5d > 0: ind['vol_ratio'] = volumes[-1] / avg_5d
    flow_row = conn.execute(
        "SELECT net_inflow_ratio FROM capital_flow_daily WHERE stock_code=? AND date<=? ORDER BY date DESC LIMIT 1",
        (stock_code, signal_date)).fetchone()
    ind['flow_ratio'] = flow_row['net_inflow_ratio'] if flow_row else None

    result = scorer.score_stock(stock_code, sig['name'] or '', ind)
    day3_rise = sig['day3_max_rise'] or 0
    day3_drop = sig['day3_max_drop'] or 0
    outcome = 'WIN' if day3_rise >= 3.0 else ('LOSS' if day3_drop <= -3.0 else 'FLAT')
    results.append({'score': result.total_score, 'outcome': outcome, 'ind': ind, 'code': stock_code,
                    'day3_rise': day3_rise, 'day3_drop': day3_drop})

# Analyze patterns
def analyze_group(group, label):
    if not group: return
    print(f"\n{'='*50}")
    print(f"{label} ({len(group)} 笔)")
    print(f"{'='*50}")
    for key in ['change_5d', 'kline_pos_20d', 'vol_ratio', 'flow_ratio', 'day_amplitude', 'prev_day_change']:
        vals = [r['ind'].get(key) for r in group if r['ind'].get(key) is not None]
        if vals:
            print(f"  {key:>18}: avg={statistics.mean(vals):>7.2f} | med={statistics.median(vals):>7.2f} | "
                  f"min={min(vals):>7.2f} | max={max(vals):>7.2f}")

# Groups
low_win = [r for r in results if r['score'] < 40 and r['outcome'] == 'WIN']
low_loss = [r for r in results if r['score'] < 40 and r['outcome'] == 'LOSS']
high_win = [r for r in results if r['score'] >= 60 and r['outcome'] == 'WIN']
high_loss = [r for r in results if r['score'] >= 60 and r['outcome'] == 'LOSS']
mid_win = [r for r in results if 40 <= r['score'] < 60 and r['outcome'] == 'WIN']
mid_loss = [r for r in results if 40 <= r['score'] < 60 and r['outcome'] == 'LOSS']

analyze_group(low_win, "低分(<40) 盈利 — 漏捕信号")
analyze_group(low_loss, "低分(<40) 亏损 — 正确过滤")
analyze_group(high_win, "高分(>=60) 盈利 — 正确捕捉")
analyze_group(high_loss, "高分(>=60) 亏损 — 误判")

# Key question: what differentiates low_win from low_loss?
print(f"\n{'='*50}")
print("低分组 WIN vs LOSS 关键差异")
print(f"{'='*50}")
for key in ['change_5d', 'kline_pos_20d', 'vol_ratio', 'flow_ratio', 'prev_day_change']:
    w_vals = [r['ind'].get(key) for r in low_win if r['ind'].get(key) is not None]
    l_vals = [r['ind'].get(key) for r in low_loss if r['ind'].get(key) is not None]
    if w_vals and l_vals:
        w_avg, l_avg = statistics.mean(w_vals), statistics.mean(l_vals)
        diff = w_avg - l_avg
        print(f"  {key:>18}: WIN_avg={w_avg:>7.2f} | LOSS_avg={l_avg:>7.2f} | diff={diff:>+7.2f} {'<-- signal' if abs(diff) > 1 else ''}")

# Also check: do low_win stocks have a "reversal" pattern? (prev_day negative but today positive)
print(f"\n--- 低分WIN的反转特征 ---")
reversal_count = sum(1 for r in low_win if r['ind'].get('prev_day_change', 0) < -2 and r['ind'].get('change_5d', 0) < 0)
print(f"  超跌反弹型 (5日跌 + 前日跌>2%): {reversal_count}/{len(low_win)} ({reversal_count/len(low_win)*100:.0f}%)")

conn.close()
