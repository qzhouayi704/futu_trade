#!/usr/bin/env python3
"""验证修复后大盘股评分变化"""
import sqlite3, sys
sys.path.insert(0, '.')

db = sqlite3.connect('simple_trade/data/trade.db')

BIG_CAPS = [
    'HK.03690',  # 美团
    'HK.01024',  # 快手
    'HK.09888',  # 百度
    'HK.09999',  # 网易
    'HK.00700',  # 腾讯
    'HK.09618',  # 京东
    'HK.09988',  # 阿里
    'HK.03888',  # 金山软件
    'HK.01810',  # 小米
    'HK.02015',  # 理想
    'HK.09868',  # 小鹏
    'HK.00981',  # 中芯
]

from simple_trade.services.strategy.stock_scorer import StockScorer, PASSING_SCORE
from simple_trade.services.analysis.overnight_screener import OvernightScreener

scorer = StockScorer()
screener = OvernightScreener(db_manager=None)

print(f'TREND及格线: {PASSING_SCORE}')
print('=' * 130)
print(f'{"股票":<16} {"名称":<8} {"旧TREND":<8} {"新TREND":<8} {"量比旧":<8} {"量比新":<10} {"资金加分":<8} {"新总分":<8} {"结论"}')
print('-' * 130)

for code in BIG_CAPS:
    name_row = db.execute('SELECT name FROM stocks WHERE code=?', (code,)).fetchone()
    name = name_row[0] if name_row else code

    klines_raw = db.execute(
        'SELECT time_key, close_price, open_price, high_price, low_price, volume '
        'FROM kline_data WHERE stock_code=? ORDER BY time_key DESC LIMIT 25',
        (code,)
    ).fetchall()

    if len(klines_raw) < 2:
        print(f'{code:<16} {name:<8} 无K线')
        continue

    # 转成dict格式 (正序)
    cols = ['time_key', 'close_price', 'open_price', 'high_price', 'low_price', 'volume']
    klines = [dict(zip(cols, r)) for r in reversed(klines_raw)]

    last_close = klines[-1]['close_price']
    prev_close = klines[-2]['close_price']
    chg = (last_close - prev_close) / prev_close * 100

    stock = {
        'code': code, 'name': name, 'last_price': last_close,
        'change_rate': chg,
        'high_price': klines[-1]['high_price'],
        'low_price': klines[-1]['low_price'],
        'volume_ratio': 0,  # K线模式无量比
        'turnover_rate': 0,
        'amplitude': 0,
    }

    # 旧模式: vol_ratio=None
    old_indicators = {}
    high = klines[-1]['high_price'] or 0
    low = klines[-1]['low_price'] or 0
    if high > 0 and low > 0 and last_close > 0:
        old_indicators['day_amplitude'] = (high - low) / last_close * 100
    old_indicators['vol_ratio'] = None  # 旧: 无数据

    cap = db.execute(
        'SELECT net_inflow_ratio, capital_score, main_net_inflow '
        'FROM capital_flow_cache WHERE stock_code=? ORDER BY timestamp DESC LIMIT 1',
        (code,)
    ).fetchone()
    old_indicators['ticker_power'] = cap[0] if cap else None
    old_indicators['today_change'] = chg

    closes = [k['close_price'] for k in klines if k.get('close_price', 0) > 0]
    if len(closes) >= 2:
        old_indicators['prev_day_change'] = (closes[-1] - closes[-2]) / closes[-2] * 100
    if len(closes) >= 6:
        old_indicators['change_5d'] = (closes[-1] - closes[-6]) / closes[-6] * 100
    if len(klines) >= 10:
        hs = [k['high_price'] for k in klines[-20:] if k.get('high_price')]
        ls = [k['low_price'] for k in klines[-20:] if k.get('low_price')]
        if hs and ls:
            mh, ml = max(hs), min(ls)
            if mh > ml:
                old_indicators['kline_pos_20d'] = (last_close - ml) / (mh - ml)

    old_score, _ = scorer._score_trend(old_indicators)

    # 新模式: vol_ratio从K线计算(仅>=1.5时填入)
    new_indicators = dict(old_indicators)
    calc_vr = None
    if len(klines) >= 6:
        today_vol = klines[-1].get('volume', 0) or 0
        prev_vols = [k['volume'] for k in klines[-6:-1] if k.get('volume', 0) > 0]
        if today_vol > 0 and prev_vols:
            avg_vol = sum(prev_vols) / len(prev_vols)
            if avg_vol > 0:
                calc_vr = round(today_vol / avg_vol, 2)
                if calc_vr >= 1.5:
                    new_indicators['vol_ratio'] = calc_vr

    new_score, new_details = scorer._score_trend(new_indicators)

    vol_old = 'None→12'
    vol_new_val = new_indicators.get('vol_ratio')
    vol_new_detail = next((d for d in new_details if d.dimension == '量比'), None)
    if vol_new_val and vol_new_detail:
        vol_new = f'{vol_new_val:.1f}→{vol_new_detail.score}'
    elif calc_vr:
        vol_new = f'({calc_vr:.1f})<1.5→12'
    else:
        vol_new = 'None→12'

    # 资金加分
    cap_bonus = 0
    cap_score = cap[1] if cap else 50
    main_inflow = cap[2] if cap else 0
    if cap_score >= 85 and main_inflow > 0:
        cap_bonus = 15
    elif cap_score >= 70 and main_inflow > 0:
        cap_bonus = 10

    # 连续天数加分
    daily = db.execute(
        'SELECT net_inflow FROM capital_flow_daily WHERE stock_code=? ORDER BY date DESC LIMIT 10',
        (code,)
    ).fetchall()
    cont_days = 0
    for r in daily:
        if r[0] and r[0] > 0:
            cont_days += 1
        else:
            break
    day_bonus = 15 if cont_days >= 5 else (10 if cont_days >= 3 else (5 if cont_days >= 2 else 0))

    total_new = new_score + day_bonus + cap_bonus
    passed_old = old_score >= PASSING_SCORE
    passed_new = new_score >= PASSING_SCORE

    if not passed_old and passed_new:
        conclusion = f'✅ 修复! {old_score}→{total_new}'
    elif passed_old and passed_new:
        conclusion = f'✅ 提升 {old_score}→{total_new}'
    elif not passed_new:
        conclusion = f'❌ 仍不及格({new_score})'
    else:
        conclusion = f'→ {total_new}'

    print(f'{code:<16} {name:<8} {old_score:<8.0f} {new_score:<8.0f} {vol_old:<8} {vol_new:<10} {cap_bonus:<+8} {total_new:<8.0f} {conclusion}')

db.close()
