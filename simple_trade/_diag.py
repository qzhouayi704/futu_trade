#!/usr/bin/env python3
import sqlite3, datetime
db_path = '/data/futu_trade_data/trade.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()
today = datetime.datetime.now().strftime('%Y-%m-%d')

# 1. rt_data
c.execute('SELECT COUNT(*) FROM rt_data WHERE trade_date = ?', (today,))
print(f'rt_data today: {c.fetchone()[0]} rows')

# 2. ticker_data
c.execute('SELECT COUNT(*) FROM ticker_data WHERE trade_date = ?', (today,))
print(f'ticker_data today: {c.fetchone()[0]} rows')

# 3. ticker_data sample
c.execute('SELECT timestamp, direction, price FROM ticker_data WHERE trade_date = ? LIMIT 3', (today,))
for r in c.fetchall():
    print(f'ticker: ts={r[0]} dir={r[1]} price={r[2]}')

# 4. rt_data sample
c.execute('SELECT time, cur_price FROM rt_data WHERE trade_date = ? LIMIT 3', (today,))
for r in c.fetchall():
    print(f'rt_data: time={r[0]} price={r[1]}')

# 5. tables check
for t in ['order_book_snapshot','ticker_credibility','big_order_tracking','scalping_delta_history','kline_5min_data','capital_flow_cache']:
    try:
        c.execute(f'SELECT COUNT(*) FROM {t}')
        print(f'{t}: {c.fetchone()[0]} rows')
    except Exception as e:
        print(f'{t}: NOT FOUND')

conn.close()
