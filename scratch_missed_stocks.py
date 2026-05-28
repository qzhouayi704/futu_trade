#!/usr/bin/env python3
"""分析漏掉的股票为什么没有触发信号"""
import sqlite3
db = sqlite3.connect('/opt/futu_trade_sys/simple_trade/data/trade.db')
code, td = 'HK.02166', '2026-05-27'
cnt = db.execute('SELECT COUNT(*) FROM ticker_data WHERE stock_code=? AND trade_date=?', (code, td)).fetchone()[0]
tv = db.execute('SELECT SUM(turnover) FROM ticker_data WHERE stock_code=? AND trade_date=?', (code, td)).fetchone()[0]
tv_wan = (tv or 0)/10000
buy_tv = db.execute("SELECT SUM(turnover) FROM ticker_data WHERE stock_code=? AND trade_date=? AND direction='BUY'", (code, td)).fetchone()[0] or 0
sell_tv = db.execute("SELECT SUM(turnover) FROM ticker_data WHERE stock_code=? AND trade_date=? AND direction='SELL'", (code, td)).fetchone()[0] or 0
print(f'\n=== {code} ({td}) ===')
print(f'记录数: {cnt}, 总成交额: {tv_wan:.0f}万, 买: {buy_tv/10000:.0f}万, 卖: {sell_tv/10000:.0f}万, 净: {(buy_tv-sell_tv)/10000:.0f}万')
rows = db.execute("""
    SELECT substr(datetime(timestamp/1000,'unixepoch','+8 hours'),12,5) as minute,
           direction, SUM(turnover) as tv
    FROM ticker_data WHERE stock_code=? AND trade_date=?
    GROUP BY minute, direction ORDER BY minute
""", (code, td)).fetchall()
mins = {}
for m,d,t in rows:
    if m not in mins: mins[m]={'b':0,'s':0}
    if d=='BUY': mins[m]['b']+=float(t or 0)
    elif d=='SELL': mins[m]['s']+=float(t or 0)
nets = [(m, round((v['b']-v['s'])/10000,1), round((v['b']+v['s'])/10000,1)) for m,v in mins.items()]
nets.sort(key=lambda x:-x[1])
print(f'净买入TOP5:')
for m,n,tv in nets[:5]:
    print(f'  {m} 净买+{n}万 成交{tv}万')
nets.sort(key=lambda x:x[1])
print(f'净卖出TOP5:')
for m,n,tv in nets[:5]:
    print(f'  {m} 净买{n}万 成交{tv}万')
print(f'日成交额{tv_wan:.0f}万 vs 阈值1000万: {"通过" if tv_wan>=1000 else "未达标!"}')
# 计算动态mega阈值
avg_tv = tv_wan / len(mins) if mins else 0
abs_nets_list = [abs(n) for _,n,_ in [(m, round((v['b']-v['s'])/10000,1), 0) for m,v in mins.items()] if n!=0]
avg_abs = sum(abs_nets_list)/len(abs_nets_list) if abs_nets_list else avg_tv
if tv_wan >= 50000: mega_min = 5000
elif tv_wan >= 10000: mega_min = 2000
elif tv_wan >= 1000: mega_min = 800
else: mega_min = 800
dyn_mega = max(mega_min, avg_abs * 3)
print(f'\n动态阈值分析:')
print(f'  avg_abs_net={avg_abs:.1f}万, mega_min={mega_min}万')
print(f'  dyn_mega = max({mega_min}, {avg_abs:.1f}*3={avg_abs*3:.1f}) = {dyn_mega:.1f}万')
max_net = max(n for _,n,_ in [(m, round((v['b']-v['s'])/10000,1), 0) for m,v in mins.items()])
print(f'  单分钟最大净买入: {max_net:.1f}万 vs 阈值{dyn_mega:.1f}万 → {"触发!" if max_net>dyn_mega else "未触发"}')
db.close()
