#!/usr/bin/env python3
"""
分析 HK.01879 (曦智科技-P) + 对比不同窗口大小 (5/10/15/30分钟)
"""
import sqlite3
DB_PATH = 'simple_trade/data/trade.db'
TARGET = 'HK.01879'
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
        if direction == 'BUY': e['buy'] += tv
        elif direction == 'SELL': e['sell'] += tv
        if avg_price and float(avg_price) > 0:
            e['price'] += float(avg_price)
            e['price_n'] += 1
    timeline = []
    cum_buy, cum_sell = 0, 0
    for minute in sorted(minutes.keys()):
        e = minutes[minute]
        cum_buy += e['buy']; cum_sell += e['sell']
        net = e['buy'] - e['sell']
        price = round(e['price'] / e['price_n'], 3) if e['price_n'] > 0 else 0
        timeline.append({
            'time': minute,
            'net': round(net / 10000, 1),
            'cum_net': round((cum_buy - cum_sell) / 10000, 1),
            'price': price,
        })
    return timeline

def sub_min(hhmm, mins):
    h, m = int(hhmm[:2]), int(hhmm[3:])
    total = h * 60 + m - mins
    if total < 0: total = 0
    return f"{total // 60:02d}:{total % 60:02d}"

def main():
    conn = sqlite3.connect(DB_PATH)
    tl = load_minute_data(conn, TARGET, TODAY)
    if not tl:
        print("无数据"); return
    row = conn.execute("SELECT name FROM stocks WHERE code=?", (TARGET,)).fetchone()
    name = row[0] if row else TARGET
    open_p = tl[0]['price']

    print(f"{'='*100}")
    print(f"📊 {name} ({TARGET}) {TODAY}")
    print(f"开盘={open_p}  收盘={tl[-1]['price']}  全天涨幅={round((tl[-1]['price']-open_p)/open_p*100,2):+.2f}%")
    print(f"{'='*100}")

    # Part 1: 逐15分钟走势
    print(f"\nPart 1: 盘中走势（每15分钟）")
    print(f"{'─'*100}")
    checks = ['09:30','09:45','10:00','10:15','10:30','10:45','11:00','11:15','11:30',
              '13:00','13:15','13:30','13:45','14:00','14:15','14:30','14:45','15:00','15:15','15:30','15:45','16:00']
    for cp in checks:
        pts = [p for p in tl if p['time'] <= cp]
        if not pts: continue
        cur_p = pts[-1]['price']
        cum = pts[-1]['cum_net']
        chg = round((cur_p - open_p) / open_p * 100, 2) if open_p > 0 else 0
        # 最近5分钟净流
        r5 = sum(p['net'] for p in tl if sub_min(cp, 5) < p['time'] <= cp)
        # 用条形图展示
        bar_n = min(abs(int(cum / 100)), 30)
        if cum >= 0:
            bar = f"{'█' * bar_n:>30}"
            col = "+"
        else:
            bar = f"{'▓' * bar_n:<30}"
            col = "-"
        print(f"  {cp}  价格={cur_p:>8.3f}  涨幅={chg:>+6.2f}%  累计={cum:>+8.0f}万  5分钟={r5:>+6.0f}万  {bar}")

    # Part 2: 不同窗口对比
    print(f"\n{'='*100}")
    print(f"Part 2: 不同窗口大小对比 — 在哪个窗口下最先识别出机会？")
    print(f"{'─'*100}")
    windows = [5, 10, 15, 30]
    header = f"  {'时间':>5}  {'涨幅':>6}  "
    for w in windows:
        header += f" {w}分钟窗口{'':>12}"
    print(header)
    print(f"  {'':>5}  {'':>6}  ", end="")
    for w in windows:
        print(f" {'净流':>6}  {'方向':>4}  {'判定':>6}  ", end="")
    print()

    for cp in checks:
        pts = [p for p in tl if p['time'] <= cp]
        if len(pts) < 3: continue
        cur_p = pts[-1]['price']
        chg = round((cur_p - open_p) / open_p * 100, 2) if open_p > 0 else 0

        line = f"  {cp:>5}  {chg:>+5.2f}%  "
        for w in windows:
            cutoff = sub_min(cp, w)
            window = [p for p in tl if cutoff < p['time'] <= cp]
            if len(window) < 2:
                line += f" {'---':>6}  {'--':>4}  {'--':>6}  "
                continue
            w_net = sum(p['net'] for p in window)
            w_chg = round((window[-1]['price'] - window[0]['price']) / window[0]['price'] * 100, 2) if window[0]['price'] > 0 else 0

            if w_net > 100 and w_chg > 0.3:
                judge = "🟢机会"
            elif w_net < -100 and w_chg < -0.3:
                judge = "🔴风险"
            elif w_net > 100:
                judge = "🟡流入"
            elif w_net < -100:
                judge = "🟠流出"
            else:
                judge = "⚪平"

            line += f" {w_net:>+5.0f}万  {w_chg:>+.1f}%  {judge}  "
        print(line)

    # Part 3: 哪个窗口最早识别出机会/风险的切换？
    print(f"\n{'='*100}")
    print(f"Part 3: 各窗口首次判定为 🟢机会 的时间")
    print(f"{'─'*100}")
    for w in windows:
        first_opp = None
        first_risk = None
        for cp in checks:
            cutoff = sub_min(cp, w)
            window = [p for p in tl if cutoff < p['time'] <= cp]
            if len(window) < 2: continue
            w_net = sum(p['net'] for p in window)
            w_chg = round((window[-1]['price'] - window[0]['price']) / window[0]['price'] * 100, 2) if window[0]['price'] > 0 else 0
            pts_now = [p for p in tl if p['time'] <= cp]
            chg_now = round((pts_now[-1]['price'] - open_p) / open_p * 100, 2) if open_p > 0 else 0

            if w_net > 100 and w_chg > 0.3 and first_opp is None:
                first_opp = (cp, chg_now, w_net, w_chg)
            if w_net < -100 and w_chg < -0.3 and first_risk is None:
                first_risk = (cp, chg_now, w_net, w_chg)

        if first_opp:
            print(f"  {w:>2}分钟窗口: 首次🟢机会 @ {first_opp[0]}  当时涨幅={first_opp[1]:>+.2f}%  窗口净流={first_opp[2]:>+.0f}万")
        else:
            print(f"  {w:>2}分钟窗口: 全天未识别为🟢机会")
        if first_risk:
            print(f"  {w:>2}分钟窗口: 首次🔴风险 @ {first_risk[0]}  当时涨幅={first_risk[1]:>+.2f}%  窗口净流={first_risk[2]:>+.0f}万")

if __name__ == '__main__':
    main()
