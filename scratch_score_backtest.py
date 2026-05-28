#!/usr/bin/env python3
"""
双窗口最优参数搜索
短窗口: 1/3/5/10 分钟 (捕捉突发)
长窗口: 10/15/20/30 分钟 (捕捉趋势)

评估指标:
1. 机会命中率: 识别为机会后，未来10分钟是否涨
2. 风险命中率: 识别为风险后，未来10分钟是否跌
3. 首次捕捉时机: 对当天涨幅TOP股票，最早识别为机会的时间点
"""
import sqlite3
from collections import defaultdict

DB_PATH = 'simple_trade/data/trade.db'

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
            e['price'] += float(avg_price); e['price_n'] += 1
    timeline = []
    cum_buy, cum_sell = 0, 0
    for minute in sorted(minutes.keys()):
        e = minutes[minute]
        cum_buy += e['buy']; cum_sell += e['sell']
        net = e['buy'] - e['sell']
        price = round(e['price'] / e['price_n'], 3) if e['price_n'] > 0 else 0
        timeline.append({
            'time': minute, 'net': round(net / 10000, 1),
            'cum_net': round((cum_buy - cum_sell) / 10000, 1),
            'price': price,
        })
    return timeline

def sub_min(hhmm, mins):
    h, m = int(hhmm[:2]), int(hhmm[3:])
    total = h * 60 + m - mins
    if total < 0: total = 0
    return f"{total // 60:02d}:{total % 60:02d}"

def add_min(hhmm, mins):
    h, m = int(hhmm[:2]), int(hhmm[3:])
    total = h * 60 + m + mins
    return f"{total // 60:02d}:{total % 60:02d}"

