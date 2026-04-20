#!/usr/bin/env python3
"""检查数据库中的买入信号"""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), '..', 'simple_trade', 'data', 'trade.db')
conn = sqlite3.connect(db_path)
c = conn.cursor()

# 查看买入信号数量
c.execute("SELECT COUNT(*) FROM trade_signals WHERE signal_type='BUY'")
print(f"BUY signals count: {c.fetchone()[0]}")

# 查看所有买入信号
c.execute("""
    SELECT ts.id, s.code, s.name, ts.signal_type, ts.signal_price, 
           ts.created_at, ts.strategy_id, ts.strategy_name
    FROM trade_signals ts 
    JOIN stocks s ON ts.stock_id = s.id 
    WHERE ts.signal_type='BUY' 
    ORDER BY ts.created_at DESC
""")
rows = c.fetchall()
print(f"\nTotal BUY signals: {len(rows)}")
print("\n--- All BUY signals ---")
for r in rows:
    print(f"  ID={r[0]}, Code={r[1]}, Name={r[2]}, Price={r[4]}, Time={r[5]}, Strategy={r[6]}/{r[7]}")

# 检查 kline_data 数据情况
print("\n--- kline_data sample ---")
if rows:
    sample_code = rows[0][1]
    c.execute("""
        SELECT stock_code, time_key, open_price, close_price, high_price, low_price, volume, turnover
        FROM kline_data 
        WHERE stock_code = ?
        ORDER BY time_key DESC
        LIMIT 5
    """, (sample_code,))
    kline_rows = c.fetchall()
    for kr in kline_rows:
        print(f"  {kr}")

# 检查所有有买入信号的股票的kline数据范围
print("\n--- kline data coverage for buy signal stocks ---")
stock_codes = list(set(r[1] for r in rows))
for code in stock_codes[:10]:
    c.execute("""
        SELECT MIN(time_key), MAX(time_key), COUNT(*)
        FROM kline_data
        WHERE stock_code = ?
    """, (code,))
    kline_info = c.fetchone()
    print(f"  {code}: from={kline_info[0]}, to={kline_info[1]}, count={kline_info[2]}")

conn.close()
