#!/usr/bin/env python3
"""
精确回测 v2 — 只分析高涨幅股票(>3%)
买点 = multi_green共振确认时刻(第二个绿色信号的价格)
卖点 = 15m/30m/60m/收盘
"""
import sqlite3, os

DB_PATH = os.environ.get("DB_PATH", "/opt/futu_trade_sys/simple_trade/data/trade.db")

MEGA_MULTIPLIER = 3
SCAN_INTERVAL = 3
COOLDOWN_MINUTES = 15
CONFLICT_WINDOW = 15
SUSTAINED_RATIO = 0.35
SUSTAINED_MINUTES = 20
ACCEL_THRESHOLD = 3.0
MEGA_FLOOR_PCT = 0.02
MEGA_FLOOR_MIN = 50
SNIPER_STRENGTH = {
    'mega_buy': 90, 'accel_in': 0, 'reversal_bull': 0,
    'mega_sell': 95, 'reversal_bear': 30, 'sustained_out': 20,
}
RESONANCE_WINDOW = 15


def load_minute_data(db, stock_code, trade_date):
    rows = db.execute("""
        SELECT substr(datetime(timestamp/1000,'unixepoch','+8 hours'),12,5) as minute,
               direction, SUM(turnover) as tv, AVG(price) as ap
        FROM ticker_data WHERE stock_code=? AND trade_date=?
        GROUP BY minute, direction ORDER BY minute
    """, (stock_code, trade_date)).fetchall()
    minutes = {}
    for minute, direction, turnover, avg_price in rows:
        if not ('09:15' <= minute <= '16:10'):
            continue
        if minute not in minutes:
            minutes[minute] = {'buy': 0.0, 'sell': 0.0, 'price': 0, 'price_n': 0}
        e = minutes[minute]
        tv = float(turnover or 0)
        if direction == 'BUY': e['buy'] += tv
        elif direction == 'SELL': e['sell'] += tv
        if avg_price and float(avg_price) > 0:
            e['price'] += float(avg_price); e['price_n'] += 1
    timeline = []
    cum_buy, cum_sell = 0.0, 0.0
    for m in sorted(minutes.keys()):
        e = minutes[m]
        cum_buy += e['buy']; cum_sell += e['sell']
        net = e['buy'] - e['sell']
        price = round(e['price'] / e['price_n'], 3) if e['price_n'] > 0 else 0
        timeline.append({
            'time': m, 'net': round(net/10000, 1),
            'cum_net': round((cum_buy - cum_sell)/10000, 1),
            'price': price, 'turnover': round((e['buy']+e['sell'])/10000, 1),
        })
    return timeline


