#!/usr/bin/env python3
"""排查资金流数据：对比 capital_flow_daily 表数据 vs 实际分布"""

import sqlite3
import sys

db_path = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# 1. Check capital_flow_daily data distribution
print("=== capital_flow_daily 表数据分布 ===")
cur = conn.execute("SELECT COUNT(*) FROM capital_flow_daily")
print(f"总记录数: {cur.fetchone()[0]}")

cur = conn.execute("""
    SELECT net_inflow_ratio, COUNT(*) as cnt
    FROM capital_flow_daily
    GROUP BY net_inflow_ratio
    ORDER BY cnt DESC
    LIMIT 20
""")
print("\nnet_inflow_ratio 值分布 (TOP 20):")
for r in cur.fetchall():
    print(f"  ratio={r['net_inflow_ratio']} | count={r['cnt']}")

# 2. Check recent entries
print("\n=== 最近10条 capital_flow_daily ===")
cur = conn.execute("""
    SELECT stock_code, date, net_inflow, net_inflow_ratio
    FROM capital_flow_daily
    ORDER BY date DESC
    LIMIT 10
""")
for r in cur.fetchall():
    print(f"  {r['stock_code']} | {r['date']} | inflow={r['net_inflow']} | ratio={r['net_inflow_ratio']}")

# 3. Check capital_flow_cache (realtime) distribution
print("\n=== capital_flow_cache 表数据分布 ===")
cur = conn.execute("SELECT COUNT(*) FROM capital_flow_cache")
print(f"总记录数: {cur.fetchone()[0]}")

cur = conn.execute("""
    SELECT 
        MIN(net_inflow_ratio) as min_r,
        MAX(net_inflow_ratio) as max_r,
        AVG(net_inflow_ratio) as avg_r,
        COUNT(DISTINCT net_inflow_ratio) as distinct_count
    FROM capital_flow_cache
""")
r = cur.fetchone()
print(f"  min={r['min_r']}, max={r['max_r']}, avg={r['avg_r']:.4f}, distinct_values={r['distinct_count']}")

cur = conn.execute("""
    SELECT net_inflow_ratio, COUNT(*) as cnt
    FROM capital_flow_cache
    GROUP BY net_inflow_ratio
    ORDER BY cnt DESC
    LIMIT 15
""")
print("\nnet_inflow_ratio 值分布 (TOP 15):")
for r in cur.fetchall():
    print(f"  ratio={r['net_inflow_ratio']} | count={r['cnt']}")

# 4. Check a specific stock's flow data
print("\n=== HK.03738 资金流历史 ===")
cur = conn.execute("""
    SELECT date, net_inflow, net_inflow_ratio
    FROM capital_flow_daily
    WHERE stock_code = 'HK.03738'
    ORDER BY date DESC
    LIMIT 10
""")
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"  {r['date']} | inflow={r['net_inflow']} | ratio={r['net_inflow_ratio']}")
else:
    print("  No data for HK.03738")

conn.close()
