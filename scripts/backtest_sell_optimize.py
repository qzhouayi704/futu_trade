#!/usr/bin/env python3
"""高抛时机优化对比"""
import sqlite3, os
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), '..', 'simple_trade', 'data', 'trade.db')
OUT = os.path.join(os.path.dirname(__file__), 'backtest_sell_optimize.md')

# 卖出策略类型
SELL_MODES = [
    {'name': 'S0: 原始高抛(LB12)', 'mode': 'highthrow', 'lb': 12},
    {'name': 'S1: 追踪止盈(回撤3%)', 'mode': 'trailing', 'trail_pct': 3, 'activate_pct': 5},
    {'name': 'S2: 追踪止盈(回撤5%)', 'mode': 'trailing', 'trail_pct': 5, 'activate_pct': 5},
    {'name': 'S3: 连续2阴线卖', 'mode': 'consecutive_bear', 'count': 2, 'min_profit': 3},
    {'name': 'S4: 高抛+最低利润5%', 'mode': 'highthrow_min', 'lb': 12, 'min_profit': 5},
    {'name': 'S5: 追踪3%+激活8%', 'mode': 'trailing', 'trail_pct': 3, 'activate_pct': 8},
    {'name': 'S6: 追踪5%+激活10%', 'mode': 'trailing', 'trail_pct': 5, 'activate_pct': 10},
]

SL, TC, MH = -10, 5, 30  # 固定: 止损-10%, T5验证, 最大30天

def vwap(row):
    if not row: return None
    v, t = row[5], row[6]
    if v and v > 0 and t and t > 0: return t / v
    ps = [p for p in row[1:5] if p]
    return sum(ps)/len(ps) if ps else None

def is_high_throw(klines, idx, lb):
    if idx < 1 or idx >= len(klines): return False
    th, yh = klines[idx][3], klines[idx-1][3]
    if not th or not yh or th >= yh: return False
    start = max(0, idx - lb)
    highs = [klines[i][3] for i in range(start, idx) if klines[i][3]]
    return yh == max(highs) if highs else False

def check_sell(future, i, buy_price, max_price, cfg):
    """检查是否触发卖出信号, 返回 (triggered, price, reason)"""
    mode = cfg['mode']
    dv, dc = vwap(future[i]), future[i][2]
    cur = dv or dc or buy_price
    ret = (cur - buy_price) / buy_price * 100
    peak_ret = (max_price - buy_price) / buy_price * 100
    drawdown = (max_price - cur) / max_price * 100 if max_price > 0 else 0

    if mode == 'highthrow':
        if is_high_throw(future, i, cfg['lb']):
            return True, dv or cur, '高抛信号'
    elif mode == 'highthrow_min':
        if is_high_throw(future, i, cfg['lb']) and ret >= cfg['min_profit']:
            return True, dv or cur, f'高抛(利润{ret:.0f}%)'
    elif mode == 'trailing':
        act = cfg['activate_pct']
        trail = cfg['trail_pct']
        if peak_ret >= act and drawdown >= trail:
            return True, dv or cur, f'追踪止盈(峰值{peak_ret:.0f}%,回撤{drawdown:.0f}%)'
    elif mode == 'consecutive_bear':
        cnt = cfg['count']
        mp = cfg.get('min_profit', 0)
        if i >= cnt - 1 and ret >= mp:
            bears = all(future[i-j][2] < future[i-j][1] for j in range(cnt)
                       if future[i-j][2] and future[i-j][1])
            if bears:
                return True, dv or cur, f'{cnt}连阴卖出'
    return False, None, None