def detect_signals(timeline):
    signals = []
    cooldown = {}
    prev_dir = 'neutral'
    recent = []
    for i, p in enumerate(timeline):
        past = timeline[:i+1]
        day_total = sum(x['turnover'] for x in past)
        if day_total < 100: continue
        tvs = [x['turnover'] for x in past if x['turnover'] > 0]
        avg_tv = sum(tvs)/len(tvs) if tvs else 0
        if avg_tv <= 0: continue
        mega_floor = max(MEGA_FLOOR_MIN, day_total * MEGA_FLOOR_PCT)
        abs_nets = [abs(x['net']) for x in past if x['net'] != 0]
        avg_abs = sum(abs_nets)/len(abs_nets) if abs_nets else avg_tv
        dyn_mega = max(mega_floor, avg_abs * MEGA_MULTIPLIER)
        accel_min = mega_floor * 0.5
        rev_min = mega_floor
        dyn_sustained = max(SUSTAINED_RATIO * avg_tv * SUSTAINED_MINUTES, mega_floor * 0.6)

        def can(st, red):
            if st in cooldown and i - cooldown[st] < COOLDOWN_MINUTES: return False
            cut = max(0, i - CONFLICT_WINDOW)
            for _, r_red, r_idx in recent:
                if r_idx >= cut and ((red and not r_red) or (not red and r_red)): return False
            return True

        def emit(st, red):
            cooldown[st] = i
            recent.append((p['time'], red, i))
            cut = max(0, i - CONFLICT_WINDOW * 2)
            while recent and recent[0][2] < cut:
                recent.pop(0)
            signals.append({
                'time': p['time'], 'is_red': red, 'idx': i,
                'type': st, 'price': p['price'],
                'strength': SNIPER_STRENGTH.get(st, 0),
                'net': p['net'],
            })

        is_scan = (i % SCAN_INTERVAL == 0 and i > 0)
        if p['net'] < -dyn_mega and can('mega_sell', True):
            emit('mega_sell', True)
        if p['net'] > dyn_mega and can('mega_buy', False):
            emit('mega_buy', False)
        if is_scan:
            curr_dir = 'positive' if p['cum_net'] > 0 else ('negative' if p['cum_net'] < 0 else 'neutral')
            if prev_dir == 'negative' and curr_dir == 'positive' and p['cum_net'] > rev_min:
                if can('reversal_bull', False): emit('reversal_bull', False)
            if prev_dir == 'positive' and curr_dir == 'negative' and p['cum_net'] < -rev_min:
                if can('reversal_bear', True): emit('reversal_bear', True)
            if i >= 6:
                recent_3 = sum(timeline[j]['net'] for j in range(i-2, i+1))
                prev_3 = sum(timeline[j]['net'] for j in range(i-5, i-2))
                if prev_3 > 0 and recent_3 > prev_3 * ACCEL_THRESHOLD and recent_3 > accel_min:
                    if can('accel_in', False): emit('accel_in', False)
            if i >= SUSTAINED_MINUTES:
                window_net = sum(timeline[j]['net'] for j in range(i - SUSTAINED_MINUTES + 1, i + 1))
                if window_net < -dyn_sustained:
                    if can('sustained_out', True): emit('sustained_out', True)
            prev_dir = curr_dir
    return signals


def find_resonance_entry(signals):
    """找到multi_green共振确认的那一刻(第二个绿色信号), 返回该信号"""
    green_sigs = [s for s in signals if not s['is_red']]
    for sig in green_sigs:
        idx = sig['idx']
        cutoff = max(0, idx - RESONANCE_WINDOW)
        recent_buys = [s for s in signals if not s['is_red'] and cutoff <= s['idx'] <= idx]
        green_types = set(s['type'] for s in recent_buys)
        if len(green_types) >= 2:
            return sig, 'multi_green', list(green_types)
        if sig.get('strength', 0) >= 80:
            return sig, 'strong_single', [sig['type']]
    return None, None, []


def get_max_gain(timeline):
    first_price = 0
    max_price = 0
    for p in timeline:
        if p['price'] > 0:
            if first_price == 0: first_price = p['price']
            max_price = max(max_price, p['price'])
    if first_price <= 0: return 0
    return round((max_price - first_price) / first_price * 100, 2)


def calc_return(entry, exit_p):
    if not entry or not exit_p or entry <= 0: return None
    return round((exit_p - entry) / entry * 100, 2)


