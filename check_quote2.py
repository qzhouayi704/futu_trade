import urllib.request, json
resp = urllib.request.urlopen('http://127.0.0.1:5001/api/quotes', timeout=10)
d = json.loads(resp.read())
targets = ['01384', '00068']
for q in d.get('data', []):
    code = q.get('code', '')
    if any(t in code for t in targets):
        name = q.get('name', '')
        print('=== {} ({}) ==='.format(code, name))
        for key in ['volume_ratio', 'ticker_buy_sell_ratio', 'net_inflow_ratio',
                     'last_price', 'change_rate', 'high_price', 'low_price',
                     'capital_score', 'main_net_inflow']:
            val = q.get(key, 'MISSING')
            print('  {}: {}'.format(key, val))
        print()