def run_one(conn, signals, sell_cfg):
    c = conn.cursor()
    trades = []
    for sig in signals:
        code, buy_date = sig['code'], sig['date']
        c.execute("SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover "
                  "FROM kline_data WHERE stock_code=? AND DATE(time_key)=DATE(?) LIMIT 1", (code, buy_date))
        d0 = c.fetchone()
        if not d0 or not d0[1] or not d0[2] or d0[2] <= d0[1]: continue
        c.execute("SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover "
                  "FROM kline_data WHERE stock_code=? AND DATE(time_key)>DATE(?) ORDER BY time_key LIMIT ?",
                  (code, buy_date, MH + 5))
        future = c.fetchall()
        if not future: continue
        buy_price = future[0][1] or vwap(future[0])
        future = future[1:]
        if not buy_price or len(future) < TC: continue

        sell_price = sell_date = sell_reason = None
        hold_days = 0
        max_price = buy_price
        for i in range(len(future)):
            hold_days = i + 1
            dv, dc = vwap(future[i]), future[i][2]
            cur = dv or dc or buy_price
            if future[i][3] and future[i][3] > max_price: max_price = future[i][3]
            ret = (cur - buy_price) / buy_price * 100
            # 止损
            if ret <= SL:
                sell_price, sell_date, sell_reason = cur, future[i][0][:10], '止损'
                break
            # T验证
            if hold_days == TC:
                up = sum(1 for j in range(TC) if future[j][2] and future[j][1] and future[j][2] > future[j][1])
                if ret < 0 and up < 1:
                    sell_price, sell_date, sell_reason = dc or cur, future[i][0][:10], '趋势未延续'
                    break
            # 卖出策略
            if hold_days > TC:
                triggered, sp, sr = check_sell(future, i, buy_price, max_price, sell_cfg)
                if triggered:
                    sell_price, sell_date, sell_reason = sp, future[i][0][:10], sr
                    break
            if hold_days >= MH:
                sell_price, sell_date, sell_reason = cur, future[i][0][:10], '超时'
                break

        if sell_price:
            trades.append({'ret': (sell_price-buy_price)/buy_price*100, 'days': hold_days,
                          'reason': sell_reason, 'code': sig['code'], 'name': sig['name'],
                          'buy_date': buy_date, 'buy_price': buy_price,
                          'sell_date': sell_date, 'sell_price': sell_price,
                          'max_rise': (max_price-buy_price)/buy_price*100})
    return trades

def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""SELECT ts.id, s.code, s.name, ts.signal_price, ts.created_at
        FROM trade_signals ts JOIN stocks s ON ts.stock_id = s.id
        WHERE ts.signal_type='BUY' AND (ts.strategy_name='趋势反转策略' OR ts.strategy_id='trend_reversal')
        ORDER BY ts.created_at DESC""")
    seen, signals = set(), []
    for r in c.fetchall():
        key = (r[1], r[4][:10])
        if key not in seen:
            seen.add(key)
            signals.append({'code':r[1], 'name':r[2], 'price':r[3], 'date':r[4][:10]})

    L = ['# 高抛时机优化对比\n']
    L.append(f'> 固定参数: 阳线确认+T1买入, SL={SL}%, T{TC}验证, 最大持有{MH}天\n')
    L.append('## 卖出策略对比\n')
    L.append('| 策略 | 交易数 | 平均收益 | 胜率 | 盈亏比 | 持有天 | 利润捕获率 |')
    L.append('|------|--------|---------|------|--------|-------|-----------|')

    all_res = {}
    for cfg in SELL_MODES:
        trades = run_one(conn, signals, cfg)
        all_res[cfg['name']] = trades
        if not trades: continue
        rets = [t['ret'] for t in trades]
        maxr = [t['max_rise'] for t in trades]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        days = [t['days'] for t in trades]
        aw = sum(wins)/len(wins) if wins else 0
        al = abs(sum(losses)/len(losses)) if losses else 1
        # 利润捕获率 = 实际收益 / 最高可能收益
        capture = sum(rets) / sum(maxr) * 100 if sum(maxr) > 0 else 0
        L.append(f"| {cfg['name']} | {len(trades)} | {sum(rets)/len(rets):+.2f}% | "
                 f"{len(wins)/len(trades)*100:.0f}% | {aw/al:.2f} | {sum(days)/len(days):.1f} | {capture:.0f}% |")

    # Detail for top 3
    ranked = sorted(all_res.items(), key=lambda x: sum(t['ret'] for t in x[1])/max(len(x[1]),1) if x[1] else -999, reverse=True)
    for name, trades in ranked[:3]:
        if not trades: continue
        L.append(f'\n### {name}\n')
        L.append('| 股票 | 买入日 | 买入价 | 卖出日 | 卖出价 | 天数 | 收益 | 最高涨幅 | 原因 |')
        L.append('|------|--------|--------|--------|--------|------|------|---------|------|')
        for t in sorted(trades, key=lambda x: x['ret'], reverse=True):
            rs = f"+{t['ret']:.1f}%" if t['ret'] >= 0 else f"{t['ret']:.1f}%"
            L.append(f"| {t['code']} {t['name']} | {t['buy_date']} | {t['buy_price']:.2f} | "
                     f"{t['sell_date']} | {t['sell_price']:.2f} | {t['days']} | {rs} | +{t['max_rise']:.1f}% | {t['reason']} |")

    conn.close()
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print(f'Report: {OUT}')

if __name__ == '__main__':
    main()
