import sqlite3

DB = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'
conn = sqlite3.connect(DB)
c = conn.cursor()

# 1. daily_active_stocks 列结构
print('=== daily_active_stocks 结构 ===')
c.execute("PRAGMA table_info(daily_active_stocks)")
for r in c.fetchall():
    print(r)

c.execute("SELECT * FROM daily_active_stocks WHERE stock_code = 'HK.00595' ORDER BY rowid DESC LIMIT 3")
rows = c.fetchall()
if rows:
    cols = [d[0] for d in c.description]
    print(f'列: {cols}')
    for r in rows:
        print(r)
else:
    print('无数据')

# 2. 5分钟K线
print('\n=== 5分钟K线（最新10条）===')
c.execute(
    "SELECT time_key, open_price, high_price, low_price, close_price, volume "
    "FROM kline_5min_data WHERE stock_code = 'HK.00595' ORDER BY time_key DESC LIMIT 10"
)
rows = c.fetchall()
for r in rows:
    print(r)
if not rows:
    print('无5分钟K线数据')

# 3. 尝试从网络获取今天行情 (futunn)
print('\n=== 尝试获取网络行情 ===')
try:
    import urllib.request
    import json
    # 尝试读取系统API（如果后端运行中）
    url = 'http://localhost:8000/api/stocks/HK.00595/quote'
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=3) as resp:
        data = json.loads(resp.read())
        print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception as e:
    print(f'本地API不可用: {e}')

# 4. 尝试其他API端点
try:
    url2 = 'http://localhost:8000/api/market-scan/hot-stocks'
    req2 = urllib.request.Request(url2, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req2, timeout=5) as resp:
        data = json.loads(resp.read())
        # 找 00595
        for stock in data.get('data', data) if isinstance(data, dict) else data:
            if isinstance(stock, dict) and '00595' in str(stock.get('code', '')):
                print('\n=== 市场扫描中的00595 ===')
                print(json.dumps(stock, indent=2, ensure_ascii=False))
                break
except Exception as e:
    print(f'市场扫描API不可用: {e}')

conn.close()
