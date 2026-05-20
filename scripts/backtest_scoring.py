#!/usr/bin/env python3
"""分析蓝思科技(HK.06613)的实际买入位和K线特征"""
import sqlite3, sys, json
sys.path.insert(0, '/opt/futu_trade_sys')

DB_PATH = '/opt/futu_trade_sys/simple_trade/data/trade.db'
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row

code = 'HK.06613'

# 1. Trading records
print("=== 交易记录 ===")
for tbl in ['trading_records', 'trade_records']:
    try:
        rows = db.execute(f"SELECT * FROM {tbl} WHERE stock_code=? OR code=? ORDER BY rowid", (code, code)).fetchall()
        if rows:
            print(f"Table: {tbl}, {len(rows)} records")
            for r in rows:
                d = dict(r)
                for k,v in list(d.items()):
                    if isinstance(v, str) and len(v) > 80:
                        d[k] = v[:80]+'...'
                print(f"  {d}")
    except Exception as e:
        print(f"  {tbl}: {e}")

# 2. Signal records
print("\n=== 信号记录 ===")
try:
    rows = db.execute("SELECT * FROM trade_signals WHERE stock_code=? ORDER BY timestamp DESC LIMIT 10", (code,)).fetchall()
    for r in rows:
        print(f"  {r['timestamp'][:19]} signal={r['signal_type']} score={r.get('score','')} reason={str(r.get('reason',''))[:80]}")
except Exception as e:
    print(f"  Error: {e}")

# 3. Overnight screening appearances
print("\n=== 隔夜筛选出现 ===")
rows = db.execute("SELECT screen_date, candidates_json FROM overnight_screen_results ORDER BY screen_date").fetchall()
for row in rows:
    candidates = json.loads(row['candidates_json'])
    for c in candidates:
        if c['stock_code'] == code:
            print(f"  {row['screen_date']}: rank={c['rank']} score={c['total_score']} cat={c['category']}")
            print(f"    metrics: price={c['key_metrics']['last_price']} chg={c['key_metrics']['change_rate']}% "
                  f"turnover_rate={c['key_metrics']['turnover_rate']}% amp={c['key_metrics']['amplitude']}%")
            print(f"    reasons: {c['reasons']}")

# 4. K-line data around the period
print("\n=== K线数据 (近30天) ===")
klines = db.execute("""
    SELECT time_key, open_price, high_price, low_price, close_price, volume, turnover_rate
    FROM kline_data WHERE stock_code=? ORDER BY time_key DESC LIMIT 30
""", (code,)).fetchall()
klines = list(reversed(klines))

print(f"{'日期':12s} {'开':>7s} {'高':>7s} {'低':>7s} {'收':>7s} {'涨跌%':>7s} {'量':>12s} {'换手':>6s}")
for i, k in enumerate(klines):
    prev_c = klines[i-1]['close_price'] if i > 0 else k['open_price']
    chg = ((k['close_price'] or 0) - (prev_c or 0)) / (prev_c or 1) * 100
    # Calc 5-day change
    c5 = klines[i-5]['close_price'] if i >= 5 else None
    chg5 = ((k['close_price'] or 0) - c5) / c5 * 100 if c5 else 0
    
    # Amplitude
    amp = ((k['high_price'] or 0) - (k['low_price'] or 0)) / (k['close_price'] or 1) * 100
    
    # Volume ratio
    if i >= 5:
        avg_vol = sum(klines[j]['volume'] or 0 for j in range(i-5, i)) / 5
        vr = (k['volume'] or 0) / avg_vol if avg_vol > 0 else 0
    else:
        vr = 0
    
    marker = ''
    # Mark if green candle
    if (k['close_price'] or 0) > (k['open_price'] or 0):
        marker = '▲'
    else:
        marker = '▼'
    
    print(f"  {k['time_key'][:10]} {k['open_price']:7.2f} {k['high_price']:7.2f} {k['low_price']:7.2f} "
          f"{k['close_price']:7.2f} {chg:+6.1f}% {k['volume']:>12,.0f} {k['turnover_rate'] or 0:5.1f}% "
          f"amp={amp:.1f}% vr={vr:.1f} 5d={chg5:+.1f}% {marker}")

# 5. Capital flow
print("\n=== 资金流 ===")
try:
    rows = db.execute("SELECT * FROM capital_flow_daily WHERE stock_code=? ORDER BY date DESC LIMIT 15", (code,)).fetchall()
    for r in rows:
        print(f"  {r['date']} net={r['net_inflow']:+,.0f}")
except Exception as e:
    print(f"  {e}")

db.close()