def main():
    db = sqlite3.connect(DB_PATH)
    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date DESC LIMIT 7"
    ).fetchall()]
    dates.sort()
    print(f"分析日期: {dates[0]} ~ {dates[-1]} ({len(dates)}天)")
    print(f"{'='*110}")

    passed_high = []   # 高涨幅 + 共振通过
    filtered_high = [] # 高涨幅 + 被过滤

    for trade_date in dates:
        codes = [r[0] for r in db.execute(
            "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date=?",
            (trade_date,)
        ).fetchall()]

        for code in codes:
            tl = load_minute_data(db, code, trade_date)
            if len(tl) < 10: continue

            max_gain = get_max_gain(tl)
            if max_gain < 3:  # 只看高涨幅股票
                continue

            sigs = detect_signals(tl)
            green_sigs = [s for s in sigs if not s['is_red']]
            if not green_sigs: continue

            entry_sig, res_type, res_types = find_resonance_entry(sigs)

            if entry_sig:
                # 共振通过 — 买点=共振确认时刻
                entry_price = entry_sig['price']
                entry_idx = entry_sig['idx']
                if entry_price <= 0: continue

                p15 = tl[min(entry_idx+15, len(tl)-1)]['price'] if entry_idx+15 < len(tl) else None
                p30 = tl[min(entry_idx+30, len(tl)-1)]['price'] if entry_idx+30 < len(tl) else None
                p60 = tl[min(entry_idx+60, len(tl)-1)]['price'] if entry_idx+60 < len(tl) else None
                close = next((p['price'] for p in reversed(tl) if p['price'] > 0), None)
                max_p = max((p['price'] for p in tl[entry_idx:] if p['price'] > 0), default=0)

                passed_high.append({
                    'date': trade_date, 'code': code, 'max_gain': max_gain,
                    'res_type': res_type, 'res_types': res_types,
                    'entry_time': entry_sig['time'], 'entry_price': entry_price,
                    'entry_type': entry_sig['type'],
                    'ret_15m': calc_return(entry_price, p15),
                    'ret_30m': calc_return(entry_price, p30),
                    'ret_60m': calc_return(entry_price, p60),
                    'ret_close': calc_return(entry_price, close),
                    'ret_max': calc_return(entry_price, max_p) if max_p > 0 else None,
                })
            else:
                # 被过滤 — 假设在第一个绿色信号买入
                first = green_sigs[0]
                entry_price = first['price']
                entry_idx = first['idx']
                if entry_price <= 0: continue

                p15 = tl[min(entry_idx+15, len(tl)-1)]['price'] if entry_idx+15 < len(tl) else None
                p30 = tl[min(entry_idx+30, len(tl)-1)]['price'] if entry_idx+30 < len(tl) else None
                p60 = tl[min(entry_idx+60, len(tl)-1)]['price'] if entry_idx+60 < len(tl) else None
                close = next((p['price'] for p in reversed(tl) if p['price'] > 0), None)
                max_p = max((p['price'] for p in tl[entry_idx:] if p['price'] > 0), default=0)

                filtered_high.append({
                    'date': trade_date, 'code': code, 'max_gain': max_gain,
                    'entry_time': first['time'], 'entry_price': entry_price,
                    'entry_type': first['type'],
                    'green_types': [g['type'] for g in green_sigs],
                    'red_types': [s['type'] for s in sigs if s['is_red']],
                    'ret_15m': calc_return(entry_price, p15),
                    'ret_30m': calc_return(entry_price, p30),
                    'ret_60m': calc_return(entry_price, p60),
                    'ret_close': calc_return(entry_price, close),
                    'ret_max': calc_return(entry_price, max_p) if max_p > 0 else None,
                })

    db.close()

    # === 共振通过的高涨幅股详情 ===
    print(f"\n{'='*110}")
    print(f"  共振通过的高涨幅股票 ({len(passed_high)}只) — 买点=共振确认时刻")
    print(f"{'='*110}")

    passed_high.sort(key=lambda x: -x['max_gain'])

    print(f"\n  {'日期':<12} {'股票':<12} {'日涨幅':>7} {'共振':>14} {'买入信号':<14} {'买入时间':<6} {'买入价':<9}"
          f" {'15m':>6} {'30m':>6} {'60m':>6} {'收盘':>6} {'最高':>6}")
    print(f"  {'-'*120}")

    for s in passed_high[:30]:
        def fmt(v):
            if v is None: return '  N/A'
            return f"{v:+.1f}%"
        types_str = '+'.join(s['res_types'])
        print(f"  {s['date']:<12} {s['code']:<12} {s['max_gain']:>+6.1f}% {s['res_type']:<14} "
              f"{s['entry_type']:<14} {s['entry_time']:<6} {s['entry_price']:<9.3f}"
              f" {fmt(s['ret_15m']):>6} {fmt(s['ret_30m']):>6} {fmt(s['ret_60m']):>6}"
              f" {fmt(s['ret_close']):>6} {fmt(s['ret_max']):>6}")

    if len(passed_high) > 30:
        print(f"  ... 还有{len(passed_high)-30}只")

    # === 被过滤的高涨幅股详情 ===
    print(f"\n{'='*110}")
    print(f"  被共振过滤的高涨幅股票 ({len(filtered_high)}只) — 买点=第一个绿色信号")
    print(f"{'='*110}")

    filtered_high.sort(key=lambda x: -x['max_gain'])

    print(f"\n  {'日期':<12} {'股票':<12} {'日涨幅':>7} {'买入信号':<14} {'买入时间':<6} {'买入价':<9}"
          f" {'15m':>6} {'30m':>6} {'60m':>6} {'收盘':>6} {'最高':>6} {'红色信号'}")
    print(f"  {'-'*120}")

    for s in filtered_high:
        def fmt(v):
            if v is None: return '  N/A'
            return f"{v:+.1f}%"
        red = ','.join(set(s['red_types'])) if s['red_types'] else '-'
        print(f"  {s['date']:<12} {s['code']:<12} {s['max_gain']:>+6.1f}% "
              f"{s['entry_type']:<14} {s['entry_time']:<6} {s['entry_price']:<9.3f}"
              f" {fmt(s['ret_15m']):>6} {fmt(s['ret_30m']):>6} {fmt(s['ret_60m']):>6}"
              f" {fmt(s['ret_close']):>6} {fmt(s['ret_max']):>6} {red}")

    # === 汇总对比 ===
    def stats(records, field):
        vals = [r[field] for r in records if r[field] is not None]
        if not vals: return 0, 0, 0
        avg = sum(vals) / len(vals)
        win = sum(1 for v in vals if v > 0)
        wr = win / len(vals) * 100
        return avg, wr, len(vals)

    print(f"\n{'='*110}")
    print(f"  汇总对比 — 仅高涨幅股票(日内最大涨幅>3%)")
    print(f"{'='*110}")

    print(f"\n  共振通过 ({len(passed_high)}只):")
    for label, field in [('15分钟', 'ret_15m'), ('30分钟', 'ret_30m'),
                          ('60分钟', 'ret_60m'), ('收盘', 'ret_close'), ('信号后最高', 'ret_max')]:
        avg, wr, n = stats(passed_high, field)
        print(f"    {label}: 平均={avg:+.2f}%  胜率={wr:.0f}%  样本={n}")

    print(f"\n  被过滤 ({len(filtered_high)}只):")
    for label, field in [('15分钟', 'ret_15m'), ('30分钟', 'ret_30m'),
                          ('60分钟', 'ret_60m'), ('收盘', 'ret_close'), ('信号后最高', 'ret_max')]:
        avg, wr, n = stats(filtered_high, field)
        print(f"    {label}: 平均={avg:+.2f}%  胜率={wr:.0f}%  样本={n}")

    print(f"\n  直接对比:")
    print(f"  {'指标':<12} {'通过(avg)':>12} {'通过(胜率)':>12} {'过滤(avg)':>12} {'过滤(胜率)':>12} {'判定'}")
    print(f"  {'-'*75}")
    for label, field in [('15分钟', 'ret_15m'), ('30分钟', 'ret_30m'),
                          ('60分钟', 'ret_60m'), ('收盘', 'ret_close'), ('信号后最高', 'ret_max')]:
        p_avg, p_wr, _ = stats(passed_high, field)
        f_avg, f_wr, _ = stats(filtered_high, field)
        if p_avg > f_avg:
            verdict = "✅ 过滤合理"
        else:
            verdict = "❌ 错过机会"
        print(f"  {label:<12} {p_avg:>+10.2f}% {p_wr:>10.0f}% {f_avg:>+10.2f}% {f_wr:>10.0f}% {verdict}")

    # === 按涨幅分段看通过组的表现 ===
    print(f"\n{'='*110}")
    print(f"  共振通过组 — 按日内涨幅分段统计收盘收益")
    print(f"{'='*110}")

    bins = [(3, 5), (5, 8), (8, 12), (12, 20), (20, 50)]
    print(f"\n  {'涨幅区间':<10} {'数量':<6} {'收盘avg':>10} {'收盘胜率':>10} {'最高avg':>10} {'最高胜率':>10}")
    print(f"  {'-'*60}")
    for lo, hi in bins:
        sub = [s for s in passed_high if lo <= s['max_gain'] < hi]
        if not sub: continue
        c_avg, c_wr, _ = stats(sub, 'ret_close')
        m_avg, m_wr, _ = stats(sub, 'ret_max')
        print(f"  {lo}~{hi}%    {len(sub):<6} {c_avg:>+9.2f}% {c_wr:>9.0f}% {m_avg:>+9.2f}% {m_wr:>9.0f}%")


if __name__ == '__main__':
    main()
