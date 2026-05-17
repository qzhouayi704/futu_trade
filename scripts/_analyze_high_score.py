"""深入分析80+分交易的盈亏原因"""
import json

# 加载两个数据源
perf = json.load(open('scripts/buy_performance_analysis.json','r',encoding='utf-8'))
scores = json.load(open('scripts/scoring_backtest.json','r',encoding='utf-8'))

# 找出所有80+分交易的详细信息
high_trades = [s for s in scores['scored_trades'] if s['score'] >= 80]

# 用 code+date+buy_price 关联到 perf 的完整数据
perf_map = {}
for p in perf['trade_patterns']:
    key = f"{p['code']}_{p['date']}_{p['buy_price']}"
    perf_map[key] = p

# 从indicators获取更多数据
ind_data = json.load(open('scripts/buy_day_indicators.json','r',encoding='utf-8'))
ind_map = {}
for t in ind_data['trades']:
    key = f"{t['code']}_{t['date']}_{t['buy_price']}"
    ind_map[key] = t

print("=" * 90)
print("80+分交易逐笔分析（12笔）")
print("=" * 90)

wins = [t for t in high_trades if t['result'] == 'WIN']
losses = [t for t in high_trades if t['result'] == 'LOSS']

# 分析每笔
for t in high_trades:
    code = t['code']
    date = t['date']
    
    # 从perf找到完整的买卖配对数据
    key = f"{code}_{date}_{t.get('actual_pct',0)}"
    
    # 直接用actual_pct匹配
    matched = None
    for p in perf['trade_patterns']:
        if p['code'] == code and p['date'] == date and abs(p['actual_pct'] - t['actual_pct']) < 0.01:
            matched = p
            break
    
    print(f"\n{'WIN' if t['result']=='WIN' else 'LOSS':4s} | score={t['score']} | {code} {date}")
    print(f"  actual: {t['actual_pct']:+.2f}% | potential: {t.get('potential_pct',0):+.2f}% | hold: {t['hold_minutes']:.1f}min")
    
    if matched:
        print(f"  buy:  {matched['buy_time']} @ {matched['buy_price']}")
        print(f"  sell: {matched['sell_time']} @ {matched['sell_price']}")
        print(f"  max after buy: {matched['max_price_after_buy']} ({matched['potential_pct']:+.2f}%)")
        print(f"  min after buy: {matched['min_price_after_buy']} ({matched['max_drawdown_pct']:+.2f}%)")
        print(f"  capture: {matched['capture_ratio']:.1f}%")
        
        # 判断亏损原因
        if t['result'] == 'LOSS':
            if matched['was_profitable_entry']:
                reason = "方向对但卖太早/恐慌卖出"
            elif matched['hold_minutes'] < 2:
                reason = "恐慌性卖出（<2分钟）"
            elif matched['max_drawdown_pct'] < -3:
                reason = "追高后大幅回调"
            else:
                reason = "买在高点，后续无涨"
            print(f"  >>> 亏损原因: {reason}")

print("\n" + "=" * 90)
print("汇总分析")
print("=" * 90)

# 持仓时间分析
win_hold = [t['hold_minutes'] for t in wins]
loss_hold = [t['hold_minutes'] for t in losses]
print(f"\n持仓时间:")
print(f"  WIN  avg={sum(win_hold)/len(win_hold):.1f}min, trades: {[f'{h:.1f}' for h in win_hold]}")
print(f"  LOSS avg={sum(loss_hold)/len(loss_hold):.1f}min, trades: {[f'{h:.1f}' for h in loss_hold]}")

# 同一天同一股的重复交易
from collections import Counter
day_stock = Counter()
for t in high_trades:
    day_stock[f"{t['code']}_{t['date']}"] += 1

print(f"\n同日同股重复交易:")
for k, cnt in day_stock.most_common():
    if cnt > 1:
        code, date = k.split('_')
        sub = [t for t in high_trades if t['code']==code and t['date']==date]
        w = sum(1 for t in sub if t['result']=='WIN')
        l = sum(1 for t in sub if t['result']=='LOSS')
        print(f"  {code} {date}: {cnt}笔 (WIN:{w} LOSS:{l})")

# 买入价 vs 日内位置
print(f"\n买入价在日内的位置:")
for t in high_trades:
    matched = None
    for p in perf['trade_patterns']:
        if p['code']==t['code'] and p['date']==t['date'] and abs(p['actual_pct']-t['actual_pct'])<0.01:
            matched = p
            break
    if matched:
        # 从ind_data获取日内高低
        for ind in ind_data['trades']:
            if ind['code']==t['code'] and ind['date']==t['date']:
                dh = ind.get('day_high',0)
                dl = ind.get('day_low',0)
                if dh > dl and dl > 0:
                    buy_pos = (matched['buy_price'] - dl) / (dh - dl)
                    sell_pos = (matched['sell_price'] - dl) / (dh - dl)
                    print(f"  {t['result']:4s} {t['code']} | buy_pos={buy_pos:.2f} sell_pos={sell_pos:.2f} | buy@{matched['buy_price']} range=[{dl}-{dh}]")
                break
