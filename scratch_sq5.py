#!/usr/bin/env python3
"""查CCASS + signal_pipeline最近 + recommendation"""
import sqlite3, json

conn = sqlite3.connect('simple_trade/data/trade.db')
conn.row_factory = sqlite3.Row

codes = ['HK.00772', 'HK.03888']

# 1. CCASS表结构
print("=== ccass_holdings 表结构 ===")
cur = conn.execute("PRAGMA table_info(ccass_holdings)")
for r in cur.fetchall():
    print(f"  {r[1]}: {r[2]}")

# 2. CCASS数据
print("\n=== ccass_holdings 数据 ===")
for code in codes:
    cur = conn.execute("SELECT * FROM ccass_holdings WHERE stock_code=? ORDER BY rowid DESC LIMIT 3", (code,))
    rows = cur.fetchall()
    if rows:
        cols = [d[0] for d in cur.description]
        print(f"\n{code} ({len(rows)}):")
        for r in rows:
            print({c: r[c] for c in cols})
    else:
        print(f"\n{code}: no data")

# 3. signal_pipeline 最近20条
print("\n=== signal_pipeline 最近20条 ===")
cur = conn.execute("SELECT trade_date, stock_code, stock_name, source, direction, strength, final_action, final_reason FROM signal_pipeline ORDER BY id DESC LIMIT 20")
for r in cur.fetchall():
    sc = r['stock_code']
    mark = ' ***' if sc in codes else ''
    print(f"  [{r['trade_date']}] {sc} {r['stock_name']:6s} {r['source']:8s} {r['direction']:4s} str={r['strength']:5.0f} -> {r['final_action']:8s} | {r['final_reason'][:60]}{mark}")

# 4. recommendation_log 表结构
print("\n=== recommendation_log 表结构 ===")
cur = conn.execute("PRAGMA table_info(recommendation_log)")
for r in cur.fetchall():
    print(f"  {r[1]}: {r[2]}")

# 5. recommendation_log
print("\n=== recommendation_log 数据 ===")
for code in codes:
    cur = conn.execute("SELECT * FROM recommendation_log WHERE stock_code=? ORDER BY rowid DESC LIMIT 2", (code,))
    rows = cur.fetchall()
    if rows:
        cols = [d[0] for d in cur.description]
        print(f"\n{code} ({len(rows)}):")
        for r in rows:
            for c in cols:
                print(f"  {c}: {r[c]}")
            print()
    else:
        print(f"\n{code}: no data")

conn.close()
