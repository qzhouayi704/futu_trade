#!/usr/bin/env python3
"""
回测 v3: 扩大数据范围
- 用 kline_data 表中所有284只股票的历史K线
- 每个交易日对每只股票跑3策略评分
- 只取评分>=55的高分股票模拟交易
- 覆盖 2026-04-01 ~ 2026-05-16 (留最后3天做卖出窗口)
"""
import sqlite3, sys, json
from collections import defaultdict
from datetime import datetime, timedelta
sys.path.insert(0, '/opt/futu_trade_sys')

DB_PATH = '/opt/futu_trade_sys/simple_trade/data/trade.db'
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row

from simple_trade.services.strategy.stock_scorer import StockScorer
scorer = StockScorer()

# Trade parameters per mode (v2 - REVERSAL tightened)
TRADE_PARAMS = {
    'TREND':    {'stop_loss': 0.08, 'trail_activate': 0.10, 'trail_callback': 0.03, 'max_days': 3,  'buy_dip': 0.01},
    'REVERSAL': {'stop_loss': 0.12, 'trail_activate': 0.08, 'trail_callback': 0.05, 'max_days': 5,  'buy_dip': 0.00},
    'BREAKOUT': {'stop_loss': 0.08, 'trail_activate': 0.10, 'trail_callback': 0.03, 'max_days': 5,  'buy_dip': 0.00},
}

MIN_SCORE = 55  # 最低评分门槛


def simulate_trade(buy_price, klines_after, params):
    sl = params['stop_loss']
    trail_act = params['trail_activate']
    trail_cb = params['trail_callback']
    max_days = params['max_days']
    max_high = buy_price
    trail_active = False
    for i, k in enumerate(klines_after):
        day = i + 1
        low = k['low_price'] or buy_price
        high = k['high_price'] or buy_price
        close = k['close_price'] or buy_price
        if low <= buy_price * (1 - sl):
            return buy_price * (1 - sl), '止损', day
        if high > max_high:
            max_high = high
        if max_high >= buy_price * (1 + trail_act):
            trail_active = True
        if trail_active:
            trail_stop = max_high * (1 - trail_cb)
            if low <= trail_stop:
                return trail_stop, '追踪止盈', day
        if day >= max_days:
            return close, '到期卖出', day
    if klines_after:
        return klines_after[-1]['close_price'], '数据截止', len(klines_after)
    return buy_price, '无数据', 0


# 1. Load all kline data into memory
print("=== Loading kline data ===")
all_klines = db.execute("""
    SELECT stock_code, time_key, open_price, high_price, low_price, close_price, volume, turnover_rate
    FROM kline_data ORDER BY stock_code, time_key
""").fetchall()
print(f"Total kline rows: {len(all_klines)}")

# Group by stock
stock_klines = defaultdict(list)
for k in all_klines:
    stock_klines[k['stock_code']].append(dict(k))

# Get stock names
stock_names = {}
try:
    for r in db.execute("SELECT code, name FROM stocks"):
        stock_names[r['code']] = r['name']
except:
    pass

# Capital flow data
cf_cache = {}
for r in db.execute("SELECT stock_code, net_inflow_ratio, big_order_buy_ratio FROM capital_flow_cache"):
    cf_cache[r['stock_code']] = dict(r)

cf_daily_data = defaultdict(list)
for r in db.execute("SELECT stock_code, date, net_inflow FROM capital_flow_daily ORDER BY stock_code, date DESC"):
    cf_daily_data[r['stock_code']].append(dict(r))

# 2. Get all unique trading dates
all_dates = sorted(set(k['time_key'][:10] for k in all_klines))
print(f"Trading dates: {len(all_dates)}, range: {all_dates[0]} ~ {all_dates[-1]}")

# Use dates from April 2026 onwards, leave last 5 days for exit
start_date = '2026-04-01'
end_date_idx = len(all_dates) - 6  # leave 5+1 days for max hold
screen_dates = [d for i, d in enumerate(all_dates) if d >= start_date and i <= end_date_idx]
print(f"Screening dates: {len(screen_dates)} ({screen_dates[0]} ~ {screen_dates[-1]})")

# 3. For each date, score all stocks
results = []
total_scored = 0

