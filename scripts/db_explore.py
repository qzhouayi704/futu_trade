#!/usr/bin/env python3
"""数据库回测数据探查"""
import sqlite3, json

DB_PATH = '/opt/futu_trade_sys/simple_trade/data/trade.db'
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 1. 列出所有表和行数
tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print('=== 数据库表 ===')
for t in tables:
    count = cursor.execute(f"SELECT COUNT(*) FROM [{t['name']}]").fetchone()[0]
    if count > 0:
        print(f"  {t['name']}: {count} 行")

# 2. signal_pipeline 数据
print('\n=== signal_pipeline 日期范围 ===')
r = cursor.execute('SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT trade_date), COUNT(*) FROM signal_pipeline').fetchone()
print(f"  范围: {r[0]} ~ {r[1]}, 共 {r[2]} 个交易日, {r[3]} 条记录")

# 3. action 分布
print('\n=== signal_pipeline action 分布 ===')
rows = cursor.execute('SELECT final_action, COUNT(*) c FROM signal_pipeline GROUP BY final_action ORDER BY c DESC').fetchall()
for row in rows:
    print(f"  {row['final_action']}: {row['c']}")

# 4. direction 分布
print('\n=== signal_pipeline direction 分布 ===')
rows = cursor.execute('SELECT direction, COUNT(*) c FROM signal_pipeline GROUP BY direction ORDER BY c DESC').fetchall()
for row in rows:
    print(f"  {row['direction']}: {row['c']}")

# 5. 最近的signal_pipeline记录(看结构)
print('\n=== 最近5条 signal_pipeline ===')
rows = cursor.execute('SELECT * FROM signal_pipeline ORDER BY id DESC LIMIT 5').fetchall()
cols = [d[0] for d in cursor.description]
print(f"  列: {cols}")
for row in rows:
    print(f"  [{row['timestamp']}] {row['stock_name']}({row['stock_code']}) {row['direction']} str={row['strength']} → {row['final_action']}: {row['final_reason'][:60]}")

# 6. simulated_trades
print('\n=== simulated_trades ===')
try:
    r = cursor.execute('SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM simulated_trades').fetchone()
    print(f"  范围: {r[0]} ~ {r[1]}, 共 {r[2]} 条")
    # 看最近几条
    rows = cursor.execute('SELECT * FROM simulated_trades ORDER BY id DESC LIMIT 3').fetchall()
    if rows:
        cols = [d[0] for d in cursor.description]
        print(f"  列: {cols}")
        for row in rows:
            d = dict(row)
            print(f"  [{d.get('trade_date','')}] {d.get('stock_name','')} {d.get('direction','')} price={d.get('price','')} qty={d.get('quantity','')}")
except Exception as e:
    print(f"  错误: {e}")

# 7. kline_data
print('\n=== kline_data ===')
try:
    r = cursor.execute('SELECT MIN(time_key), MAX(time_key), COUNT(DISTINCT stock_code), COUNT(*) FROM kline_data').fetchone()
    print(f"  范围: {r[0]} ~ {r[1]}, {r[2]} 只股票, {r[3]} 条K线")
except Exception as e:
    print(f"  错误: {e}")

# 8. sniper_signals
print('\n=== sniper_signals ===')
try:
    r = cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%sniper%'").fetchall()
    for t in r:
        count = cursor.execute(f"SELECT COUNT(*) FROM [{t['name']}]").fetchone()[0]
        print(f"  {t['name']}: {count} 行")
except: pass

# 9. ticker_data (tick级数据)
print('\n=== ticker/tick 数据 ===')
for tname in ['ticker_data', 'tick_data', 'scalping_ticks', 'quote_snapshots']:
    try:
        r = cursor.execute(f"SELECT COUNT(*) FROM [{tname}]").fetchone()[0]
        if r > 0:
            print(f"  {tname}: {r} 行")
            r2 = cursor.execute(f"SELECT MIN(timestamp), MAX(timestamp) FROM [{tname}]").fetchone()
            print(f"    范围: {r2[0]} ~ {r2[1]}")
    except: pass

conn.close()
