#!/usr/bin/env python3
import sqlite3
DB_PATH = '/opt/futu_trade_sys/simple_trade/data/trade.db'
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row

# 1. overnight_screen_results schema
cols = db.execute("PRAGMA table_info(overnight_screen_results)").fetchall()
print("=== overnight_screen_results columns ===")
for c in cols:
    print(f"  {c['name']} ({c['type']})")
rows = db.execute("SELECT * FROM overnight_screen_results LIMIT 2").fetchall()
for r in rows:
    d = dict(r)
    # Truncate long fields
    for k, v in d.items():
        if isinstance(v, str) and len(v) > 100:
            d[k] = v[:100] + '...'
    print(f"  {d}")

# 2. Check daily_active_stocks as alternative
print("\n=== daily_active_stocks ===")
cols = db.execute("PRAGMA table_info(daily_active_stocks)").fetchall()
print("Columns:", [c['name'] for c in cols])
count = db.execute("SELECT COUNT(*) as c FROM daily_active_stocks").fetchone()['c']
print(f"Total rows: {count}")
if count > 0:
    dates = db.execute("SELECT DISTINCT date FROM daily_active_stocks ORDER BY date DESC LIMIT 10").fetchall()
    print(f"Dates: {[d['date'] for d in dates]}")

# 3. Check trading_records
print("\n=== trading_records ===")
cols = db.execute("PRAGMA table_info(trading_records)").fetchall()
print("Columns:", [c['name'] for c in cols])
count = db.execute("SELECT COUNT(*) as c FROM trading_records").fetchone()['c']
print(f"Total rows: {count}")

# 4. Check kline_data stock count per date
print("\n=== kline_data distribution ===")
rows = db.execute("""
    SELECT date(time_key) as d, COUNT(DISTINCT stock_code) as stocks
    FROM kline_data
    GROUP BY date(time_key)
    ORDER BY d DESC LIMIT 20
""").fetchall()
for r in rows:
    print(f"  {r['d']}: {r['stocks']} stocks")

db.close()
