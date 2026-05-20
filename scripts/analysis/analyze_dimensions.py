#!/usr/bin/env python3
"""分析各个指标维度的独立预测力，找出哪些维度真正有用"""

import sqlite3, sys, statistics
sys.path.insert(0, '.')

db_path = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Collect all stock-date samples with indicators and outcomes
cur = conn.execute("""
    SELECT DISTINCT DATE(time_key) as td FROM kline_data
    WHERE DATE(time_key) >= DATE('now', '-30 days') AND DATE(time_key) <= DATE('now', '-6 days')
    ORDER BY td
""")
test_dates = [r['td'] for r in cur.fetchall()]

cur = conn.execute("SELECT stock_code FROM kline_data GROUP BY stock_code HAVING COUNT(*)>=30")
stock_codes = [r['stock_code'] for r in cur.fetchall()]

samples = []
for td in test_dates:
    for sc in stock_codes:
        klines = conn.execute(
            "SELECT * FROM kline_data WHERE stock_code=? AND DATE(time_key)<=? ORDER BY time_key DESC LIMIT 30",
            (sc, td)).fetchall()
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
            avg5 = sum(volumes[-6:-1]) / 5
            if avg5 > 0: ind['vol_ratio'] = volumes[-1] / avg5
        flow = conn.execute(
            "SELECT net_inflow_ratio FROM capital_flow_daily WHERE stock_code=? AND date<=? ORDER BY date DESC LIMIT 1",
            (sc, td)).fetchone()
        ind['flow_ratio'] = flow['net_inflow_ratio'] if flow else None

        # Future 3-day outcome
        future = conn.execute(
            "SELECT close_price, high_price FROM kline_data WHERE stock_code=? AND DATE(time_key)>? ORDER BY time_key ASC LIMIT 3",
            (sc, td)).fetchall()
        if not future or closes[-1] <= 0: continue
        buy = closes[-1]
        max_rise = max((k['high_price'] - buy) / buy * 100 for k in future if k['high_price']) if future else 0
        outcome = 1 if max_rise >= 3.0 else 0

        ind['outcome'] = outcome
        ind['max_rise'] = max_rise
        samples.append(ind)

print(f"Total samples: {len(samples)}", flush=True)
win_rate = sum(s['outcome'] for s in samples) / len(samples)
print(f"Overall win rate: {win_rate*100:.1f}%\n", flush=True)

# For each indicator, split into quartiles and show win rate
for key in ['change_5d', 'kline_pos_20d', 'vol_ratio', 'flow_ratio', 'day_amplitude', 'prev_day_change']:
    vals = [(s[key], s['outcome'], s['max_rise']) for s in samples if s.get(key) is not None]
    if len(vals) < 100: continue
    vals.sort(key=lambda x: x[0])
    n = len(vals)
    q_size = n // 5
    print(f"=== {key} (n={n}) ===")
    for qi in range(5):
        start = qi * q_size
        end = (qi + 1) * q_size if qi < 4 else n
        group = vals[start:end]
        wr = sum(g[1] for g in group) / len(group)
        avg_rise = sum(g[2] for g in group) / len(group)
        lo_val, hi_val = group[0][0], group[-1][0]
        label = f"Q{qi+1}[{lo_val:>7.2f}~{hi_val:>7.2f}]"
        bar = '#' * int(wr * 40)
        print(f"  {label}: WR={wr*100:>5.1f}% rise={avg_rise:>5.1f}% {bar}")
    print()

conn.close()
