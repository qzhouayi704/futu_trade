#!/usr/bin/env python3
"""
分析 HK.00100 (MINIMAX-W) 今天盘中反转的场景
逐30分钟窗口展示：资金方向变化 → 排行榜位置如何变化
对比"累计全天"vs"滑动窗口"两种评分方式
"""

import sqlite3
from collections import defaultdict

DB_PATH = 'simple_trade/data/trade.db'
TARGET = 'HK.00100'
TODAY = '2026-05-26'


def load_minute_data(conn, stock_code, today):
    rows = conn.execute("""
        SELECT
            substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
            direction, SUM(turnover) as tv, AVG(price) as ap
        FROM ticker_data
        WHERE stock_code = ? AND trade_date = ?
        GROUP BY minute, direction ORDER BY minute
    """, (stock_code, today)).fetchall()

    minutes = {}
    for minute, direction, turnover, avg_price in rows:
        if not ('09:15' <= minute <= '16:10'):
            continue
        if minute not in minutes:
            minutes[minute] = {'buy': 0, 'sell': 0, 'price': 0, 'price_n': 0}
        e = minutes[minute]
        tv = float(turnover or 0)
        if direction == 'BUY':
            e['buy'] += tv
        elif direction == 'SELL':
            e['sell'] += tv
        if avg_price and float(avg_price) > 0:
            e['price'] += float(avg_price)
            e['price_n'] += 1

    timeline = []
    cum_buy, cum_sell = 0, 0
    for minute in sorted(minutes.keys()):
        e = minutes[minute]
        cum_buy += e['buy']
        cum_sell += e['sell']
        net = e['buy'] - e['sell']
        price = round(e['price'] / e['price_n'], 3) if e['price_n'] > 0 else 0
        timeline.append({
            'time': minute,
            'net': round(net / 10000, 1),
            'cum_net': round((cum_buy - cum_sell) / 10000, 1),
            'price': price,
        })
    return timeline


