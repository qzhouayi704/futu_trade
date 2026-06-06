#!/usr/bin/env python3
"""探查 ticker_data 和 sniper_signals 结构，为回测做准备"""
import sqlite3, json
from datetime import datetime

DB = '/opt/futu_trade_sys/simple_trade/data/trade.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# 1. ticker_data 结构
print('=== ticker_data 结构 ===')
cols = conn.execute("PRAGMA table_info(ticker_data)").fetchall()
for c in cols:
    print(f"  {c['name']} ({c['type']})")

# 2. 时间范围（转换时间戳）
print('\n=== ticker_data 时间范围 ===')
r = conn.execute('SELECT MIN(timestamp), MAX(timestamp) FROM ticker_data').fetchone()
ts_min, ts_max = r[0], r[1]
# 判断是毫秒还是秒
if ts_min > 1e12:  # 毫秒
    dt_min = datetime.fromtimestamp(ts_min / 1000)
    dt_max = datetime.fromtimestamp(ts_max / 1000)
else:
    dt_min = datetime.fromtimestamp(ts_min)
    dt_max = datetime.fromtimestamp(ts_max)
print(f"  {dt_min} ~ {dt_max}")

# 3. 每日数据量
print('\n=== ticker_data 每日数据量 (最近10日) ===')
if ts_min > 1e12:
    rows = conn.execute("""
        SELECT date(timestamp/1000, 'unixepoch', 'localtime') as d, 
               COUNT(*) as c, COUNT(DISTINCT stock_code) as stocks
        FROM ticker_data 
        GROUP BY d ORDER BY d DESC LIMIT 10
    """).fetchall()
else:
    rows = conn.execute("""
        SELECT date(timestamp, 'unixepoch', 'localtime') as d, 
               COUNT(*) as c, COUNT(DISTINCT stock_code) as stocks
        FROM ticker_data 
        GROUP BY d ORDER BY d DESC LIMIT 10
    """).fetchall()
for row in rows:
    print(f"  {row['d']}: {row['c']:>8} 条, {row['stocks']} 只股票")

# 4. 看一条 ticker_data
print('\n=== 最近1条 ticker_data ===')
r = conn.execute('SELECT * FROM ticker_data ORDER BY id DESC LIMIT 1').fetchone()
print(f"  {dict(r)}")

# 5. sniper_signals 结构
print('\n=== sniper_signals 结构 ===')
cols = conn.execute("PRAGMA table_info(sniper_signals)").fetchall()
for c in cols:
    print(f"  {c['name']} ({c['type']})")

# 6. sniper_signals 最近5条
print('\n=== 最近5条 sniper_signals ===')
rows = conn.execute('SELECT * FROM sniper_signals ORDER BY id DESC LIMIT 5').fetchall()
for row in rows:
    d = dict(row)
    print(f"  [{d.get('created_at','')}] {d.get('stock_name','')}({d.get('stock_code','')}) "
          f"type={d.get('signal_type','')} dir={d.get('direction','')} str={d.get('strength','')}")

# 7. sniper_signals 按日期分布
print('\n=== sniper_signals 按日分布 (最近10日) ===')
rows = conn.execute("""
    SELECT date(created_at) as d, COUNT(*) as c, 
           SUM(CASE WHEN direction='BUY' THEN 1 ELSE 0 END) as buys,
           SUM(CASE WHEN direction='SELL' THEN 1 ELSE 0 END) as sells
    FROM sniper_signals GROUP BY d ORDER BY d DESC LIMIT 10
""").fetchall()
for row in rows:
    print(f"  {row['d']}: {row['c']} 条 (BUY={row['buys']}, SELL={row['sells']})")

# 8. trade_signals 结构
print('\n=== trade_signals 结构 ===')
cols = conn.execute("PRAGMA table_info(trade_signals)").fetchall()
for c in cols:
    print(f"  {c['name']} ({c['type']})")

# 9. trade_signals 最近一条
print('\n=== 最近1条 trade_signals ===')
r = conn.execute('SELECT * FROM trade_signals ORDER BY id DESC LIMIT 1').fetchone()
if r:
    d = dict(r)
    for k in list(d.keys()):
        v = d[k]
        if isinstance(v, str) and len(v) > 80:
            d[k] = v[:80] + '...'
    print(f"  {d}")

conn.close()
