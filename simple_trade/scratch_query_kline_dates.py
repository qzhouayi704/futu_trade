#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('simple_trade/data/trade.db')
cursor = conn.cursor()

print("Listing unique dates in kline_data (last 10):")
rows = cursor.execute(
    "SELECT DISTINCT time_key FROM kline_data "
    "ORDER BY time_key DESC LIMIT 10"
).fetchall()
for r in rows:
    print(r[0])

print("\nNumber of records for 2026-06-05:")
count = cursor.execute(
    "SELECT COUNT(*) FROM kline_data WHERE time_key LIKE '2026-06-05%'"
).fetchone()
print(count[0])

conn.close()
