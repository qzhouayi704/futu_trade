#!/usr/bin/env python3
"""一次性清理脚本：删除非交易时段的 ticker_data 垃圾数据"""

import sqlite3
import sys

DB_PATH = r"d:\Program Files\futu_trade_sys\simple_trade\data\trade.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# 1. 统计垃圾数据
c.execute("""
    SELECT COUNT(*) FROM ticker_data
    WHERE CAST(strftime('%H', datetime(timestamp/1000, 'unixepoch', '+8 hours')) AS INTEGER) < 9
       OR CAST(strftime('%H', datetime(timestamp/1000, 'unixepoch', '+8 hours')) AS INTEGER) >= 17
""")
garbage_count = c.fetchone()[0]
print(f"非交易时段垃圾数据: {garbage_count} 条")

# 2. 查看分布
c.execute("""
    SELECT trade_date,
           strftime('%H', datetime(timestamp/1000, 'unixepoch', '+8 hours')) as hour,
           COUNT(*) as cnt
    FROM ticker_data
    WHERE CAST(strftime('%H', datetime(timestamp/1000, 'unixepoch', '+8 hours')) AS INTEGER) < 9
       OR CAST(strftime('%H', datetime(timestamp/1000, 'unixepoch', '+8 hours')) AS INTEGER) >= 17
    GROUP BY trade_date, hour
    ORDER BY trade_date DESC, hour
    LIMIT 20
""")
rows = c.fetchall()
if rows:
    print("\n按日期+小时分布:")
    for r in rows:
        print(f"  {r[0]} {r[1]}:xx -> {r[2]} 条")

# 3. 查看总数据量
c.execute("SELECT COUNT(*) FROM ticker_data")
total = c.fetchone()[0]
print(f"\nticker_data 总数据: {total} 条")
print(f"垃圾占比: {garbage_count/total*100:.1f}%" if total > 0 else "")

# 4. 确认删除
if "--delete" in sys.argv:
    c.execute("""
        DELETE FROM ticker_data
        WHERE CAST(strftime('%H', datetime(timestamp/1000, 'unixepoch', '+8 hours')) AS INTEGER) < 9
           OR CAST(strftime('%H', datetime(timestamp/1000, 'unixepoch', '+8 hours')) AS INTEGER) >= 17
    """)
    deleted = c.rowcount
    conn.commit()
    print(f"\n✅ 已删除 {deleted} 条垃圾数据")
else:
    print("\n⚠️ 预览模式，加 --delete 参数执行删除")

conn.close()