def main():
    conn = sqlite3.connect(DB_PATH)
    tl = load_minute_data(conn, TARGET, TODAY)
    if not tl:
        print("无数据")
        return

    name_row = conn.execute("SELECT name FROM stocks WHERE code=?", (TARGET,)).fetchone()
    name = name_row[0] if name_row else TARGET
    open_price = tl[0]['price']

    print(f"{'='*90}")
    print(f"📊 {name} ({TARGET}) {TODAY} 盘中走势分析")
    print(f"{'='*90}")
    print(f"开盘价: {open_price}")

    # ============ Part 1: 逐30分钟展示资金流向 ============
    print(f"\n{'─'*90}")
    print(f"Part 1: 每30分钟的资金流向快照")
    print(f"{'─'*90}")

    check_points = ['09:30', '09:45', '10:00', '10:30', '11:00', '11:30',
                    '13:00', '13:30', '14:00', '14:30', '15:00', '15:30', '16:00']

    for cp in check_points:
        points = [p for p in tl if p['time'] <= cp]
        if not points:
            continue

        cur_price = points[-1]['price']
        cum_net = points[-1]['cum_net']
        chg = round((cur_price - open_price) / open_price * 100, 2) if open_price > 0 else 0

        # 最近30分钟的净流入
        recent_30 = [p for p in tl if cp >= p['time'] > _sub_30(cp)]
        recent_net = sum(p['net'] for p in recent_30)

        # 资金方向判定
        if cum_net > 0:
            cum_dir = "🟢 正向"
        elif cum_net < 0:
            cum_dir = "🔴 负向"
        else:
            cum_dir = "⚪ 中性"

        if recent_net > 100:
            recent_dir = "🟢 流入"
        elif recent_net < -100:
            recent_dir = "🔴 流出"
        else:
            recent_dir = "⚪ 平衡"

        bar_len = min(abs(int(cum_net / 200)), 20)
        bar = ("█" * bar_len) if cum_net > 0 else ("▓" * bar_len)
        bar_sign = "+" if cum_net > 0 else ""

        print(f"  {cp}  价格={cur_price:>8.3f}  涨幅={chg:>+.2f}%  "
              f"累计净流={bar_sign}{cum_net:>+8.0f}万 {cum_dir}  "
              f"近30分钟={recent_net:>+6.0f}万 {recent_dir}")

    # ============ Part 2: 评分模拟 — 两种方式对比 ============
    print(f"\n{'─'*90}")
    print(f"Part 2: 两种评分方式对比")
    print(f"{'─'*90}")
    print(f"  方式A: 累计全天（红绿混合）→ 一旦进入风险榜，难以出来")
    print(f"  方式B: 滑动窗口30分钟 → 随资金反转实时切换")
    print()

    for cp in ['10:00', '10:30', '11:00', '13:00', '13:30', '14:00', '14:30', '15:00']:
        points = [p for p in tl if p['time'] <= cp]
        if len(points) < 5:
            continue

        cur_price = points[-1]['price']
        cum_net = points[-1]['cum_net']
        chg = round((cur_price - open_price) / open_price * 100, 2) if open_price > 0 else 0

        # 方式A: 累计全天
        if cum_net > 0 and chg > 0:
            rank_a = "🟢 机会榜"
        elif cum_net < 0 and chg < 0:
            rank_a = "🔴 风险榜"
        elif cum_net < 0:
            rank_a = "🔴 风险榜(资金负)"
        elif chg < 0:
            rank_a = "⚠️ 观望(价跌但资金正)"
        else:
            rank_a = "⚪ 中性"

        # 方式B: 滑动窗口30分钟
        recent_30 = [p for p in tl if cp >= p['time'] > _sub_30(cp)]
        recent_net = sum(p['net'] for p in recent_30)
        # 最近30分钟价格变化
        if recent_30 and len(recent_30) > 1:
            r_chg = round((recent_30[-1]['price'] - recent_30[0]['price']) / recent_30[0]['price'] * 100, 2) if recent_30[0]['price'] > 0 else 0
        else:
            r_chg = 0

        if recent_net > 200 and r_chg > 0:
            rank_b = "🟢 机会榜"
        elif recent_net < -200 and r_chg < 0:
            rank_b = "🔴 风险榜"
        elif recent_net > 200:
            rank_b = "🟢 机会(资金流入中)"
        elif recent_net < -200:
            rank_b = "🔴 风险(资金流出中)"
        else:
            rank_b = "⚪ 中性"

        print(f"  {cp}  涨幅={chg:>+.2f}%  累计净流={cum_net:>+6.0f}万  近30分钟={recent_net:>+6.0f}万")
        print(f"        方式A(全天累计): {rank_a}")
        print(f"        方式B(滑动窗口): {rank_b}")
        print()

    # ============ Part 3: 结论 ============
    print(f"{'─'*90}")
    print(f"结论:")
    print(f"{'─'*90}")

    # 找到资金反转点
    prev_dir = 'neutral'
    reversal_points = []
    for i, p in enumerate(tl):
        if i % 3 != 0 or i == 0:
            continue
        cur_dir = 'positive' if p['cum_net'] > 0 else ('negative' if p['cum_net'] < 0 else 'neutral')
        if prev_dir == 'negative' and cur_dir == 'positive':
            reversal_points.append(('负→正', p['time'], p['price'], p['cum_net']))
        elif prev_dir == 'positive' and cur_dir == 'negative':
            reversal_points.append(('正→负', p['time'], p['price'], p['cum_net']))
        prev_dir = cur_dir

    if reversal_points:
        print(f"\n  资金反转事件:")
        for direction, time, price, cum in reversal_points:
            emoji = "🟢" if "正" in direction.split("→")[1] else "🔴"
            print(f"    {emoji} {time} 资金{direction}  价格={price:.3f}  累计={cum:>+.0f}万")

    # 全天分段分析
    morning = [p for p in tl if p['time'] <= '12:00']
    afternoon = [p for p in tl if p['time'] >= '13:00']

    if morning and afternoon:
        m_net = sum(p['net'] for p in morning)
        a_net = sum(p['net'] for p in afternoon)
        print(f"\n  上午净流入: {m_net:>+.0f}万 {'🔴流出' if m_net < 0 else '🟢流入'}")
        print(f"  下午净流入: {a_net:>+.0f}万 {'🔴流出' if a_net < 0 else '🟢流入'}")
        print(f"\n  → 方式A(全天累计): 上午进入风险榜后，即使下午反转也难以翻正")
        print(f"  → 方式B(滑动窗口): 下午资金流入时立即切换到机会榜 ✅")


def _sub_30(hhmm):
    """简单减30分钟"""
    h, m = int(hhmm[:2]), int(hhmm[3:])
    m -= 30
    if m < 0:
        h -= 1
        m += 60
    return f"{h:02d}:{m:02d}"


if __name__ == '__main__':
    main()
