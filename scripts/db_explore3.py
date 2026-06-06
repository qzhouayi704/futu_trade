#!/usr/bin/env python3
"""补充探查: sniper_signals, big_order_tracking, trade_signals 结构"""
import sqlite3

DB = '/opt/futu_trade_sys/simple_trade/data/trade.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# 1. sniper_signals 按 signal_type 分布
print('=== sniper_signals signal_type 分布 ===')
rows = conn.execute("SELECT signal_type, COUNT(*) c FROM sniper_signals GROUP BY signal_type ORDER BY c DESC").fetchall()
for r in rows:
    print(f"  {r['signal_type']}: {r['c']}")

# 2. sniper_signals 按日+type
print('\n=== sniper_signals 按日 (最近5日) ===')
rows = conn.execute("""
    SELECT trade_date, COUNT(*) c, 
           SUM(CASE WHEN is_red=1 THEN 1 ELSE 0 END) as red_count
    FROM sniper_signals GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5
""").fetchall()
for r in rows:
    print(f"  {r['trade_date']}: {r['c']} 条 (红色信号={r['red_count']})")

# 3. big_order_tracking 结构
print('\n=== big_order_tracking 结构 ===')
cols = conn.execute("PRAGMA table_info(big_order_tracking)").fetchall()
for c in cols:
    print(f"  {c['name']} ({c['type']})")

# 4. big_order_tracking 最近1条
print('\n=== big_order_tracking 最近1条 ===')
r = conn.execute('SELECT * FROM big_order_tracking ORDER BY id DESC LIMIT 1').fetchone()
if r:
    d = dict(r)
    for k in list(d.keys()):
        v = d[k]
        if isinstance(v, str) and len(v) > 100:
            d[k] = v[:100] + '...'
    print(f"  {d}")

# 5. big_order_tracking 按日+方向
print('\n=== big_order_tracking 按日统计 (最近5日) ===')
rows = conn.execute("""
    SELECT trade_date, COUNT(*) c,
           SUM(CASE WHEN direction='BUY' THEN 1 ELSE 0 END) as buys,
           SUM(CASE WHEN direction='SELL' THEN 1 ELSE 0 END) as sells,
           SUM(CASE WHEN direction='BUY' THEN turnover ELSE 0 END) as buy_vol,
           SUM(CASE WHEN direction='SELL' THEN turnover ELSE 0 END) as sell_vol
    FROM big_order_tracking GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5
""").fetchall()
for r in rows:
    print(f"  {r['trade_date']}: {r['c']} 笔 (BUY={r['buys']}/{r['buy_vol']:.0f}, SELL={r['sells']}/{r['sell_vol']:.0f})")

# 6. trade_signals 按日+方向
print('\n=== trade_signals 按日统计 (最近5日) ===')
try:
    rows = conn.execute("""
        SELECT trade_date, COUNT(*) c,
               SUM(CASE WHEN direction='BUY' THEN 1 ELSE 0 END) as buys,
               SUM(CASE WHEN direction='SELL' THEN 1 ELSE 0 END) as sells
        FROM trade_signals GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5
    """).fetchall()
    for r in rows:
        print(f"  {r['trade_date']}: {r['c']} 条 (BUY={r['buys']}, SELL={r['sells']})")
except Exception as e:
    print(f"  错误: {e}")

# 7. trade_signals 最近1条
print('\n=== trade_signals 最近1条 ===')
r = conn.execute('SELECT * FROM trade_signals ORDER BY id DESC LIMIT 1').fetchone()
if r:
    d = dict(r)
    for k in list(d.keys()):
        v = d[k]
        if isinstance(v, str) and len(v) > 80:
            d[k] = v[:80] + '...'
    print(f"  {d}")

# 8. capital_flow_signals 结构+分布
print('\n=== capital_flow_signals 结构 ===')
cols = conn.execute("PRAGMA table_info(capital_flow_signals)").fetchall()
for c in cols:
    print(f"  {c['name']} ({c['type']})")

print('\n=== capital_flow_signals 信号分布 ===')
try:
    rows = conn.execute("SELECT signal_type, COUNT(*) c FROM capital_flow_signals GROUP BY signal_type ORDER BY c DESC LIMIT 10").fetchall()
    for r in rows:
        print(f"  {r['signal_type']}: {r['c']}")
except: pass

conn.close()
