#!/usr/bin/env python3
"""还原关键交易日的5分钟分时走势，标注买卖点位置"""
import json
import sqlite3
from collections import defaultdict

DB_PATH = "simple_trade/data/trade.db"
PERF_PATH = "scripts/buy_performance_analysis.json"
SCORES_PATH = "scripts/scoring_backtest.json"
OUT_PATH = "scripts/intraday_analysis.txt"

perf = json.load(open(PERF_PATH, 'r', encoding='utf-8'))
scores = json.load(open(SCORES_PATH, 'r', encoding='utf-8'))
trades_raw = json.load(open('scripts/futu_real_trades.json', 'r', encoding='utf-8'))

# 收集所有成交记录
all_deals = []
for key in ['today_deals', 'history_deals']:
    if key in trades_raw and isinstance(trades_raw[key], list):
        all_deals.extend(trades_raw[key])

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 选择关键交易日分析
# 从80+分交易+其他代表性交易中选
key_days = [
    ('HK.01384', '2026-05-08', '滴普科技(前日+57%,90分,4W4L)'),
    ('HK.01384', '2026-04-16', '滴普科技(90分WIN+10.8%)'),
    ('HK.00068', '2026-04-28', '群核科技(60分,5笔混合)'),
    ('HK.00068', '2026-04-24', '群核科技(85分WIN+2.7%)'),
    ('HK.02706', '2026-05-12', '海致科技(今日)'),
    ('HK.02656', '2026-04-21', '健康160(低分高频)'),
    ('HK.01879', '2026-04-09', '曦智科技(高胜率标的)'),
]

output = []

for code, date, label in key_days:
    output.append("=" * 100)
    output.append(f"  {label} | {code} {date}")
    output.append("=" * 100)
    
    # 获取5分钟K线
    cur.execute("""
        SELECT time_key, open_price, high_price, low_price, close_price, volume
        FROM kline_5min_data 
        WHERE stock_code=? AND date(time_key)=?
        ORDER BY time_key
    """, (code, date))
    klines = cur.fetchall()
    
    if not klines:
        output.append("  (无5分钟K线数据)")
        output.append("")
        continue
    
    # 获取当天所有成交
    day_deals = [d for d in all_deals 
                 if d.get('code') == code and d.get('create_time', '')[:10] == date]
    day_deals.sort(key=lambda x: x.get('create_time', ''))
    
    # 计算VWAP
    total_vol = 0
    total_turnover = 0
    vwap_series = []
    
    day_high = max(k[2] for k in klines)
    day_low = min(k[3] for k in klines)
    day_open = klines[0][1]
    day_close = klines[-1][4]
    
    output.append(f"  日线: 开{day_open} 高{day_high} 低{day_low} 收{day_close}")
    output.append(f"  振幅: {(day_high-day_low)/day_low*100:.1f}%  涨跌: {(day_close-day_open)/day_open*100:.1f}%")
    output.append("")
    
    # 绘制文字版分时图
    output.append("  时间        开盘   最高   最低   收盘   成交量     走势")
    output.append("  " + "-" * 90)
    
    price_range = day_high - day_low if day_high > day_low else 1
    bar_width = 40
    
    for k in klines:
        time_str = k[0][11:16]  # HH:MM
        o, h, l, c, vol = k[1], k[2], k[3], k[4], k[5]
        
        # 文字版蜡烛
        pos_l = int((l - day_low) / price_range * bar_width)
        pos_h = int((h - day_low) / price_range * bar_width)
        pos_o = int((o - day_low) / price_range * bar_width)
        pos_c = int((c - day_low) / price_range * bar_width)
        
        bar = [' '] * (bar_width + 1)
        # 影线
        for i in range(pos_l, pos_h + 1):
            bar[i] = '|'
        # 实体
        body_start = min(pos_o, pos_c)
        body_end = max(pos_o, pos_c)
        char = '#' if c >= o else 'v'
        for i in range(body_start, body_end + 1):
            bar[i] = char
        
        # 标注买卖点
        markers = []
        for d in day_deals:
            deal_time = d.get('create_time', '')[11:16]
            k_time = k[0][11:16]
            # 判断成交是否在这个5分钟窗口内
            k_start = k[0]
            k_hour, k_min = int(k_time[:2]), int(k_time[3:5])
            d_hour, d_min = int(deal_time[:2]), int(deal_time[3:5])
            d_total = d_hour * 60 + d_min
            k_total = k_hour * 60 + k_min
            if k_total <= d_total < k_total + 5:
                side = d.get('trd_side', '?')
                price = d.get('price', 0)
                qty = d.get('qty', 0)
                emoji = 'B' if side == 'BUY' else 'S'
                markers.append(f"{emoji}@{price}x{int(qty)}")
        
        marker_str = ' '.join(markers) if markers else ''
        vol_k = vol / 1000 if vol else 0
        
        bar_str = ''.join(bar)
        output.append(f"  {time_str} {o:7.2f} {h:7.2f} {l:7.2f} {c:7.2f} {vol_k:8.0f}K  {bar_str}  {marker_str}")
    
    # 买卖点汇总
    output.append("")
    output.append("  买卖明细:")
    buys = [d for d in day_deals if d.get('trd_side') == 'BUY']
    sells = [d for d in day_deals if d.get('trd_side') == 'SELL']
    
    for d in day_deals:
        side = d.get('trd_side', '?')
        price = d.get('price', 0)
        time = d.get('create_time', '')[11:19]
        qty = int(d.get('qty', 0))
        pos_in_day = (price - day_low) / price_range * 100 if price_range > 0 else 0
        marker = 'BUY ' if side == 'BUY' else 'SELL'
        output.append(f"    {marker} {time} @ {price:7.2f} x{qty:4d}  (日内位置: {pos_in_day:.0f}%)")
    
    # 买卖点分析
    if buys and sells:
        avg_buy = sum(d['price'] for d in buys) / len(buys)
        avg_sell = sum(d['price'] for d in sells) / len(sells)
        avg_buy_pos = sum((d['price']-day_low)/price_range*100 for d in buys) / len(buys)
        avg_sell_pos = sum((d['price']-day_low)/price_range*100 for d in sells) / len(sells)
        
        output.append(f"\n  买入均价: {avg_buy:.2f} (日内位置: {avg_buy_pos:.0f}%)")
        output.append(f"  卖出均价: {avg_sell:.2f} (日内位置: {avg_sell_pos:.0f}%)")
        output.append(f"  价差: {avg_sell - avg_buy:+.2f} ({(avg_sell-avg_buy)/avg_buy*100:+.2f}%)")
        
        # 识别买入模式
        buy_times = [d.get('create_time','')[11:16] for d in buys]
        early_buys = sum(1 for t in buy_times if t < '09:45')
        mid_buys = sum(1 for t in buy_times if '09:45' <= t < '10:30')
        late_buys = sum(1 for t in buy_times if t >= '10:30')
        output.append(f"  买入时段: 开盘15min内:{early_buys}笔, 中段:{mid_buys}笔, 后段:{late_buys}笔")
    
    output.append("")

conn.close()

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output))

print(f"Done. Output: {OUT_PATH}")
print(f"Analyzed {len(key_days)} trading days.")