for sd in screen_dates:
    sd_idx = all_dates.index(sd)

    for code, klines in stock_klines.items():
        # Find klines up to this date
        hist = [k for k in klines if k['time_key'][:10] <= sd]
        if len(hist) < 6:
            continue

        today = hist[-1]
        if today['time_key'][:10] != sd:
            continue  # no trading on this date for this stock

        today_close = today['close_price'] or 0
        prev_close = hist[-2]['close_price'] or 0
        if today_close <= 0 or prev_close <= 0:
            continue

        # Build indicators
        c_5d = hist[-6]['close_price'] or 0
        change_5d = round((today_close - c_5d) / c_5d * 100, 2) if c_5d else 0

        recent = hist[-min(20, len(hist)):]
        h_val = max(r['high_price'] or 0 for r in recent)
        l_val = min(r['low_price'] or 9999 for r in recent)
        kline_pos = round((today_close - l_val) / (h_val - l_val), 4) if h_val != l_val else 0.5

        c_p2 = hist[-3]['close_price'] if len(hist) >= 3 else 0
        c_p2 = c_p2 or 0
        prev_day_change = round((prev_close - c_p2) / c_p2 * 100, 2) if c_p2 else 0

        prev5_vols = [r['volume'] or 0 for r in hist[-6:-1]]
        avg_vol = sum(prev5_vols) / len(prev5_vols) if prev5_vols else 1
        vol_ratio = round((today['volume'] or 0) / avg_vol, 2) if avg_vol > 0 else 0

        amp = round(((today['high_price'] or 0) - (today['low_price'] or 0)) / today_close * 100, 2) if today_close else 0

        low_20d = min(r['low_price'] or 9999 for r in hist[:-1][-20:])
        rise_from_low = round((today_close - low_20d) / low_20d * 100, 2) if low_20d > 0 else 0
        today_change = round((today_close - prev_close) / prev_close * 100, 2)

        # Breakout
        prev_bars = hist[:-1]
        h5 = max(r['high_price'] or 0 for r in prev_bars[-5:]) if len(prev_bars) >= 5 else 0
        h10 = max(r['high_price'] or 0 for r in prev_bars[-10:]) if len(prev_bars) >= 10 else 0
        h20 = max(r['high_price'] or 0 for r in prev_bars[-20:]) if len(prev_bars) >= 20 else 0
        rc = [r['close_price'] or 0 for r in prev_bars[-3:]]
        def _broken(res): return res > 0 and today_close > res and any(cc <= res for cc in rc)
        bl, bp = '', 0
        if _broken(h20): bl, bp = '20日高', (today_close - h20) / h20 * 100
        elif _broken(h10): bl, bp = '10日高', (today_close - h10) / h10 * 100
        elif _broken(h5): bl, bp = '5日高', (today_close - h5) / h5 * 100

        # Capital
        cf = cf_cache.get(code)
        cf_d = cf_daily_data.get(code, [])
        cont = 0
        for r in cf_d:
            if r['date'] <= sd and r['net_inflow'] and r['net_inflow'] > 0:
                cont += 1
            elif r['date'] <= sd:
                break

        indicators = {
            'change_5d': change_5d, 'kline_pos_20d': kline_pos, 'day_amplitude': amp,
            'vol_ratio': vol_ratio, 'prev_day_change': prev_day_change, 'ticker_power': None,
            'rise_from_low': rise_from_low, 'today_change': today_change,
            'breakout_level': bl, 'breakout_pct': round(bp, 2) if bl else None,
            'net_inflow_ratio': cf['net_inflow_ratio'] if cf else None,
            'big_order_buy_ratio': cf['big_order_buy_ratio'] if cf else None,
            'capital_continuity_days': cont, 'change_pct': today_change,
        }

        all_scores = scorer.score_all_strategies(code, stock_names.get(code, ''), indicators)
        best = all_scores['best']
        total_scored += 1

        if best.total_score < MIN_SCORE:
            continue

        params = TRADE_PARAMS.get(best.mode, TRADE_PARAMS['TREND'])

        # Future klines for trade simulation
        future = [k for k in klines if k['time_key'][:10] > sd][:params['max_days'] + 1]
        if not future:
            continue

        t1 = future[0]
        t1_open = t1['open_price'] or 0
        t1_low = t1['low_price'] or 0
        if t1_open <= 0:
            continue

        # Buy price
        if params['buy_dip'] > 0:
            dip_price = round(today_close * (1 - params['buy_dip']), 2)
            if t1_low <= dip_price:
                buy_price, buy_method = dip_price, '低吸'
            else:
                buy_price, buy_method = t1_open, '开盘(低吸未成交)'
        else:
            buy_price, buy_method = t1_open, '开盘'

        sell_price, sell_reason, hold_days = simulate_trade(buy_price, future, params)
        trade_return = round((sell_price - buy_price) / buy_price * 100, 2)

        results.append({
            'date': sd, 'code': code, 'name': stock_names.get(code, ''),
            'mode': best.mode, 'score': best.total_score,
            'trend': all_scores['trend'].total_score,
            'reversal': all_scores['reversal'].total_score,
            'breakout': all_scores['breakout'].total_score if all_scores['breakout_triggered'] else None,
            'buy_price': buy_price, 'buy_method': buy_method,
            'sell_price': round(sell_price, 2), 'sell_reason': sell_reason,
            'hold_days': hold_days, 'ret': trade_return,
        })

db.close()

# 4. Analysis
# Exclude "数据截止" trades
valid = [r for r in results if r['sell_reason'] != '数据截止']
all_trades = results

print(f"\n{'='*60}")
print(f"  评分>=55的交易总数: {len(all_trades)}笔 (日均{len(all_trades)/max(len(screen_dates),1):.0f}只)")
print(f"  有效交易(排除数据截止): {len(valid)}笔")
if valid:
    avg = sum(r['ret'] for r in valid) / len(valid)
    wr = sum(1 for r in valid if r['ret'] > 0) / len(valid)
    ah = sum(r['hold_days'] for r in valid) / len(valid)
    print(f"  收益: {avg:+.2f}%  胜率: {wr:.1%}  平均持仓: {ah:.1f}天")
