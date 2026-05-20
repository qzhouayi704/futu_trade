#!/usr/bin/env python3
"""深挖资金流预测力：单日 vs 多日趋势 vs 强度分层"""

import sqlite3, sys
sys.path.insert(0, '.')

db_path = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Get active stocks only
cur = conn.execute("SELECT code FROM stocks WHERE is_low_activity = 0 OR heat_score > 30")
pool = set(r['code'] for r in cur.fetchall())

cur = conn.execute("""
    SELECT DISTINCT DATE(time_key) as td FROM kline_data
    WHERE DATE(time_key) >= DATE('now', '-30 days') AND DATE(time_key) <= DATE('now', '-6 days')
    ORDER BY td
""")
test_dates = [r['td'] for r in cur.fetchall()]

cur = conn.execute("SELECT stock_code FROM kline_data GROUP BY stock_code HAVING COUNT(*)>=30")
stocks = [r['stock_code'] for r in cur.fetchall() if r['stock_code'] in pool]

samples = []
for td in test_dates:
    for sc in stocks:
        # Get outcome
        klines = conn.execute(
            "SELECT close_price FROM kline_data WHERE stock_code=? AND DATE(time_key)<=? ORDER BY time_key DESC LIMIT 1",
            (sc, td)).fetchone()
        if not klines or not klines['close_price'] or klines['close_price'] <= 0: continue
        buy = klines['close_price']

        future = conn.execute(
            "SELECT high_price FROM kline_data WHERE stock_code=? AND DATE(time_key)>? ORDER BY time_key ASC LIMIT 3",
            (sc, td)).fetchall()
        if not future: continue
        max_rise = max((k['high_price'] - buy) / buy * 100 for k in future if k['high_price'])
        win = 1 if max_rise >= 3.0 else 0

        # Get multiple days of flow data
        flows = conn.execute("""
            SELECT date, net_inflow, net_inflow_ratio FROM capital_flow_daily
            WHERE stock_code = ? AND date <= ? ORDER BY date DESC LIMIT 5
        """, (sc, td)).fetchall()

        if not flows: continue

        # Feature 1: Single day flow ratio (current approach)
        single_ratio = flows[0]['net_inflow_ratio']

        # Feature 2: 3-day consecutive inflow count
        consec_in = 0
        for f in flows[:3]:
            if f['net_inflow_ratio'] and f['net_inflow_ratio'] > 0:
                consec_in += 1
            else:
                break

        # Feature 3: 3-day average flow ratio (trend)
        if len(flows) >= 3:
            avg_3d = sum(f['net_inflow_ratio'] for f in flows[:3] if f['net_inflow_ratio']) / 3
        else:
            avg_3d = single_ratio

        # Feature 4: Flow magnitude (absolute net inflow)
        magnitude = abs(flows[0]['net_inflow']) if flows[0]['net_inflow'] else 0

        # Feature 5: Flow momentum (today vs yesterday direction change)
        if len(flows) >= 2 and flows[0]['net_inflow_ratio'] and flows[1]['net_inflow_ratio']:
            flow_momentum = flows[0]['net_inflow_ratio'] - flows[1]['net_inflow_ratio']
        else:
            flow_momentum = 0

        samples.append({
            'win': win, 'max_rise': max_rise,
            'single_ratio': single_ratio,
            'consec_in': consec_in,
            'avg_3d': avg_3d,
            'magnitude': magnitude,
            'flow_momentum': flow_momentum,
        })

print(f"Samples with flow data: {len(samples)}", flush=True)
overall_wr = sum(s['win'] for s in samples) / len(samples)
print(f"Overall win rate: {overall_wr*100:.1f}%\n", flush=True)

# Analysis 1: Single-day ratio (current approach)
print("=== 1. 单日资金流比率（当前方式） ===", flush=True)
for label, lo, hi in [("强流出<-0.3", -2, -0.3), ("弱流出-0.3~0", -0.3, 0), ("弱流入0~0.3", 0, 0.3), ("强流入>0.3", 0.3, 2)]:
    g = [s for s in samples if lo <= s['single_ratio'] < hi]
    if g:
        wr = sum(s['win'] for s in g) / len(g)
        print(f"  {label:>12}: n={len(g):>4} | WR={wr*100:>5.1f}%", flush=True)

# Analysis 2: Consecutive inflow days
print("\n=== 2. 连续流入天数（多日确认） ===", flush=True)
for days in [0, 1, 2, 3]:
    g = [s for s in samples if s['consec_in'] == days]
    if g:
        wr = sum(s['win'] for s in g) / len(g)
        print(f"  连续{days}天流入: n={len(g):>4} | WR={wr*100:>5.1f}%", flush=True)

# Analysis 3: 3-day average
print("\n=== 3. 3日均值资金流 ===", flush=True)
for label, lo, hi in [("均值<-0.2", -2, -0.2), ("-0.2~0", -0.2, 0), ("0~0.2", 0, 0.2), (">0.2", 0.2, 2)]:
    g = [s for s in samples if lo <= s['avg_3d'] < hi]
    if g:
        wr = sum(s['win'] for s in g) / len(g)
        print(f"  {label:>12}: n={len(g):>4} | WR={wr*100:>5.1f}%", flush=True)

# Analysis 4: Flow momentum (direction change)
print("\n=== 4. 资金流动量（今 vs 昨 方向变化） ===", flush=True)
for label, lo, hi in [("大幅转出<-0.5", -2, -0.5), ("小幅转出", -0.5, 0), ("小幅转入", 0, 0.5), ("大幅转入>0.5", 0.5, 2)]:
    g = [s for s in samples if lo <= s['flow_momentum'] < hi]
    if g:
        wr = sum(s['win'] for s in g) / len(g)
        print(f"  {label:>14}: n={len(g):>4} | WR={wr*100:>5.1f}%", flush=True)

# Analysis 5: Combined signal - 连续流入 + 当日强流入
print("\n=== 5. 组合信号（连续流入+当日强流入） ===", flush=True)
combo_strong = [s for s in samples if s['consec_in'] >= 2 and s['single_ratio'] > 0.3]
combo_weak = [s for s in samples if s['consec_in'] == 0 and s['single_ratio'] < -0.3]
combo_mid = [s for s in samples if s not in combo_strong and s not in combo_weak]
if combo_strong:
    wr = sum(s['win'] for s in combo_strong) / len(combo_strong)
    print(f"  强组合(连续2天+当日>0.3): n={len(combo_strong):>4} | WR={wr*100:>5.1f}%", flush=True)
if combo_mid:
    wr = sum(s['win'] for s in combo_mid) / len(combo_mid)
    print(f"  中性:                      n={len(combo_mid):>4} | WR={wr*100:>5.1f}%", flush=True)
if combo_weak:
    wr = sum(s['win'] for s in combo_weak) / len(combo_weak)
    print(f"  弱组合(无连续+当日<-0.3):  n={len(combo_weak):>4} | WR={wr*100:>5.1f}%", flush=True)

conn.close()
