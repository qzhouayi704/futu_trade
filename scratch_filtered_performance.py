#!/usr/bin/env python3
"""
被共振过滤的股票 — 后续表现分析

检查被过滤的股票在信号触发后的价格走势：
- 信号时买入，15分钟/30分钟/60分钟/收盘时卖出的收益
- 对比共振通过的股票同样指标
"""
import sqlite3, os
from collections import defaultdict

DB_PATH = os.environ.get("DB_PATH", "/opt/futu_trade_sys/simple_trade/data/trade.db")

# === 复用 resonance filter check 的核心逻辑 ===
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
                if can('reversal_bull', False):
                    emit('reversal_bull', False)
            if prev_dir == 'positive' and curr_dir == 'negative' and p['cum_net'] < -rev_min:
                if can('reversal_bear', True):
                    emit('reversal_bear', True)
            if i >= 6:
                recent_3 = sum(timeline[j]['net'] for j in range(i-2, i+1))
                prev_3 = sum(timeline[j]['net'] for j in range(i-5, i-2))
                if prev_3 > 0 and recent_3 > prev_3 * ACCEL_THRESHOLD and recent_3 > accel_min:
                    if can('accel_in', False):
                        emit('accel_in', False)
            if i >= SUSTAINED_MINUTES:
                window_net = sum(timeline[j]['net'] for j in range(i - SUSTAINED_MINUTES + 1, i + 1))
                if window_net < -dyn_sustained:
                    if can('sustained_out', True):
                        emit('sustained_out', True)
            prev_dir = curr_dir
    return signals


def check_resonance(signals):
    can_pass = False
    for sig in signals:
        if sig['is_red']:
            continue
        idx = sig['idx']
        cutoff = max(0, idx - RESONANCE_WINDOW)
        recent_buys = [s for s in signals if not s['is_red'] and cutoff <= s['idx'] <= idx]
        green_types = set(s['type'] for s in recent_buys)
        if len(green_types) >= 2:
            can_pass = True
            break
        if sig.get('strength', 0) >= 80:
            can_pass = True
            break
    return can_pass


def get_price_at_offset(timeline, signal_idx, offset):
    """获取信号后offset分钟的价格"""
    target = min(signal_idx + offset, len(timeline) - 1)
    if target <= signal_idx:
        return None
    p = timeline[target]['price']
    return p if p > 0 else None


def get_close_price(timeline):
    """获取收盘价(最后一个有效价格)"""
    for p in reversed(timeline):
        if p['price'] > 0:
            return p['price']
    return None


def calc_return(entry, exit_price):
    if not entry or not exit_price or entry <= 0:
        return None
    return round((exit_price - entry) / entry * 100, 2)