print(f"{'='*60}")

if not valid:
    print("No valid trades!"); sys.exit(0)

# By mode
print(f"\n--- 按策略模式 ---")
for mode in ['TREND', 'REVERSAL', 'BREAKOUT']:
    ms = [r for r in valid if r['mode'] == mode]
    if ms:
        a = sum(r['ret'] for r in ms) / len(ms)
        w = sum(1 for r in ms if r['ret'] > 0) / len(ms)
        h = sum(r['hold_days'] for r in ms) / len(ms)
        # Profit factor
        gains = sum(r['ret'] for r in ms if r['ret'] > 0)
        losses = abs(sum(r['ret'] for r in ms if r['ret'] < 0))
        pf = round(gains / losses, 2) if losses > 0 else 999
        print(f"  {mode:10s}: {len(ms):4d}笔, 收益 {a:+.2f}%, 胜率 {w:.1%}, 持仓 {h:.1f}天, PF={pf}")

# By score band
print(f"\n--- 按评分段 ---")
bands = [(55, 60), (60, 65), (65, 70), (70, 75), (75, 80), (80, 85), (85, 101)]
for lo, hi in bands:
    band = [r for r in valid if lo <= r['score'] < hi]
    if band:
        a = sum(r['ret'] for r in band) / len(band)
        w = sum(1 for r in band if r['ret'] > 0) / len(band)
        print(f"  {lo}-{hi:3d}: {len(band):4d}笔, 收益 {a:+.2f}%, 胜率 {w:.1%}")

# By sell reason
print(f"\n--- 按卖出原因 ---")
for reason in ['止损', '追踪止盈', '到期卖出']:
    rs = [r for r in valid if r['sell_reason'] == reason]
    if rs:
        a = sum(r['ret'] for r in rs) / len(rs)
        print(f"  {reason:6s}: {len(rs):4d}笔, 平均收益 {a:+.2f}%")

# By buy method
print(f"\n--- 按买入方式 ---")
for method in ['低吸', '开盘(低吸未成交)', '开盘']:
    ms = [r for r in valid if r['buy_method'] == method]
    if ms:
        a = sum(r['ret'] for r in ms) / len(ms)
        w = sum(1 for r in ms if r['ret'] > 0) / len(ms)
        print(f"  {method:18s}: {len(ms):4d}笔, 收益 {a:+.2f}%, 胜率 {w:.1%}")

# Breakout triggered
print(f"\n--- 突破触发 ---")
bo = [r for r in valid if r['breakout'] is not None]
nbo = [r for r in valid if r['breakout'] is None]
if bo:
    a = sum(r['ret'] for r in bo) / len(bo)
    w = sum(1 for r in bo if r['ret'] > 0) / len(bo)
    print(f"  触发: {len(bo):4d}笔, 收益 {a:+.2f}%, 胜率 {w:.1%}")
if nbo:
    a = sum(r['ret'] for r in nbo) / len(nbo)
    w = sum(1 for r in nbo if r['ret'] > 0) / len(nbo)
    print(f"  未触发: {len(nbo):4d}笔, 收益 {a:+.2f}%, 胜率 {w:.1%}")

# Weekly breakdown
print(f"\n--- 按周 ---")
week_trades = defaultdict(list)
for r in valid:
    # ISO week
    dt = datetime.strptime(r['date'], '%Y-%m-%d')
    wk = dt.strftime('%Y-W%W')
    week_trades[wk].append(r)
for wk in sorted(week_trades):
    ts = week_trades[wk]
    a = sum(r['ret'] for r in ts) / len(ts)
    w = sum(1 for r in ts if r['ret'] > 0) / len(ts)
    print(f"  {wk}: {len(ts):4d}笔, 收益 {a:+.2f}%, 胜率 {w:.1%}")

# Best combination: mode + score range
print(f"\n--- 最佳组合 (模式+评分段) ---")
for mode in ['TREND', 'REVERSAL', 'BREAKOUT']:
    for lo, hi in [(55,65), (65,75), (75,85), (85,101)]:
        combo = [r for r in valid if r['mode'] == mode and lo <= r['score'] < hi]
        if len(combo) >= 5:
            a = sum(r['ret'] for r in combo) / len(combo)
            w = sum(1 for r in combo if r['ret'] > 0) / len(combo)
            gains = sum(r['ret'] for r in combo if r['ret'] > 0)
            losses = abs(sum(r['ret'] for r in combo if r['ret'] < 0))
            pf = round(gains / losses, 2) if losses > 0 else 999
            print(f"  {mode:10s} {lo}-{hi:3d}: {len(combo):4d}笔, 收益 {a:+.2f}%, 胜率 {w:.1%}, PF={pf}")

print(f"\n回测完成! 总评分次数: {total_scored}")
