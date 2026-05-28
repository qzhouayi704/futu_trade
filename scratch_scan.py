import json
with open(r'C:\Users\ZHOUYICAN\.gemini\antigravity\brain\ca5234b5-70e6-4524-81d4-3d18b5e1f48f\.system_generated\steps\357\content.md', 'r', encoding='utf-8') as f:
    text = f.read()
for line in text.strip().split('\n'):
    line = line.strip()
    if line.startswith('{'):
        data = json.loads(line)
        break
stocks = data['data']
print(f"Total stocks with ticker data: {len(stocks)}")
print(f"\n{'='*80}")
print(f"{'Stock':<16} {'Name':<12} {'Signal':<10} {'Momentum':<10} {'CumNet':>10} {'BuyRatio':>8} {'Points':>6}")
print(f"{'='*80}")
for s in stocks[:30]:
    print(f"{s['stock_code']:<16} {s.get('stock_name',''):<12} {s.get('signal',''):<10} {s.get('momentum_label',''):<10} {s.get('cum_net',0):>10.1f} {s.get('buy_sell_ratio','N/A'):>8} {s.get('data_points',0):>6}")
