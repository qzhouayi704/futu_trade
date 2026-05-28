#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日内波段回测 — 基于逐笔成交数据(ticker_data)
高精度模拟：逐笔 → 合成5分钟OHLCV → 滑动窗口动量分析 → 信号生成

使用 2026-05-15 的77万条逐笔数据
"""
import sqlite3, sys, os
from collections import defaultdict
from datetime import datetime, timezone, timedelta

DB_PATH = "simple_trade/data/trade.db"
TEST_DATE = "2026-05-22"

# 港股交易时段(UTC) 09:30-16:00 HKT = 01:30-08:00 UTC
HKT = timedelta(hours=8)
TRADE_COST_PCT = 0.16  # 单次交易成本: 佣金0.03%*2 + 印花税0.1%


def load_ticker_data(conn, stock_code, trade_date):
    """加载逐笔数据并按时间排序"""
    c = conn.cursor()
    c.execute("""
        SELECT price, volume, turnover, direction, timestamp, created_at
        FROM ticker_data
        WHERE stock_code = ? AND trade_date = ?
        ORDER BY timestamp ASC, id ASC
    """, (stock_code, trade_date))
    return c.fetchall()


def ticks_to_5min_bars(ticks):
    """逐笔数据合成5分钟K线（精准模拟实时合成过程）"""
    bar_map = defaultdict(list)

    for tick in ticks:
        price, vol, to, direction, ts_ms, created_at = tick
        price = float(price)
        vol = int(vol) if vol else 0
        if price <= 0:
            continue

        # timestamp(ms) -> HKT time
        ts_sec = ts_ms / 1000
        dt_utc = datetime.fromtimestamp(ts_sec, tz=timezone.utc)
        dt_hkt = dt_utc + HKT
        h, m = dt_hkt.hour, dt_hkt.minute

        # 过滤非交易时段
        hkt_time = h * 100 + m
        if hkt_time < 930 or hkt_time >= 1600:
            continue
        if 1200 <= hkt_time < 1300:
            continue  # 午休

        # 5分钟对齐
        m5 = (m // 5) * 5
        bar_key = f"{h:02d}:{m5:02d}"
        bar_map[bar_key].append({
            'price': price, 'vol': vol, 'to': float(to) if to else 0,
            'dir': direction, 'ts': ts_ms
        })

    bars = []
    for key in sorted(bar_map.keys()):
        entries = bar_map[key]
        if not entries:
            continue
        prices = [e['price'] for e in entries]
        buy_vol = sum(e['vol'] for e in entries if e['dir'] == 'BUY')
        sell_vol = sum(e['vol'] for e in entries if e['dir'] == 'SELL')
        total_to = sum(e['to'] for e in entries)

        bars.append({
            'time': key,
            'open': prices[0], 'close': prices[-1],
            'high': max(prices), 'low': min(prices),
            'volume': sum(e['vol'] for e in entries),
            'turnover': total_to,
            'buy_vol': buy_vol, 'sell_vol': sell_vol,
            'ticks': len(entries),
            'net_buy_ratio': (buy_vol - sell_vol) / (buy_vol + sell_vol)
                if (buy_vol + sell_vol) > 0 else 0,
        })
    return bars


def analyze_momentum(bars):
    """滑动窗口动量分析"""
    results = []
    for i in range(len(bars)):
        avail = bars[:i+1]
        if len(avail) < 3:
            results.append(None)
            continue

        r3 = avail[-3:]
        w = [0.2, 0.3, 0.5]
        direction = sum(w[j] * (1 if r3[j]['close'] > r3[j]['open'] else -1) for j in range(3))

        # fractals
        b1, b2, b3 = avail[-3], avail[-2], avail[-1]
        has_top = (b2['high'] > b1['high'] and b2['high'] > b3['high']
                   and b3['close'] < b2['open'])
        has_bottom = (b2['low'] < b1['low'] and b2['low'] < b3['low']
                      and b3['close'] > b2['open'])

        # shadows
        bar = avail[-1]
        amp = bar['high'] - bar['low']
        upper_s = bar['high'] - max(bar['open'], bar['close'])
        lower_s = min(bar['open'], bar['close']) - bar['low']
        upper_warn = amp > 0 and (upper_s / amp) > 0.6
        lower_sup = amp > 0 and (lower_s / amp) > 0.6

        # trend
        trend = "stable"
        if len(avail) >= 6:
            prev_b = [abs(b['close'] - b['open']) for b in avail[-6:-3]]
            curr_b = [abs(b['close'] - b['open']) for b in avail[-3:]]
            pa = sum(prev_b) / 3 if prev_b else 0.001
            ca = sum(curr_b) / 3
            accel = (ca - pa) / pa if pa > 0 else 0
            pd = sum(1 if b['close'] > b['open'] else -1 for b in avail[-6:-3]) / 3
            cd = sum(1 if b['close'] > b['open'] else -1 for b in avail[-3:]) / 3
            if pd * cd < 0:
                trend = "reversing"
            elif accel > 0.3:
                trend = "accelerating"
            elif accel < -0.3:
                trend = "decelerating"

        # 资金流方向(逐笔特有)
        net_buy_3 = sum(b['net_buy_ratio'] for b in r3) / 3

        results.append({
            'dir': round(direction, 3),
            'top': has_top, 'bot': has_bottom,
            'uw': upper_warn, 'ls': lower_sup,
            'trend': trend,
            'net_buy_3': round(net_buy_3, 3),  # 近3根净买入比率
        })
    return results


def simulate(bars, mom, stock_code):
    """模拟波段交易（含资金流+交易成本）"""
    if not bars or len(bars) < 6:
        return []

    open_price = bars[0]['open']
    signals = []
    has_pos = True
    sell_px = 0
    peak_after = 0

    for i, bar in enumerate(bars):
        if i < 3:
            continue
        st = mom[i]
        if st is None:
            continue

        px = bar['close']
        t = bar['time']
        if t < '09:40' or ('12:00' <= t < '13:00'):
            continue

        chg = (px - open_price) / open_price * 100

        if has_pos:
            # === SELL check (R13) ===
            conds = 0
            reasons = []

            # C1: 动量减弱
            if st['top']:
                conds += 1; reasons.append("TOP")
            elif st['uw']:
                conds += 1; reasons.append("UP_SHADOW")
            elif st['dir'] < -0.2 and st['trend'] in ("decelerating", "reversing"):
                conds += 1; reasons.append(f"MOM({st['dir']:.2f})")

            # C2: 高位
            if chg >= 2.0:
                conds += 1; reasons.append(f"+{chg:.1f}%")
            elif chg >= 1.0 and st['dir'] < 0:
                conds += 1; reasons.append(f"+{chg:.1f}%&neg")

            # C3: 资金流出(逐笔特有) 或 近3根跌
            if st['net_buy_3'] < -0.15:
                conds += 1; reasons.append(f"FLOW({st['net_buy_3']:.2f})")
            elif i >= 3:
                r3 = (px - bars[i-3]['open']) / bars[i-3]['open'] * 100
                if r3 < -0.3 and st['dir'] < 0:
                    conds += 1; reasons.append(f"R3={r3:+.2f}%")

            if conds >= 2:
                signals.append({
                    'time': t, 'type': 'SELL', 'price': px,
                    'chg': chg, 'reasons': reasons, 'conds': conds,
                    'net_buy': st['net_buy_3'],
                })
                has_pos = False
                sell_px = px
                peak_after = px

        else:
            if px > peak_after:
                peak_after = px
            if sell_px <= 0:
                continue

            # === BUY check (R14 + SwingTracker) ===
            conds = 0
            reasons = []

            # C1: 动量恢复
            if st['bot']:
                conds += 1; reasons.append("BOTTOM")
            elif st['ls']:
                conds += 1; reasons.append("LOW_SHADOW")
            elif st['dir'] > 0.2 and st['trend'] in ("accelerating", "stable"):
                conds += 1; reasons.append(f"MOM({st['dir']:.2f})")

            # C2: 价格回撤
            dd = (sell_px - px) / sell_px * 100
            if dd >= 1.0:
                conds += 1; reasons.append(f"DD={dd:.1f}%")
            elif chg <= -0.5:
                conds += 1; reasons.append(f"DAY={chg:.1f}%")

            # C3: 资金流转正(逐笔特有) 或 K线企稳
            if st['net_buy_3'] > 0.1:
                conds += 1; reasons.append(f"FLOW+({st['net_buy_3']:.2f})")
            elif i >= 3:
                r3 = (px - bars[i-3]['open']) / bars[i-3]['open'] * 100
                if r3 > 0.2 and st['dir'] > 0:
                    conds += 1; reasons.append(f"R3={r3:+.2f}%")

            # 买回价须低于卖出价，且扣除成本后有利润
            gross_profit = (sell_px - px) / sell_px * 100
            net_profit = gross_profit - TRADE_COST_PCT * 2  # 卖+买各一次
            if conds >= 2 and px < sell_px and net_profit > 0:
                signals.append({
                    'time': t, 'type': 'BUY', 'price': px,
                    'chg': chg, 'reasons': reasons, 'conds': conds,
                    'gross_profit': gross_profit,
                    'net_profit': net_profit,
                    'net_buy': st['net_buy_3'],
                })
                has_pos = True
                sell_px = 0

    return signals


def print_bar_chart(bars, mom, width=45):
    """打印K线走势图"""
    if not bars:
        return
    max_p = max(b['high'] for b in bars)
    min_p = min(b['low'] for b in bars)
    rng = max_p - min_p if max_p > min_p else 1
    base = bars[0]['open']

    for i, bar in enumerate(bars):
        t = bar['time']
        if '12:00' <= t < '13:00':
            continue

        chg = (bar['close'] - base) / base * 100
        bs = int((min(bar['open'], bar['close']) - min_p) / rng * width)
        be = int((max(bar['open'], bar['close']) - min_p) / rng * width)
        lp = int((bar['low'] - min_p) / rng * width)
        hp = int((bar['high'] - min_p) / rng * width)

        line = [' '] * (width + 1)
        for j in range(lp, min(hp + 1, width + 1)):
            line[j] = '-'
        ch = '#' if bar['close'] >= bar['open'] else 'v'
        for j in range(bs, min(be + 1, width + 1)):
            line[j] = ch

        # flow indicator
        flow_ch = ''
        if bar['net_buy_ratio'] > 0.3:
            flow_ch = ' $+'
        elif bar['net_buy_ratio'] < -0.3:
            flow_ch = ' $-'

        m_tag = ""
        if mom[i]:
            if mom[i]['top']: m_tag = " <-TOP"
            elif mom[i]['bot']: m_tag = " <-BOT"
            elif mom[i]['uw']: m_tag = " <-UW"
            elif mom[i]['ls']: m_tag = " <-LS"

        print(f"  {t} |{''.join(line)}| {bar['close']:.3f}({chg:+.1f}%) {bar['ticks']:>5}tk{flow_ch}{m_tag}")


def run():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 获取当天所有股票
    c.execute("""SELECT stock_code, COUNT(*) FROM ticker_data
                 WHERE trade_date = ? GROUP BY stock_code ORDER BY COUNT(*) DESC""",
              (TEST_DATE,))
    stock_list = c.fetchall()

    print("=" * 78)
    print(f"  INTRADAY SWING BACKTEST (Tick-Level Precision)")
    print(f"  Date: {TEST_DATE} | Stocks: {len(stock_list)} | Trade cost: {TRADE_COST_PCT*2:.2f}%/round")
    print("=" * 78)

    total_signals = 0
    total_swings = 0
    total_gross = 0.0
    total_net = 0.0
    all_profits = []
    stock_results = []

    for stock_code, tick_count in stock_list:
        if tick_count < 100:
            continue

        print(f"\n  Loading {stock_code} ({tick_count} ticks)...", end=" ", flush=True)

        ticks = load_ticker_data(conn, stock_code, TEST_DATE)
        bars = ticks_to_5min_bars(ticks)

        if not bars or len(bars) < 6:
            print(f"insufficient bars ({len(bars) if bars else 0})")
            continue

        mom = analyze_momentum(bars)
        sigs = simulate(bars, mom, stock_code)

        day_high = max(b['high'] for b in bars)
        day_low = min(b['low'] for b in bars)
        amplitude = (day_high - day_low) / day_low * 100

        # 逐笔资金流统计
        total_buy = sum(b['buy_vol'] for b in bars)
        total_sell = sum(b['sell_vol'] for b in bars)
        net_flow = "BUY" if total_buy > total_sell else "SELL"
        flow_ratio = (total_buy - total_sell) / (total_buy + total_sell) * 100 if (total_buy + total_sell) > 0 else 0

        print(f"{len(bars)} bars, amp {amplitude:.1f}%, flow {net_flow}({flow_ratio:+.1f}%)")

        print(f"\n  {'=' * 76}")
        print(f"  {stock_code} | {len(bars)} 5min-bars | {tick_count} ticks | Amplitude: {amplitude:.1f}%")
        print(f"  Range: {day_low:.3f} - {day_high:.3f} | Net flow: {net_flow} ({flow_ratio:+.1f}%)")
        print(f"  {'=' * 76}")

        print_bar_chart(bars, mom)

        if sigs:
            print(f"\n  SIGNALS:")
            stock_gross = 0
            stock_net = 0
            stock_swings = 0
            for sig in sigs:
                icon = "  >> SELL" if sig['type'] == 'SELL' else "  << BUY "
                profit_str = ""
                if 'net_profit' in sig:
                    g = sig['gross_profit']
                    n = sig['net_profit']
                    profit_str = f" | Gross +{g:.2f}% Net +{n:.2f}%"
                    total_gross += g
                    total_net += n
                    total_swings += 1
                    stock_swings += 1
                    stock_gross += g
                    stock_net += n
                    all_profits.append(n)

                flow_str = f"flow={sig['net_buy']:.2f}" if 'net_buy' in sig else ""
                print(f"  {icon} {sig['time']} @ {sig['price']:.3f} "
                      f"(day{sig['chg']:+.1f}%) [{sig['conds']}/3] "
                      f"{'+'.join(sig['reasons'])} {flow_str}{profit_str}")
                total_signals += 1

            if stock_swings > 0:
                stock_results.append((stock_code, stock_swings, stock_gross, stock_net, amplitude))
        else:
            print(f"\n  No signals generated (low volatility or conditions not met)")

    # Summary
    print(f"\n{'=' * 78}")
    print(f"  BACKTEST SUMMARY — {TEST_DATE}")
    print(f"{'=' * 78}")
    print(f"  Stocks tested     : {len(stock_list)}")
    print(f"  Total signals     : {total_signals}")
    print(f"  Complete swings   : {total_swings} (sell+buyback pairs)")
    if total_swings > 0:
        win = sum(1 for p in all_profits if p > 0)
        print(f"  Win rate (net)    : {win}/{total_swings} = {win/total_swings*100:.0f}%")
        print(f"  Avg gross profit  : {total_gross/total_swings:.2f}%")
        print(f"  Avg net profit    : {total_net/total_swings:.2f}% (after {TRADE_COST_PCT*2:.2f}% cost)")
        print(f"  Total gross profit: {total_gross:.2f}%")
        print(f"  Total net profit  : {total_net:.2f}%")
        if all_profits:
            print(f"  Best swing (net)  : +{max(all_profits):.2f}%")
            print(f"  Worst swing (net) : +{min(all_profits):.2f}%")
    else:
        print(f"  No complete swings found")

    if stock_results:
        print(f"\n  Per-Stock Breakdown:")
        print(f"  {'Stock':<15} {'Swings':>6} {'Gross':>8} {'Net':>8} {'Amp':>6}")
        for code, sw, g, n, amp in sorted(stock_results, key=lambda x: -x[3]):
            print(f"  {code:<15} {sw:>6} {g:>+7.2f}% {n:>+7.2f}% {amp:>5.1f}%")

    print(f"{'=' * 78}")
    conn.close()


if __name__ == "__main__":
    run()
