#!/usr/bin/env python3
"""F方案细化优化回测"""
import sqlite3, os
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), '..', 'simple_trade', 'data', 'trade.db')
OUT = os.path.join(os.path.dirname(__file__), 'backtest_f_optimize.md')

CONFIGS = [
    {'name': 'F0: 基线(SL-10%,LB12,T5)', 'sl': -10, 'tc': 5, 'mh': 20, 'lb': 12},
    {'name': 'F1: 更宽止损(SL-12%)', 'sl': -12, 'tc': 5, 'mh': 20, 'lb': 12},
    {'name': 'F2: 长窗口高抛(LB20)', 'sl': -10, 'tc': 5, 'mh': 20, 'lb': 20},
    {'name': 'F3: 宽止损+长窗口(SL-12%,LB20)', 'sl': -12, 'tc': 5, 'mh': 20, 'lb': 20},
    {'name': 'F4: 短验证(T3)', 'sl': -10, 'tc': 3, 'mh': 20, 'lb': 12},
    {'name': 'F5: 长持有(MH30)', 'sl': -10, 'tc': 5, 'mh': 30, 'lb': 12},
    {'name': 'F6: 最佳组合(SL-12%,LB20,MH30)', 'sl': -12, 'tc': 5, 'mh': 30, 'lb': 20},
    {'name': 'F7: 激进(SL-8%,LB12,T3)', 'sl': -8, 'tc': 3, 'mh': 20, 'lb': 12},
]

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

def run_one(conn, signals, cfg):
    c = conn.cursor()
    trades = []
    sl, tc, mh, lb = cfg['sl'], cfg['tc'], cfg['mh'], cfg['lb']
    for sig in signals:
        code, buy_date = sig['code'], sig['date']
        c.execute("SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover "
                  "FROM kline_data WHERE stock_code=? AND DATE(time_key)=DATE(?) LIMIT 1", (code, buy_date))
        d0 = c.fetchone()
        if not d0 or not d0[1] or not d0[2] or d0[2] <= d0[1]: continue  # 阳线确认
        c.execute("SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover "
                  "FROM kline_data WHERE stock_code=? AND DATE(time_key)>DATE(?) ORDER BY time_key LIMIT ?",
                  (code, buy_date, mh + 5))
        future = c.fetchall()
        if not future: continue
        buy_price = future[0][1] or vwap(future[0])
        future = future[1:]
        if not buy_price or len(future) < tc: continue

        sell_price = sell_date = sell_reason = None
        hold_days = 0
        max_price = buy_price  # track peak for potential trailing stop
        for i in range(len(future)):
            hold_days = i + 1
            dv, dc = vwap(future[i]), future[i][2]
            cur = dv or dc or buy_price
            if future[i][3] and future[i][3] > max_price: max_price = future[i][3]
            ret = (cur - buy_price) / buy_price * 100
            if ret <= sl:
                sell_price, sell_date, sell_reason = cur, future[i][0][:10], f'止损({ret:.0f}%)'
                break
            if hold_days == tc:
                up = sum(1 for j in range(tc) if future[j][2] and future[j][1] and future[j][2] > future[j][1])
                if (cur - buy_price)/buy_price*100 < 0 and up < 1:
                    sell_price, sell_date = dc or cur, future[i][0][:10]
                    sell_reason = '趋势未延续'
                    break
            if hold_days > tc and is_high_throw(future, i, lb):
                sell_price, sell_date, sell_reason = dv or cur, future[i][0][:10], '高抛信号'
                break
            if hold_days >= mh:
                sell_price, sell_date, sell_reason = cur, future[i][0][:10], '超时'
                break
        if sell_price:
            trades.append({'ret': (sell_price-buy_price)/buy_price*100, 'days': hold_days,
                          'reason': sell_reason.split('(')[0].strip(),
                          'code': sig['code'], 'name': sig['name'],
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

    L = ['# F方案优化回测\n']
    L.append(f'> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 基础: 阳线确认+T+1开盘买入\n')
    L.append('## 参数对比\n')
    L.append('| 配置 | 交易数 | 平均收益 | 胜率 | 盈亏比 | 持有天 | 最大盈 | 最大亏 | 高抛占比 | 高抛胜率 |')
    L.append('|------|--------|---------|------|--------|-------|--------|--------|---------|---------|')

    best = None
    all_res = {}
    for cfg in CONFIGS:
        trades = run_one(conn, signals, cfg)
        all_res[cfg['name']] = trades
        if not trades:
            L.append(f"| {cfg['name']} | 0 | - | - | - | - | - | - | - | - |")
            continue
        rets = [t['ret'] for t in trades]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        days = [t['days'] for t in trades]
        aw = sum(wins)/len(wins) if wins else 0
        al = abs(sum(losses)/len(losses)) if losses else 1
        ht = [t for t in trades if t['reason'] == '高抛信号']
        ht_w = len([t for t in ht if t['ret'] > 0])
        avg_ret = sum(rets)/len(rets)
        L.append(f"| {cfg['name']} | {len(trades)} | {avg_ret:+.2f}% | "
                 f"{len(wins)/len(trades)*100:.0f}% | {aw/al:.2f} | {sum(days)/len(days):.1f} | "
                 f"{max(rets):+.1f}% | {min(rets):+.1f}% | "
                 f"{len(ht)/len(trades)*100:.0f}% | {ht_w/len(ht)*100:.0f}% |")
        if best is None or avg_ret > best[1]:
            best = (cfg['name'], avg_ret)

    if best:
        L.append(f'\n> **最佳配置: {best[0]}** (平均收益 {best[1]:+.2f}%)\n')

    # Best config detail
    for cfg_name in [best[0]] if best else []:
        trades = all_res[cfg_name]
        L.append(f'## {cfg_name} 详细\n')
        reasons = {}
        for t in trades:
            reasons.setdefault(t['reason'], []).append(t)
        L.append('| 退出原因 | 数量 | 平均收益 | 胜率 |')
        L.append('|---------|------|---------|------|')
        for rn, grp in sorted(reasons.items()):
            gr = [t['ret'] for t in grp]
            gw = len([r for r in gr if r > 0])
            L.append(f"| {rn} | {len(grp)} | {sum(gr)/len(gr):+.2f}% | {gw/len(grp)*100:.0f}% |")

        L.append('\n| 股票 | 买入日 | 买入价 | 卖出日 | 卖出价 | 天数 | 收益 | 最高涨幅 | 原因 |')
        L.append('|------|--------|--------|--------|--------|------|------|---------|------|')
        for t in sorted(trades, key=lambda x: x['ret'], reverse=True):
            rs = f"+{t['ret']:.1f}%" if t['ret'] >= 0 else f"{t['ret']:.1f}%"
            mr = f"+{t['max_rise']:.1f}%"
            L.append(f"| {t['code']} {t['name']} | {t['buy_date']} | {t['buy_price']:.2f} | "
                     f"{t['sell_date']} | {t['sell_price']:.2f} | {t['days']} | {rs} | {mr} | {t['reason']} |")

    conn.close()
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print(f'Report: {OUT}')

if __name__ == '__main__':
    main()
