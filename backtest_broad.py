#!/usr/bin/env python3
"""修正回测：只用高活跃/高热度股票（实际交易池），消除总体偏差"""

import sqlite3, sys
sys.path.insert(0, '.')

db_path = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Step 1: 了解我们的实际交易池特征
print("=== 股票池特征 ===", flush=True)
cur = conn.execute("SELECT COUNT(*) FROM stocks WHERE is_low_activity = 0")
print(f"活跃股: {cur.fetchone()[0]}", flush=True)
cur = conn.execute("SELECT COUNT(*) FROM stocks WHERE heat_score > 0")
print(f"有热度分: {cur.fetchone()[0]}", flush=True)
cur = conn.execute("SELECT AVG(heat_score), MAX(heat_score) FROM stocks WHERE heat_score > 0")
r = cur.fetchone()
print(f"热度分: avg={r[0]:.1f}, max={r[1]:.1f}", flush=True)

# Get active trading pool stocks (not low activity, or has heat score)
cur = conn.execute("""
    SELECT code FROM stocks 
    WHERE is_low_activity = 0 OR heat_score > 30
""")
pool_codes = set(r['code'] for r in cur.fetchall())
print(f"交易池股票数: {len(pool_codes)}", flush=True)

# Also get stocks from daily_active_stocks (recently active)
cur = conn.execute("""
    SELECT DISTINCT stock_code FROM daily_active_stocks 
    WHERE is_active = 1 AND check_date >= DATE('now', '-30 days')
""")
active_codes = set(r['stock_code'] for r in cur.fetchall())
print(f"近30日活跃股: {len(active_codes)}", flush=True)

# Union: trading universe
trading_universe = pool_codes | active_codes
print(f"交易域合计: {len(trading_universe)}", flush=True)

# Step 2: Filter kline stocks to trading universe
cur = conn.execute("SELECT stock_code, COUNT(*) as cnt FROM kline_data GROUP BY stock_code HAVING cnt >= 30")
all_kline = {r['stock_code']: r['cnt'] for r in cur.fetchall()}
universe_stocks = [c for c in all_kline if c in trading_universe]
non_universe = [c for c in all_kline if c not in trading_universe]
print(f"\n有K线的: {len(all_kline)} | 在交易域: {len(universe_stocks)} | 不在: {len(non_universe)}", flush=True)

# Step 3: Run backtest on BOTH groups for comparison
from simple_trade.services.strategy.stock_scorer import StockScorer
scorer = StockScorer()

cur = conn.execute("""
    SELECT DISTINCT DATE(time_key) as td FROM kline_data
    WHERE DATE(time_key) >= DATE('now', '-30 days') AND DATE(time_key) <= DATE('now', '-6 days')
    ORDER BY td
""")
test_dates = [r['td'] for r in cur.fetchall()]

def run_backtest(stock_list, label):
    results = []
    for td in test_dates:
        for sc in stock_list:
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

            result = scorer.score_stock(sc, '', ind)
            future = conn.execute(
                "SELECT close_price, high_price FROM kline_data WHERE stock_code=? AND DATE(time_key)>? ORDER BY time_key ASC LIMIT 3",
                (sc, td)).fetchall()
            if not future or closes[-1] <= 0: continue
            buy = closes[-1]
            max_rise = max((k['high_price'] - buy) / buy * 100 for k in future if k['high_price']) if future else 0
            final = (future[-1]['close_price'] - buy) / buy * 100 if future and future[-1]['close_price'] else 0
            outcome = 'WIN' if max_rise >= 3.0 else ('LOSS' if final < -3.0 else 'FLAT')
            results.append({'score': result.total_score, 'passed': result.passed, 'outcome': outcome,
                            'max_rise': max_rise, 'final': final})
    
    print(f"\n{'='*60}")
    print(f"{label} (n={len(results)})")
    print(f"{'='*60}")
    print(f"{'Score':>8} {'Count':>6} {'WinRate':>8} {'LossRate':>9} {'AvgRise':>8} {'AvgFinal':>9}")
    print("-" * 55)
    for lo, hi in [(80,100),(60,79),(40,59),(20,39),(0,19)]:
        br = [r for r in results if lo <= r['score'] <= hi]
        if not br: continue
        w = sum(1 for r in br if r['outcome'] == 'WIN')
        l = sum(1 for r in br if r['outcome'] == 'LOSS')
        ar = sum(r['max_rise'] for r in br) / len(br)
        af = sum(r['final'] for r in br) / len(br)
        print(f"{lo:>3}-{hi:>3}  {len(br):>6} {w/len(br)*100:>7.1f}% {l/len(br)*100:>8.1f}% {ar:>7.1f}% {af:>8.1f}%")
    
    passed = [r for r in results if r['passed']]
    failed = [r for r in results if not r['passed']]
    if passed:
        pw = sum(1 for r in passed if r['outcome'] == 'WIN')
        pl = sum(1 for r in passed if r['outcome'] == 'LOSS')
        print(f"\n  PASS(>=60): {len(passed)}笔 | 胜率{pw/len(passed)*100:.1f}% | 败率{pl/len(passed)*100:.1f}%")
    if failed:
        fw = sum(1 for r in failed if r['outcome'] == 'WIN')
        fl = sum(1 for r in failed if r['outcome'] == 'LOSS')
        print(f"  FAIL(<60):  {len(failed)}笔 | 胜率{fw/len(failed)*100:.1f}% | 败率{fl/len(failed)*100:.1f}%")
    return results

# Run on trading universe
r1 = run_backtest(universe_stocks, "交易域（高活跃/高热度）")
# Run on non-universe for comparison
r2 = run_backtest(non_universe, "非交易域（冷门股）")

conn.close()
