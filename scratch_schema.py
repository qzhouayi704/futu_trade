#!/usr/bin/env python3
"""查询表结构"""
import sqlite3
conn = sqlite3.connect('simple_trade/data/trade.db')

print("=== capital_flow_daily 表结构 ===")
cur = conn.execute("PRAGMA table_info(capital_flow_daily)")
for r in cur.fetchall():
    print(r)

print("\n=== 所有表 ===")
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
for r in cur.fetchall():
    print(r[0])

print("\n=== capital_flow_daily 样例数据 ===")
cur = conn.execute("SELECT * FROM capital_flow_daily WHERE stock_code='HK.00772' ORDER BY date DESC LIMIT 1")
cols = [d[0] for d in cur.description]
print("Columns:", cols)
rows = cur.fetchall()
for r in rows:
    for i, c in enumerate(cols):
        print(f"  {c}: {r[i]}")

# 检查是否有 kline/stock_daily 表
print("\n=== 尝试查找K线表 ===")
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%daily%' OR name LIKE '%kline%' OR name LIKE '%candle%' OR name LIKE '%price%')")
for r in cur.fetchall():
    print(r[0])
    pragma = conn.execute(f"PRAGMA table_info({r[0]})")
    for col in pragma.fetchall():
        print(f"  {col}")

conn.close()
