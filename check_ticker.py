import urllib.request, json

try:
    resp = urllib.request.urlopen("http://localhost:9088/api/high-turnover-stocks", timeout=10)
    data = json.loads(resp.read())
    stocks = data.get("data", {}).get("stocks", [])
    has_ticker = [s for s in stocks if s.get("ticker_summary")]
    no_ticker = [s for s in stocks if not s.get("ticker_summary")]
    print(f"总股票数: {len(stocks)}")
    print(f"有ticker_summary: {len(has_ticker)}")
    print(f"无ticker_summary: {len(no_ticker)}")
    if has_ticker:
        for s in has_ticker[:5]:
            ts = s["ticker_summary"]
            print(f"  {s['code']} {s['name']}: score={ts['score']} ratio={ts['buy_sell_ratio']} bias={ts['bias_label']}")
    else:
        print("  全部为空!")
        # 检查是否是监控没开
        resp2 = urllib.request.urlopen("http://localhost:9088/api/system/status", timeout=5)
        status = json.loads(resp2.read())
        mon = status.get("data", {}).get("monitoring", {})
        pusher = status.get("data", {}).get("quote_pusher", {})
        print(f"  监控运行: {mon.get('is_running')}")
        print(f"  推送运行: {pusher.get('is_running')}")
        sub = status.get("data", {}).get("subscription", {})
        print(f"  QUOTE订阅: {sub.get('subscribed_count')}")
except Exception as e:
    print(f"API请求失败: {e}")
