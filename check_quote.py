#!/usr/bin/env python3
"""临时脚本：检查 HK.01384 的 quote 缓存数据"""
import sys, os
sys.path.insert(0, '/opt/futu_trade_sys')
os.chdir('/opt/futu_trade_sys')

# 方法1: 直接查看内存中 state_manager 的 quote 缓存
# 这里用 API 调用更简单
import urllib.request, json

# 查看 quote 中的关键字段
url = 'http://127.0.0.1:5001/quote/realtime?codes=HK.01384'
try:
    resp = urllib.request.urlopen(url, timeout=5)
    data = json.loads(resp.read())
    if data.get('success') and data.get('data'):
        quotes = data['data']
        if isinstance(quotes, list):
            for q in quotes:
                print(f"=== {q.get('code', '?')} ===")
                print(f"  volume_ratio: {q.get('volume_ratio', 'MISSING')}")
                print(f"  last_price: {q.get('last_price', 'MISSING')}")
                print(f"  change_rate: {q.get('change_rate', 'MISSING')}")
                print(f"  high_price: {q.get('high_price', 'MISSING')}")
                print(f"  low_price: {q.get('low_price', 'MISSING')}")
                print(f"  volume: {q.get('volume', 'MISSING')}")
                print(f"  turnover: {q.get('turnover', 'MISSING')}")
                print(f"  net_inflow_ratio: {q.get('net_inflow_ratio', 'MISSING')}")
                print(f"  ticker_buy_sell_ratio: {q.get('ticker_buy_sell_ratio', 'MISSING')}")
        else:
            print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"API failed: {data}")
except Exception as e:
    print(f"Error: {e}")

# 方法2: 直接看 state_manager 缓存中的 quote keys
print("\n--- Checking cached quotes for HK.01384 ---")
try:
    url2 = 'http://127.0.0.1:5001/system/quotes-cache'
    resp2 = urllib.request.urlopen(url2, timeout=5)
    cache = json.loads(resp2.read())
    if cache.get('data'):
        quotes_list = cache['data'] if isinstance(cache['data'], list) else cache['data'].get('quotes', [])
        for q in quotes_list:
            if q.get('code') == 'HK.01384':
                print(f"Found in cache! Keys: {sorted(q.keys())}")
                print(f"  volume_ratio: {q.get('volume_ratio', 'MISSING')}")
                print(f"  ticker_buy_sell_ratio: {q.get('ticker_buy_sell_ratio', 'MISSING')}")
                break
        else:
            print("HK.01384 NOT in cached quotes")
except Exception as e:
    print(f"Cache check error: {e}")
