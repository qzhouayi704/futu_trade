import sqlite3
conn = sqlite3.connect('/opt/futu_trade_sys/simple_trade/data/trade.db')
cur = conn.cursor()
for code in ['HK.06651','HK.01384']:
    cur.execute('SELECT time_key, open_price, high_price, low_price, close_price, volume FROM kline_data WHERE stock_code=? ORDER BY time_key DESC LIMIT 5', (code,))
    rows = cur.fetchall()
    print(f'{code}:')
    for r in rows:
        print(f'  {r}')
    if not rows:
        print('  NO DATA')
# Also check what's the latest date in the whole DB
cur.execute('SELECT MAX(time_key) FROM kline_data')
print(f'\nLatest kline date in DB: {cur.fetchone()[0]}')
# Check total kline records
cur.execute('SELECT COUNT(*) FROM kline_data')
print(f'Total kline records: {cur.fetchone()[0]}')
conn.close()
