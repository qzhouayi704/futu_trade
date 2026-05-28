#!/usr/bin/env python3
import sqlite3
conn = sqlite3.connect('simple_trade/data/trade.db')
rows = conn.execute(
    "SELECT trade_date, COUNT(DISTINCT stock_code), COUNT(*) "
    "FROM ticker_data GROUP BY trade_date ORDER BY trade_date"
).fetchall()
for d, n, t in rows:
    q = "OK" if t > 500000 else ("sparse" if t > 50000 else "bad")
    print(f"{d} stocks={n:>3} ticks={t:>8} {q}")
print()
# daily_kline dates
try:
    r2 = conn.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM daily_kline").fetchone()
    print(f"daily_kline: {r2[0]}~{r2[1]} rows={r2[2]}")
except: pass
