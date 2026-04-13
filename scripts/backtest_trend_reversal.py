#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""趋势反转策略回测 - 动态卖出逻辑"""
import sqlite3, os, sys
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), '..', 'simple_trade', 'data', 'trade.db')
OUT = os.path.join(os.path.dirname(__file__), 'trend_reversal_backtest_report.md')

LOOKBACK = 12       # 高抛信号回看天数
MAX_HOLD = 20       # 最大持有交易日
STOP_LOSS = -5.0    # 止损阈值%
T2_CHECK = 2        # 趋势验证天数


def vwap(row):
    """计算VWAP, row = (time_key, open, close, high, low, volume, turnover)"""
    if not row:
        return None
    v, t = row[5], row[6]
    if v and v > 0 and t and t > 0:
        return t / v
    ps = [p for p in row[1:5] if p]
    return sum(ps) / len(ps) if ps else None


def close_price(row):
    """获取收盘价"""
    return row[2] if row and row[2] else None


def is_high_throw(klines, idx):
    """检查idx位置是否触发高抛信号: 今日最高 < 昨日最高 且 昨日最高 = 近12日最高"""
    if idx < 1 or idx >= len(klines):
        return False
    today_high = klines[idx][3]
    yd_high = klines[idx - 1][3]
    if not today_high or not yd_high or today_high >= yd_high:
        return False
    start = max(0, idx - LOOKBACK)
    period_highs = [klines[i][3] for i in range(start, idx) if klines[i][3]]
    if not period_highs:
        return False
    return yd_high == max(period_highs)


def run_backtest():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # 1. 获取趋势反转策略的买入信号(去重)
    c.execute("""
        SELECT ts.id, s.code, s.name, ts.signal_price, ts.created_at
        FROM trade_signals ts JOIN stocks s ON ts.stock_id = s.id
        WHERE ts.signal_type = 'BUY'
          AND (ts.strategy_name = '趋势反转策略' OR ts.strategy_id = 'trend_reversal')
        ORDER BY ts.created_at DESC
    """)
    rows = c.fetchall()
    seen = set()
    signals = []
    for r in rows:
        key = (r[1], r[4][:10])
        if key not in seen:
            seen.add(key)
            signals.append({'code': r[1], 'name': r[2], 'price': r[3], 'date': r[4][:10]})

    # 2. 逐个信号模拟交易
    trades = []
    pending = []
    for sig in signals:
        code, buy_date = sig['code'], sig['date']

        # 买入日K线
        c.execute(
            "SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover "
            "FROM kline_data WHERE stock_code=? AND DATE(time_key)=DATE(?) LIMIT 1",
            (code, buy_date))
        d0 = c.fetchone()
        buy_price = (d0[1] if d0 and d0[1] else None) or sig['price']  # 开盘价

        # 买入后的K线
        c.execute(
            "SELECT time_key,open_price,close_price,high_price,low_price,volume,turnover "
            "FROM kline_data WHERE stock_code=? AND DATE(time_key)>DATE(?) "
            "ORDER BY time_key ASC LIMIT ?",
            (code, buy_date, MAX_HOLD + 5))
        future = c.fetchall()

        if len(future) < T2_CHECK:
            pending.append({**sig, 'buy_price': buy_price, 'future_days': len(future)})
            continue

        # --- 逐日检查卖出 ---
        sell_price = None
        sell_date = None
        sell_reason = None
        hold_days = 0

        for i in range(len(future)):
            hold_days = i + 1
            day_vwap = vwap(future[i])
            day_close = close_price(future[i])
            cur_price = day_vwap or day_close or buy_price

            # 止损检查(每日)
            ret = (cur_price - buy_price) / buy_price * 100
            if ret <= STOP_LOSS:
                sell_price = cur_price
                sell_date = future[i][0][:10]
                sell_reason = f'止损({ret:.1f}%)'
                break

            # T+2 趋势验证
            if hold_days == T2_CHECK:
                t2_ret = (cur_price - buy_price) / buy_price * 100
                up_count = sum(1 for j in range(T2_CHECK)
                               if future[j][2] and future[j][1] and future[j][2] > future[j][1])
                if t2_ret < 0 and up_count < 1:
                    sell_price = day_close or cur_price
                    sell_date = future[i][0][:10]
                    sell_reason = f'趋势未延续(T+2收益{t2_ret:.1f}%,阳线{up_count}天)'
                    break

            # 高抛信号(T+2后开始检查)
            if hold_days > T2_CHECK:
                # 构建包含买入日到当前的K线序列用于高抛判断
                if is_high_throw(future, i):
                    sell_price = day_vwap or cur_price
                    sell_date = future[i][0][:10]
                    sell_reason = '高抛信号'
                    break

            # 超时
            if hold_days >= MAX_HOLD:
                sell_price = cur_price
                sell_date = future[i][0][:10]
                sell_reason = '超时退出'
                break

        if sell_price and sell_date:
            ret_pct = (sell_price - buy_price) / buy_price * 100
            trades.append({
                'code': sig['code'], 'name': sig['name'],
                'buy_date': buy_date, 'buy_price': buy_price,
                'sell_date': sell_date, 'sell_price': sell_price,
                'hold_days': hold_days, 'return_pct': ret_pct,
                'reason': sell_reason
            })
        else:
            pending.append({**sig, 'buy_price': buy_price, 'future_days': len(future)})

    conn.close()

    # 3. 生成报告
    generate_report(signals, trades, pending)
    print(f"Done: {len(trades)} trades, {len(pending)} pending")