def eval_window(all_tl, short_w, long_w, stock_day_chg, stock_names):
    """评估一组窗口参数"""
    # 阈值根据窗口大小动态调整
    # 短窗口用更低阈值(突发异动)，长窗口用更高阈值(趋势)
    short_flow_thresh = max(30, short_w * 20)  # 1分钟=30万, 5分钟=100万, 10分钟=200万
    long_flow_thresh = max(100, long_w * 10)   # 10分钟=100万, 15分钟=150万, 30分钟=300万
    short_chg_thresh = 0.2   # 短窗口价格变化阈值低
    long_chg_thresh = 0.3

    opp_hits = 0; opp_total = 0
    risk_hits = 0; risk_total = 0
    # 对涨幅TOP10, 记录首次识别时间和涨幅
    top10_codes = [c for c, _ in sorted(stock_day_chg.items(), key=lambda x: -x[1])[:10]]
    first_capture = {}  # code -> (time, chg_at_time)

    all_minutes = sorted(set(p['time'] for tl in all_tl.values() for p in tl))

    for t in all_minutes:
        if t < '09:35': continue

        for code, tl in all_tl.items():
            pts = [p for p in tl if p['time'] <= t]
            if len(pts) < 3: continue
            open_p = tl[0]['price']
            cur_p = pts[-1]['price']
            if open_p <= 0 or cur_p <= 0: continue
            chg_now = (cur_p - open_p) / open_p * 100

            # 短窗口
            s_cut = sub_min(t, short_w)
            s_win = [p for p in tl if s_cut < p['time'] <= t]
            # 长窗口
            l_cut = sub_min(t, long_w)
            l_win = [p for p in tl if l_cut < p['time'] <= t]

            is_opp = False; is_risk = False

            for win, f_thresh, c_thresh in [(s_win, short_flow_thresh, short_chg_thresh),
                                             (l_win, long_flow_thresh, long_chg_thresh)]:
                if len(win) < 2: continue
                w_net = sum(p['net'] for p in win)
                w_chg = (win[-1]['price'] - win[0]['price']) / win[0]['price'] * 100 if win[0]['price'] > 0 else 0
                if w_net > f_thresh and w_chg > c_thresh:
                    is_opp = True
                if w_net < -f_thresh and w_chg < -c_thresh:
                    is_risk = True

            # 评估: 未来10分钟表现
            f_t = add_min(t, 10)
            future = [p for p in tl if t < p['time'] <= f_t]
            if len(future) < 3: continue
            f_chg = (future[-1]['price'] - pts[-1]['price']) / pts[-1]['price'] * 100

            if is_opp:
                opp_total += 1
                if f_chg > 0: opp_hits += 1
                # 记录TOP10的首次捕捉
                if code in top10_codes and code not in first_capture:
                    first_capture[code] = (t, round(chg_now, 2))

            if is_risk:
                risk_total += 1
                if f_chg < 0: risk_hits += 1

    opp_rate = opp_hits / opp_total * 100 if opp_total > 0 else 0
    risk_rate = risk_hits / risk_total * 100 if risk_total > 0 else 0
    capture_rate = len(first_capture) / len(top10_codes) * 100 if top10_codes else 0

    return {
        'opp_rate': opp_rate, 'opp_n': opp_total,
        'risk_rate': risk_rate, 'risk_n': risk_total,
        'capture_rate': capture_rate,
        'captures': first_capture,
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    # 只用数据量足够的日期
    dates = conn.execute(
        "SELECT trade_date, COUNT(DISTINCT stock_code) as n FROM ticker_data "
        "GROUP BY trade_date HAVING n > 100 ORDER BY trade_date"
    ).fetchall()

    short_windows = [1, 3, 5, 10]
    long_windows = [10, 15, 20, 30]

    # 全量结果
    combo_results = defaultdict(lambda: {'opp_hits': 0, 'opp_total': 0, 'risk_hits': 0, 'risk_total': 0,
                                          'capture_total': 0, 'capture_n': 0, 'captures': []})

    for trade_date, n_stocks in dates:
        codes = [r[0] for r in conn.execute(
            "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date=?", (trade_date,)
        ).fetchall()]

        # 预加载数据
        all_tl = {}
        stock_names = {}
        for code in codes:
            tl = load_minute_data(conn, code, trade_date)
            if len(tl) >= 15:
                all_tl[code] = tl
                row = conn.execute("SELECT name FROM stocks WHERE code=?", (code,)).fetchone()
                stock_names[code] = row[0] if row else code

        stock_day_chg = {}
        for code, tl in all_tl.items():
            if tl[0]['price'] > 0 and tl[-1]['price'] > 0:
                stock_day_chg[code] = round((tl[-1]['price'] - tl[0]['price']) / tl[0]['price'] * 100, 2)

        print(f"\n📅 {trade_date} ({len(all_tl)} stocks)")

        for sw in short_windows:
            for lw in long_windows:
                if sw >= lw: continue  # 短窗口必须小于长窗口
                result = eval_window(all_tl, sw, lw, stock_day_chg, stock_names)
                key = (sw, lw)
                cr = combo_results[key]
                cr['opp_hits'] += int(result['opp_rate'] * result['opp_n'] / 100)
                cr['opp_total'] += result['opp_n']
                cr['risk_hits'] += int(result['risk_rate'] * result['risk_n'] / 100)
                cr['risk_total'] += result['risk_n']
                cr['capture_n'] += 10  # top10
                cr['capture_total'] += int(result['capture_rate'] / 10)
                cr['captures'].append((trade_date, result['captures']))

                print(f"  短={sw:>2}m 长={lw:>2}m  "
                      f"🟢命中={result['opp_rate']:>5.1f}%({result['opp_n']:>4})  "
                      f"🔴命中={result['risk_rate']:>5.1f}%({result['risk_n']:>4})  "
                      f"TOP10捕获={result['capture_rate']:>4.0f}%")

    # ====== 汇总排名 ======
    print(f"\n{'='*90}")
    print(f"📊 全量汇总排名 (按 机会命中率 + 风险命中率 综合排序)")
    print(f"{'='*90}")
    print(f"{'短窗口':>6} {'长窗口':>6}  {'🟢机会命中':>10}  {'🔴风险命中':>10}  {'TOP10捕获':>10}  {'综合分':>6}")

    ranked = []
    for (sw, lw), cr in combo_results.items():
        opp_rate = cr['opp_hits'] / cr['opp_total'] * 100 if cr['opp_total'] > 0 else 0
        risk_rate = cr['risk_hits'] / cr['risk_total'] * 100 if cr['risk_total'] > 0 else 0
        # 综合分 = 机会命中率×0.5 + 风险命中率×0.3 + TOP10捕获×0.2
        cap_rate = cr['capture_total'] / cr['capture_n'] * 100 if cr['capture_n'] > 0 else 0
        combo_score = opp_rate * 0.5 + risk_rate * 0.3 + cap_rate * 0.2
        ranked.append((sw, lw, opp_rate, cr['opp_total'], risk_rate, cr['risk_total'], cap_rate, combo_score))

    ranked.sort(key=lambda x: -x[7])
    for sw, lw, opp_r, opp_n, risk_r, risk_n, cap_r, score in ranked:
        marker = " ⭐" if ranked.index((sw, lw, opp_r, opp_n, risk_r, risk_n, cap_r, score)) == 0 else ""
        print(f"  {sw:>3}m  {lw:>4}m  "
              f"{opp_r:>5.1f}%({opp_n:>5})  "
              f"{risk_r:>5.1f}%({risk_n:>5})  "
              f"{cap_r:>5.1f}%        "
              f"{score:>5.1f}{marker}")

    # 输出最佳组合的 TOP10 捕获详情
    best = ranked[0]
    best_key = (best[0], best[1])
    print(f"\n🏆 最佳组合: 短={best[0]}m + 长={best[1]}m")
    print(f"   机会命中率={best[2]:.1f}%  风险命中率={best[4]:.1f}%")
    for trade_date, captures in combo_results[best_key]['captures']:
        if captures:
            print(f"\n   {trade_date} 首次捕获:")
            for code, (t, chg) in sorted(captures.items(), key=lambda x: x[1][0]):
                name = stock_names.get(code, code)
                day_chg = stock_day_chg.get(code, 0)
                print(f"     {t} 🟢 {name:<14} 当时涨幅={chg:>+.2f}%  全天={day_chg:>+.2f}%")

if __name__ == '__main__':
    main()
