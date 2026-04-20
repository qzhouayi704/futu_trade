#!/usr/bin/env python3
"""多参数对比回测"""
import sqlite3, os
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), '..', 'simple_trade', 'data', 'trade.db')
OUT = os.path.join(os.path.dirname(__file__), 'backtest_comparison.md')

CONFIGS = [
    {'name': 'A: 基准(SL-5%,T2)', 'stop_loss': -5, 't_check': 2, 'max_hold': 20, 'confirm': False},
    {'name': 'B: 宽止损(SL-10%,T2)', 'stop_loss': -10, 't_check': 2, 'max_hold': 20, 'confirm': False},
    {'name': 'C: 宽止损+长验证(SL-10%,T5)', 'stop_loss': -10, 't_check': 5, 'max_hold': 20, 'confirm': False},
    {'name': 'D: 超宽(SL-15%,T5)', 'stop_loss': -15, 't_check': 5, 'max_hold': 20, 'confirm': False},
    {'name': 'E: 阳线确认+T1买(SL-5%)', 'stop_loss': -5, 't_check': 2, 'max_hold': 20, 'confirm': True},
    {'name': 'F: 阳线确认+宽止损(SL-10%)', 'stop_loss': -10, 't_check': 5, 'max_hold': 20, 'confirm': True},
]
LOOKBACK = 12

def vwap(row):
    if not row: return None
    v, t = row[5], row[6]
    if v and v > 0 and t and t > 0: return t / v
    ps = [p for p in row[1:5] if p]
    return sum(ps)/len(ps) if ps else None

def is_high_throw(klines, idx):
    if idx < 1 or idx >= len(klines): return False
    th, yh = klines[idx][3], klines[idx-1][3]
    if not th or not yh or th >= yh: return False
    start = max(0, idx - LOOKBACK)
    highs = [klines[i][3] for i in range(start, idx) if klines[i][3]]
    return yh == max(highs) if highs else False

