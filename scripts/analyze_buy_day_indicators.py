#!/usr/bin/env python3
"""分析每笔买入时的股票各项指标 — 修复版，兼容实际DB字段"""
import json
import sqlite3
from collections import defaultdict

TRADE_PATH = "scripts/buy_performance_analysis.json"
DB_PATH = "simple_trade/data/trade.db"
OUT_PATH = "scripts/buy_day_indicators.json"

with open(TRADE_PATH, 'r', encoding='utf-8') as f:
    perf_data = json.load(f)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

win_ind = defaultdict(list)
loss_ind = defaultdict(list)
trades_out = []

for trade in perf_data.get('trade_patterns', []):
    code = trade['code']
    buy_date = trade['date']
    buy_price = trade['buy_price']
    
    ind = {
        'code': code, 'name': trade['stock_name'], 'date': buy_date,
        'buy_price': buy_price, 'result': trade['result'],
        'actual_pct': trade['actual_pct'], 'potential_pct': trade['potential_pct'],
        'hold_minutes': trade['hold_minutes'],
    }
    
    try:
        # 当日K线
        cur.execute("""
            SELECT open_price, close_price, high_price, low_price, 
                   volume, turnover, turnover_rate
            FROM kline_data WHERE stock_code=? AND date(time_key)=? LIMIT 1
        """, (code, buy_date))
        dk = cur.fetchone()
        if dk:
            dk = dict(dk)
            ind['day_open'] = dk['open_price']
            ind['day_close'] = dk['close_price']
            ind['day_high'] = dk['high_price']
            ind['day_low'] = dk['low_price']
            ind['day_volume'] = dk['volume']
            ind['day_turnover'] = dk['turnover']
            ind['day_turnover_rate'] = dk.get('turnover_rate', 0)
            if dk['low_price'] and dk['low_price'] > 0:
                ind['day_amplitude'] = round((dk['high_price'] - dk['low_price']) / dk['low_price'] * 100, 2)

        # 前20日K线
        cur.execute("""
            SELECT open_price, close_price, high_price, low_price, 
                   volume, turnover, turnover_rate
            FROM kline_data WHERE stock_code=? AND date(time_key)<? 
            ORDER BY time_key DESC LIMIT 20
        """, (code, buy_date))
        prev = [dict(r) for r in cur.fetchall()]
        
        if prev:
            # 前日涨跌幅
            if len(prev) >= 2 and prev[1]['close_price'] and prev[1]['close_price'] > 0:
                ind['prev_day_change'] = round(
                    (prev[0]['close_price'] - prev[1]['close_price']) / prev[1]['close_price'] * 100, 2)
            
            # 买入日涨跌幅（相对前收）
            if prev[0]['close_price'] and prev[0]['close_price'] > 0 and dk:
                ind['buy_day_change'] = round(
                    (dk['close_price'] - prev[0]['close_price']) / prev[0]['close_price'] * 100, 2)
                # 买入时的涨跌幅（买入价 vs 前收）
                ind['buy_price_vs_prev_close'] = round(
                    (buy_price - prev[0]['close_price']) / prev[0]['close_price'] * 100, 2)
            
            # 5日均量比
            v5 = [k['volume'] for k in prev[:5] if k['volume'] and k['volume'] > 0]
            if v5:
                avg_v5 = sum(v5) / len(v5)
                ind['avg_vol_5d'] = round(avg_v5)
                if dk and dk['volume'] and avg_v5 > 0:
                    ind['vol_ratio'] = round(dk['volume'] / avg_v5, 2)
            
            # 5日均成交额
            t5 = [k['turnover'] for k in prev[:5] if k['turnover'] and k['turnover'] > 0]
            if t5:
                ind['avg_turnover_5d'] = round(sum(t5) / len(t5))
            
            # ATR(20) — 真实波幅
            trs = []
            for i in range(len(prev)):
                h = prev[i]['high_price'] or 0
                l = prev[i]['low_price'] or 0
                if h > 0 and l > 0:
                    tr = h - l
                    if i < len(prev) - 1:
                        pc = prev[i+1]['close_price'] or 0
                        if pc > 0:
                            tr = max(h - l, abs(h - pc), abs(l - pc))
                    trs.append(tr)
            if trs:
                atr = sum(trs) / len(trs)
                ind['atr'] = round(atr, 3)
                if buy_price > 0:
                    ind['atr_pct'] = round(atr / buy_price * 100, 2)
            
            # K线20日位置 (0=最低, 1=最高)
            hs = [k['high_price'] for k in prev[:20] if k['high_price'] and k['high_price'] > 0]
            ls = [k['low_price'] for k in prev[:20] if k['low_price'] and k['low_price'] > 0]
            if hs and ls:
                h20, l20 = max(hs), min(ls)
                if h20 > l20 and buy_price > 0:
                    ind['kline_pos_20d'] = round((buy_price - l20) / (h20 - l20), 3)
            
            # 近5日累计涨跌幅
            if len(prev) >= 5 and prev[4]['close_price'] and prev[4]['close_price'] > 0:
                ind['change_5d'] = round(
                    (prev[0]['close_price'] - prev[4]['close_price']) / prev[4]['close_price'] * 100, 2)
            
            # 近10日上涨天数 / 下跌天数
            up = 0; down = 0
            for i in range(min(10, len(prev)-1)):
                if prev[i]['close_price'] and prev[i+1]['close_price']:
                    if prev[i]['close_price'] > prev[i+1]['close_price']:
                        up += 1
                    elif prev[i]['close_price'] < prev[i+1]['close_price']:
                        down += 1
            ind['up_days_10'] = up
            ind['down_days_10'] = down
            
            # 5日平均换手率
            tr5 = [k['turnover_rate'] for k in prev[:5] if k.get('turnover_rate') and k['turnover_rate'] > 0]
            if tr5:
                ind['avg_turnover_rate_5d'] = round(sum(tr5) / len(tr5), 2)
        
        # 资金流
        cur.execute("""
            SELECT net_inflow, net_inflow_ratio FROM capital_flow_daily 
            WHERE stock_code=? AND date=? LIMIT 1
        """, (code, buy_date))
        flow = cur.fetchone()
        if flow:
            fd = dict(flow)
            ind['flow_net_inflow'] = fd.get('net_inflow', 0)
            ind['flow_ratio'] = fd.get('net_inflow_ratio', 0)
        
        # 前3日连续资金净流入天数
        cur.execute("""
            SELECT net_inflow FROM capital_flow_daily 
            WHERE stock_code=? AND date<? ORDER BY date DESC LIMIT 5
        """, (code, buy_date))
        pflows = cur.fetchall()
        if pflows:
            cons = 0
            for pf in pflows:
                if dict(pf).get('net_inflow', 0) > 0:
                    cons += 1
                else:
                    break
            ind['consec_inflow_days'] = cons
    
    except Exception as e:
        ind['error'] = str(e)
    
    trades_out.append(ind)
    
    # 分组
    bucket = win_ind if trade['result'] == 'WIN' else loss_ind
    for key in ['day_amplitude', 'day_turnover_rate', 'vol_ratio', 'atr_pct',
                'kline_pos_20d', 'prev_day_change', 'buy_day_change',
                'buy_price_vs_prev_close', 'up_days_10', 'down_days_10',
                'change_5d', 'avg_turnover_rate_5d', 'hold_minutes',
                'flow_ratio', 'consec_inflow_days']:
        v = ind.get(key)
        if v is not None:
            bucket[key].append(v)

# 对比
comp = {}
for key in sorted(set(list(win_ind.keys()) + list(loss_ind.keys()))):
    w = win_ind.get(key, [])
    l = loss_ind.get(key, [])
    if w and l:
        wa = sum(w)/len(w)
        la = sum(l)/len(l)
        comp[key] = {
            'win_avg': round(wa, 3), 'win_median': round(sorted(w)[len(w)//2], 3), 'win_n': len(w),
            'loss_avg': round(la, 3), 'loss_median': round(sorted(l)[len(l)//2], 3), 'loss_n': len(l),
            'diff': round(wa - la, 3),
        }

result = {'trades': trades_out, 'comparison': comp}

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"Done. {len(trades_out)} trades.")
