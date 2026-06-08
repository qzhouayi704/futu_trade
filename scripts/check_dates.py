import sqlite3
c = sqlite3.connect('simple_trade/data/trade.db')
dates = [r[0] for r in c.execute('SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date')]
print(f"共 {len(dates)} 天数据:")
for d in dates:
    cnt = c.execute('SELECT COUNT(*) FROM ticker_data WHERE trade_date=?', (d,)).fetchone()[0]
    print(f"  {d}: {cnt:,} 条tick")
c.close()
