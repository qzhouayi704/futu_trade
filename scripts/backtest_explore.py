#!/usr/bin/env python3
"""回测脚本：使用历史筛选数据验证3策略评分系统的有效性"""

import sqlite3
import sys
sys.path.insert(0, '/opt/futu_trade_sys')

DB_PATH = '/opt/futu_trade_sys/simple_trade/data/trade.db'
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row

# 1. 查看 overnight_screening_results
print("=== overnight_screening_results ===")
try:
    cols = db.execute("PRAGMA table_info(overnight_screening_results)").fetchall()
    print("Columns:", [c['name'] for c in cols])
    count = db.execute("SELECT COUNT(*) as c FROM overnight_screening_results").fetchone()['c']
    dates = db.execute("SELECT DISTINCT screening_date FROM overnight_screening_results ORDER BY screening_date DESC LIMIT 10").fetchall()
    print(f"Total rows: {count}, Dates: {[d['screening_date'] for d in dates]}")
    sample = db.execute("SELECT * FROM overnight_screening_results ORDER BY screening_date DESC LIMIT 3").fetchall()
    for s in sample:
        print(f"  {dict(s)}")
except Exception as e:
    print(f"  Error: {e}")

# 2. kline_data
print("\n=== kline_data ===")
try:
    count = db.execute("SELECT COUNT(*) as c FROM kline_data").fetchone()['c']
    date_range = db.execute("SELECT MIN(time_key) as mn, MAX(time_key) as mx FROM kline_data").fetchone()
    stocks = db.execute("SELECT COUNT(DISTINCT stock_code) as c FROM kline_data").fetchone()['c']
    print(f"Total rows: {count}, stocks: {stocks}, range: {date_range['mn']} ~ {date_range['mx']}")
except Exception as e:
    print(f"  Error: {e}")

# 3. capital_flow_daily
print("\n=== capital_flow_daily ===")
try:
    count = db.execute("SELECT COUNT(*) as c FROM capital_flow_daily").fetchone()['c']
    print(f"Total rows: {count}")
    if count > 0:
        date_range = db.execute("SELECT MIN(date) as mn, MAX(date) as mx FROM capital_flow_daily").fetchone()
        print(f"  range: {date_range['mn']} ~ {date_range['mx']}")
except Exception as e:
    print(f"  Error: {e}")

# 4. capital_flow_cache
print("\n=== capital_flow_cache ===")
try:
    count = db.execute("SELECT COUNT(*) as c FROM capital_flow_cache").fetchone()['c']
    print(f"Total rows: {count}")
except Exception as e:
    print(f"  Error: {e}")

db.close()