def generate_report(signals, trades, pending):
    L = []
    L.append('# 趋势反转策略回测报告\n')
    L.append(f'> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}  ')
    L.append(f'> 策略: 趋势反转策略 | 信号总数: {len(signals)} | 完结交易: {len(trades)} | 待观察: {len(pending)}\n')

    L.append('## 卖出规则\n')
    L.append(f'1. **T+{T2_CHECK}趋势验证**: 持有{T2_CHECK}天后收益为负且阳线<1天 → 收盘价卖出')
    L.append(f'2. **高抛信号**: 今日最高 < 昨日最高 且 昨日最高=近{LOOKBACK}日最高 → VWAP卖出')
    L.append(f'3. **固定止损**: 收益率 ≤ {STOP_LOSS}% → VWAP卖出')
    L.append(f'4. **超时退出**: 持有 > {MAX_HOLD}个交易日 → VWAP卖出\n')

    # 汇总
    if trades:
        rets = [t['return_pct'] for t in trades]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        days = [t['hold_days'] for t in trades]

        L.append('## 汇总统计\n')
        L.append('| 指标 | 值 |')
        L.append('|------|------|')
        L.append(f'| 完结交易数 | {len(trades)} |')
        L.append(f'| 平均收益率 | {sum(rets)/len(rets):+.2f}% |')
        L.append(f'| 中位数收益 | {sorted(rets)[len(rets)//2]:+.2f}% |')
        L.append(f'| 胜率 | {len(wins)/len(trades)*100:.1f}% |')
        L.append(f'| 平均持有天数 | {sum(days)/len(days):.1f} |')
        L.append(f'| 最大盈利 | {max(rets):+.2f}% |')
        L.append(f'| 最大亏损 | {min(rets):+.2f}% |')
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 1
        L.append(f'| 盈亏比 | {avg_win/avg_loss:.2f} |')
        L.append('')

        # 按退出原因分组
        reasons = {}
        for t in trades:
            key = t['reason'].split('(')[0].strip()
            if key not in reasons:
                reasons[key] = []
            reasons[key].append(t)

        L.append('## 按退出原因分组\n')
        L.append('| 退出原因 | 交易数 | 平均收益 | 胜率 | 平均持有天数 |')
        L.append('|---------|--------|---------|------|------------|')
        for reason, group in sorted(reasons.items()):
            g_rets = [t['return_pct'] for t in group]
            g_days = [t['hold_days'] for t in group]
            g_wins = len([r for r in g_rets if r > 0])
            L.append(f'| {reason} | {len(group)} | {sum(g_rets)/len(g_rets):+.2f}% | '
                     f'{g_wins/len(group)*100:.0f}% | {sum(g_days)/len(g_days):.1f} |')
        L.append('')

    # 详细交易记录
    L.append('## 详细交易记录\n')
    L.append('| 股票代码 | 名称 | 买入日 | 买入价 | 卖出日 | 卖出价 | 持有天数 | 收益率 | 退出原因 |')
    L.append('|----------|------|--------|--------|--------|--------|---------|--------|---------|')
    for t in sorted(trades, key=lambda x: x['buy_date'], reverse=True):
        ret_s = f"+{t['return_pct']:.2f}%" if t['return_pct'] >= 0 else f"{t['return_pct']:.2f}%"
        L.append(f"| {t['code']} | {t['name']} | {t['buy_date']} | {t['buy_price']:.3f} | "
                 f"{t['sell_date']} | {t['sell_price']:.3f} | {t['hold_days']} | {ret_s} | {t['reason']} |")

    if pending:
        L.append(f'\n## 待观察信号（共{len(pending)}条）\n')
        L.append('| 股票代码 | 名称 | 信号日期 | 买入价 |')
        L.append('|----------|------|----------|--------|')
        for p in pending:
            L.append(f"| {p['code']} | {p['name']} | {p['date']} | {p['buy_price']:.3f} |")

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print(f"Report: {OUT}")


if __name__ == '__main__':
    run_backtest()