def run_one(conn, signals, cfg):
    c = conn.cursor()
    trades, pending = [], []
    sl = cfg['stop_loss']
    tc = cfg['t_check']
    mh = cfg['max_hold']
    confirm = cfg['confirm']

    for sig in signals:
        code, buy_date = sig['code'], sig['date']
        c.execute("SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover "
                  "FROM kline_data WHERE stock_code=? AND DATE(time_key)=DATE(?) LIMIT 1", (code, buy_date))
        d0 = c.fetchone()

        if confirm:
            # 阳线确认: 信号日必须收阳
            if not d0 or not d0[1] or not d0[2] or d0[2] <= d0[1]:
                continue  # 跳过阴线信号
            # T+1开盘买入
            c.execute("SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover "
                      "FROM kline_data WHERE stock_code=? AND DATE(time_key)>DATE(?) ORDER BY time_key LIMIT ?",
                      (code, buy_date, mh + 5))
            future = c.fetchall()
            if not future: continue
            buy_price = future[0][1] or vwap(future[0])  # T+1开盘价
            future = future[1:]  # 从T+2开始算持有
        else:
            buy_price = (d0[1] if d0 and d0[1] else None) or sig['price']
            c.execute("SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover "
                      "FROM kline_data WHERE stock_code=? AND DATE(time_key)>DATE(?) ORDER BY time_key LIMIT ?",
                      (code, buy_date, mh + 5))
            future = c.fetchall()

        if not buy_price or len(future) < tc:
            pending.append(sig)
            continue

        sell_price = sell_date = sell_reason = None
        hold_days = 0
        for i in range(len(future)):
            hold_days = i + 1
            dv = vwap(future[i])
            dc = future[i][2] if future[i][2] else None
            cur = dv or dc or buy_price
            ret = (cur - buy_price) / buy_price * 100

            if ret <= sl:
                sell_price, sell_date, sell_reason = cur, future[i][0][:10], f'止损({ret:.0f}%)'
                break
            if hold_days == tc:
                up = sum(1 for j in range(tc) if future[j][2] and future[j][1] and future[j][2] > future[j][1])
                t_ret = (cur - buy_price) / buy_price * 100
                if t_ret < 0 and up < 1:
                    sell_price, sell_date = dc or cur, future[i][0][:10]
                    sell_reason = f'趋势未延续'
                    break
            if hold_days > tc and is_high_throw(future, i):
                sell_price, sell_date, sell_reason = dv or cur, future[i][0][:10], '高抛信号'
                break
            if hold_days >= mh:
                sell_price, sell_date, sell_reason = cur, future[i][0][:10], '超时'
                break

        if sell_price:
            trades.append({'ret': (sell_price-buy_price)/buy_price*100, 'days': hold_days,
                          'reason': sell_reason, 'code': sig['code'], 'name': sig['name'],
                          'buy_date': buy_date, 'buy_price': buy_price,
                          'sell_date': sell_date, 'sell_price': sell_price})
        else:
            pending.append(sig)
    return trades, pending

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

    L = ['# 趋势反转策略 — 多参数对比回测\n']
    L.append(f'> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 信号总数: {len(signals)}\n')

    # 对比总表
    L.append('## 参数对比总表\n')
    L.append('| 配置 | 交易数 | 平均收益 | 胜率 | 盈亏比 | 平均持有 | 最大盈利 | 最大亏损 |')
    L.append('|------|--------|---------|------|--------|---------|---------|---------|')

    all_results = {}
    for cfg in CONFIGS:
        trades, pending = run_one(conn, signals, cfg)
        all_results[cfg['name']] = (trades, pending)
        if trades:
            rets = [t['ret'] for t in trades]
            wins = [r for r in rets if r > 0]
            losses = [r for r in rets if r <= 0]
            days = [t['days'] for t in trades]
            aw = sum(wins)/len(wins) if wins else 0
            al = abs(sum(losses)/len(losses)) if losses else 1
            L.append(f"| {cfg['name']} | {len(trades)} | {sum(rets)/len(rets):+.2f}% | "
                     f"{len(wins)/len(trades)*100:.0f}% | {aw/al:.2f} | {sum(days)/len(days):.1f} | "
                     f"{max(rets):+.1f}% | {min(rets):+.1f}% |")
        else:
            L.append(f"| {cfg['name']} | 0 | - | - | - | - | - | - |")

    # 每个配置的退出原因分组
    for cfg_name, (trades, _) in all_results.items():
        if not trades: continue
        L.append(f'\n### {cfg_name}\n')
        reasons = {}
        for t in trades:
            k = t['reason'].split('(')[0].strip()
            reasons.setdefault(k, []).append(t)
        L.append('| 退出原因 | 数量 | 平均收益 | 胜率 |')
        L.append('|---------|------|---------|------|')
        for rn, grp in sorted(reasons.items()):
            gr = [t['ret'] for t in grp]
            gw = len([r for r in gr if r > 0])
            L.append(f"| {rn} | {len(grp)} | {sum(gr)/len(gr):+.2f}% | {gw/len(grp)*100:.0f}% |")

        # 详细记录
        L.append('\n| 股票 | 买入日 | 买入价 | 卖出日 | 卖出价 | 天数 | 收益率 | 原因 |')
        L.append('|------|--------|--------|--------|--------|------|--------|------|')
        for t in sorted(trades, key=lambda x: x['buy_date'], reverse=True):
            rs = f"+{t['ret']:.1f}%" if t['ret'] >= 0 else f"{t['ret']:.1f}%"
            L.append(f"| {t['code']} {t['name']} | {t['buy_date']} | {t['buy_price']:.2f} | "
                     f"{t['sell_date']} | {t['sell_price']:.2f} | {t['days']} | {rs} | {t['reason']} |")

    conn.close()
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print(f'Report: {OUT}')

if __name__ == '__main__':
    main()