def main():
    db = sqlite3.connect(DB_PATH)

    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date DESC LIMIT 7"
    ).fetchall()]
    dates.sort()
    print(f"分析日期: {dates[0]} ~ {dates[-1]} ({len(dates)}天)")
    print(f"{'='*100}")

    filtered_stocks = []  # 被过滤的
    passed_stocks = []    # 通过的(作为对照组)

    for trade_date in dates:
        codes = [r[0] for r in db.execute(
            "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date=?",
            (trade_date,)
        ).fetchall()]

        for code in codes:
            tl = load_minute_data(db, code, trade_date)
            if len(tl) < 10:
                continue

            sigs = detect_signals(tl)
            green_sigs = [s for s in sigs if not s['is_red']]
            if not green_sigs:
                continue

            can_pass = check_resonance(sigs)

            # 取第一个绿色信号作为入场点
            first_green = green_sigs[0]
            entry_price = first_green['price']
            entry_idx = first_green['idx']

            if entry_price <= 0:
                continue

            # 计算后续收益
            p15 = get_price_at_offset(tl, entry_idx, 15)
            p30 = get_price_at_offset(tl, entry_idx, 30)
            p60 = get_price_at_offset(tl, entry_idx, 60)
            close = get_close_price(tl)

            # 最高价(信号后)
            max_price = 0
            for j in range(entry_idx, len(tl)):
                if tl[j]['price'] > 0:
                    max_price = max(max_price, tl[j]['price'])

            record = {
                'date': trade_date,
                'code': code,
                'signal_type': first_green['type'],
                'signal_time': first_green['time'],
                'entry_price': entry_price,
                'ret_15m': calc_return(entry_price, p15),
                'ret_30m': calc_return(entry_price, p30),
                'ret_60m': calc_return(entry_price, p60),
                'ret_close': calc_return(entry_price, close),
                'ret_max': calc_return(entry_price, max_price) if max_price > 0 else None,
                'green_types': list(set(g['type'] for g in green_sigs)),
                'red_types': list(set(s['type'] for s in sigs if s['is_red'])),
            }

            if can_pass:
                passed_stocks.append(record)
            else:
                filtered_stocks.append(record)

    db.close()

    # === 报告1: 被过滤股票详细后续表现 ===
    print(f"\n{'='*100}")
    print(f"  被共振过滤的股票: 信号触发后的价格表现 ({len(filtered_stocks)}只)")
    print(f"{'='*100}")

    # 按max_gain排序
    filtered_stocks.sort(key=lambda x: -(x['ret_max'] or 0))

    print(f"\n  {'日期':<12} {'股票':<12} {'信号':<14} {'时间':<6} {'入场价':<8}"
          f" {'15m':>6} {'30m':>6} {'60m':>6} {'收盘':>6} {'最高':>6} {'红色信号'}")
    print(f"  {'-'*110}")

    for s in filtered_stocks:
        red = ','.join(s['red_types']) if s['red_types'] else '-'
        def fmt(v):
            if v is None: return '  N/A'
            return f"{v:+.1f}%"
        print(f"  {s['date']:<12} {s['code']:<12} {s['signal_type']:<14} {s['signal_time']:<6} "
              f"{s['entry_price']:<8.3f} {fmt(s['ret_15m']):>6} {fmt(s['ret_30m']):>6} "
              f"{fmt(s['ret_60m']):>6} {fmt(s['ret_close']):>6} {fmt(s['ret_max']):>6} {red}")

    # 汇总统计
    def stats(records, field):
        vals = [r[field] for r in records if r[field] is not None]
        if not vals:
            return 0, 0, 0
        avg = sum(vals) / len(vals)
        win = sum(1 for v in vals if v > 0)
        win_rate = win / len(vals) * 100
        return avg, win_rate, len(vals)

    print(f"\n  --- 被过滤股票汇总 ({len(filtered_stocks)}只) ---")
    for label, field in [('15分钟', 'ret_15m'), ('30分钟', 'ret_30m'),
                          ('60分钟', 'ret_60m'), ('收盘', 'ret_close'), ('最高', 'ret_max')]:
        avg, wr, n = stats(filtered_stocks, field)
        print(f"  {label}: 平均={avg:+.2f}%  胜率={wr:.0f}%  样本={n}")

    # === 报告2: 对照组 — 共振通过的股票同样统计 ===
    print(f"\n{'='*100}")
    print(f"  对照组: 共振通过的股票同样指标 ({len(passed_stocks)}只)")
    print(f"{'='*100}")

    print(f"\n  --- 共振通过股票汇总 ({len(passed_stocks)}只) ---")
    for label, field in [('15分钟', 'ret_15m'), ('30分钟', 'ret_30m'),
                          ('60分钟', 'ret_60m'), ('收盘', 'ret_close'), ('最高', 'ret_max')]:
        avg, wr, n = stats(passed_stocks, field)
        print(f"  {label}: 平均={avg:+.2f}%  胜率={wr:.0f}%  样本={n}")

    # === 报告3: 直接对比 ===
    print(f"\n{'='*100}")
    print(f"  直接对比: 被过滤 vs 通过")
    print(f"{'='*100}")

    print(f"\n  {'指标':<10} {'被过滤(avg)':>12} {'被过滤(胜率)':>14} {'通过(avg)':>12} {'通过(胜率)':>14} {'判定'}")
    print(f"  {'-'*80}")

    for label, field in [('15分钟', 'ret_15m'), ('30分钟', 'ret_30m'),
                          ('60分钟', 'ret_60m'), ('收盘', 'ret_close')]:
        f_avg, f_wr, _ = stats(filtered_stocks, field)
        p_avg, p_wr, _ = stats(passed_stocks, field)
        if f_avg < p_avg:
            verdict = "✅ 过滤合理"
        elif f_avg > p_avg * 1.5:
            verdict = "❌ 错过机会"
        else:
            verdict = "🟡 接近"
        print(f"  {label:<10} {f_avg:>+10.2f}% {f_wr:>12.0f}% {p_avg:>+10.2f}% {p_wr:>12.0f}% {verdict}")


if __name__ == '__main__':
    main()
