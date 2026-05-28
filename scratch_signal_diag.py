#!/usr/bin/env python3
"""
信号诊断 — 分析信号质量与时机
1. 每日涨幅TOP股票是否被预警到?
2. 信号触发时机是否在启动初期?
"""
import sqlite3, os
from collections import defaultdict

DB_PATH = os.environ.get("DB_PATH", "/opt/futu_trade_sys/simple_trade/data/trade.db")

# 复用回测参数
MEGA_MULTIPLIER = 3
SCAN_INTERVAL = 3
COOLDOWN_MINUTES = 15
CONFLICT_WINDOW = 15
SUSTAINED_RATIO = 0.35
SUSTAINED_MINUTES = 20
ACCEL_THRESHOLD = 3.0
TIER_THRESHOLDS = {
    'large': (50000, 3000, 5000, 5000),
    'mid':   (10000, 1500, 2000, 2000),
    'small': (1000,  500,  800,  500),
}
SNIPER_STRENGTH = {
    'mega_buy': 90, 'accel_in': 0, 'reversal_bull': 0,
    'mega_sell': 95, 'reversal_bear': 30, 'sustained_out': 20,
}


def load_minute_data(db, stock_code, trade_date):
    rows = db.execute("""
        SELECT substr(datetime(timestamp/1000,'unixepoch','+8 hours'),12,5) as minute,
               direction, SUM(turnover) as tv, AVG(price) as ap
        FROM ticker_data WHERE stock_code=? AND trade_date=?
        GROUP BY minute, direction ORDER BY minute
    """, (stock_code, trade_date)).fetchall()
    minutes = {}
    for minute, direction, turnover, avg_price in rows:
        if not ('09:15' <= minute <= '16:10'): continue
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


def get_tier(day_total):
    for _, (min_tv, a, m, r) in TIER_THRESHOLDS.items():
        if day_total >= min_tv: return a, m, r
    return 500, 800, 500


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
        accel_min, mega_min, rev_min = get_tier(day_total)
        abs_nets = [abs(x['net']) for x in past if x['net'] != 0]
        avg_abs = sum(abs_nets)/len(abs_nets) if abs_nets else avg_tv
        dyn_mega = max(mega_min, avg_abs * MEGA_MULTIPLIER)
        dyn_sustained = max(SUSTAINED_RATIO * avg_tv * SUSTAINED_MINUTES, mega_min * 0.6)

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
            while recent and recent[0][2] < cut: recent.pop(0)
            signals.append({
                'time': p['time'], 'is_red': red, 'idx': i,
                'type': st, 'price': p['price'],
            })

        is_scan = (i % SCAN_INTERVAL == 0 and i > 0)

        if p['net'] < -dyn_mega and can('mega_sell', True): emit('mega_sell', True)
        if p['net'] > dyn_mega and can('mega_buy', False): emit('mega_buy', False)

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


def analyze_price_action(timeline):
    """分析价格走势: 开盘价、最高价、最低价、收盘价、最大涨幅"""
    prices = [p['price'] for p in timeline if p['price'] > 0]
    if len(prices) < 5: return None
    open_p = prices[0]
    close_p = prices[-1]
    high_p = max(prices)
    low_p = min(prices)
    # 找到最高价的时间点
    high_idx = next(i for i, p in enumerate(timeline) if p['price'] == high_p)
    low_idx = next(i for i, p in enumerate(timeline) if p['price'] == low_p)
    high_time = timeline[high_idx]['time']
    low_time = timeline[low_idx]['time']
    # 最大涨幅 = (最高 - 开盘) / 开盘
    max_gain = (high_p - open_p) / open_p * 100 if open_p > 0 else 0
    # 从最低到最高的潜在利润
    if low_idx < high_idx and low_p > 0:
        potential = (high_p - low_p) / low_p * 100
    else:
        potential = max_gain
    day_change = (close_p - open_p) / open_p * 100 if open_p > 0 else 0
    return {
        'open': open_p, 'high': high_p, 'low': low_p, 'close': close_p,
        'high_time': high_time, 'high_idx': high_idx,
        'low_time': low_time, 'low_idx': low_idx,
        'max_gain': max_gain, 'potential': potential,
        'day_change': day_change, 'total_minutes': len(timeline),
    }


def main():
    db = sqlite3.connect(DB_PATH)
    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date ASC"
    ).fetchall()]

    print(f"{'='*100}")
    print(f"  信号诊断报告 — 预警质量 & 买卖时机分析")
    print(f"  回测期间: {dates[0]} ~ {dates[-1]} ({len(dates)}天)")
    print(f"{'='*100}")

    for trade_date in dates:
        codes = [r[0] for r in db.execute(
            "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date=?", (trade_date,)
        ).fetchall()]

        day_stocks = []
        for code in codes:
            tl = load_minute_data(db, code, trade_date)
            if len(tl) < 10: continue
            pa = analyze_price_action(tl)
            if pa is None: continue
            sigs = detect_signals(tl)
            green_sigs = [s for s in sigs if not s['is_red']]
            red_sigs = [s for s in sigs if s['is_red']]
            # 共振检查
            has_resonance = False
            green_types = set(s['type'] for s in green_sigs)
            if len(green_types) >= 2:
                # 检查15分钟窗口内是否有2种
                for s in green_sigs:
                    cutoff = max(0, s['idx'] - 15)
                    window_types = set(x['type'] for x in green_sigs if x['idx'] >= cutoff and x['idx'] <= s['idx'])
                    if len(window_types) >= 2:
                        has_resonance = True; break

            first_green_time = green_sigs[0]['time'] if green_sigs else '-'
            first_green_price = green_sigs[0]['price'] if green_sigs else 0
            first_green_idx = green_sigs[0]['idx'] if green_sigs else -1

            # 信号时机评估: 第一个绿色信号vs最高价的关系
            if first_green_idx >= 0 and pa['high_idx'] > 0 and first_green_price > 0:
                # 信号后的最大收益
                remaining_high = max((p['price'] for p in tl[first_green_idx:] if p['price'] > 0), default=first_green_price)
                signal_upside = (remaining_high - first_green_price) / first_green_price * 100
                timing_pct = first_green_idx / pa['total_minutes'] * 100  # 信号在全天的位置
            else:
                signal_upside = 0
                timing_pct = -1

            day_stocks.append({
                'code': code, 'pa': pa, 'sigs': sigs,
                'green_sigs': green_sigs, 'red_sigs': red_sigs,
                'green_types': green_types, 'has_resonance': has_resonance,
                'first_green_time': first_green_time,
                'first_green_price': first_green_price,
                'signal_upside': signal_upside,
                'timing_pct': timing_pct,
            })

        # 按日涨幅排序，取TOP 5
        day_stocks.sort(key=lambda x: -x['pa']['max_gain'])
        top5 = day_stocks[:5] if len(day_stocks) >= 5 else day_stocks

        print(f"\n{'─'*100}")
        print(f"  📅 {trade_date}  (共 {len(day_stocks)} 只活跃股票)")
        print(f"{'─'*100}")
        print(f"  {'股票':<12} {'日涨幅':>7} {'最大涨幅':>8} {'开盘':>8} {'最高':>8}({'时间':<5}) {'收盘':>8} "
              f"{'信号数':>5} {'类型':>20} {'共振':>4} {'首信号':>6} {'信号后涨幅':>10}")
        print(f"  {'─'*95}")

        for s in top5:
            pa = s['pa']
            types_str = '+'.join(sorted(s['green_types'])) if s['green_types'] else '-'
            res = '✅' if s['has_resonance'] else '❌'
            upside = f"+{s['signal_upside']:.1f}%" if s['signal_upside'] > 0 else f"{s['signal_upside']:.1f}%"

            print(f"  {s['code']:<12} {pa['day_change']:>+6.1f}% {pa['max_gain']:>+7.1f}% "
                  f"${pa['open']:>7.3f} ${pa['high']:>7.3f}({pa['high_time']:<5}) ${pa['close']:>7.3f} "
                  f"{len(s['green_sigs']):>5} {types_str:>20} {res:>4} {s['first_green_time']:>6} {upside:>10}")

        # 展示每只TOP股票的信号时间线
        for s in top5:
            if not s['sigs']: continue
            pa = s['pa']
            print(f"\n  📊 {s['code']} 信号时间线 (开盘${pa['open']:.3f} → 最高${pa['high']:.3f}@{pa['high_time']} → 收盘${pa['close']:.3f})")
            for sig in s['sigs']:
                emoji = '🔴' if sig['is_red'] else '🟢'
                pos_pct = sig['idx'] / pa['total_minutes'] * 100
                vs_high = (sig['price'] / pa['high'] - 1) * 100 if pa['high'] > 0 else 0
                vs_open = (sig['price'] / pa['open'] - 1) * 100 if pa['open'] > 0 else 0
                print(f"    {emoji} {sig['time']} {sig['type']:<16} @${sig['price']:.3f} "
                      f"(vs开盘{vs_open:+.1f}% vs最高{vs_high:+.1f}% 位置{pos_pct:.0f}%)")

    db.close()
    print(f"\n{'='*100}")
    print(f"  诊断完成")
    print(f"{'='*100}")


if __name__ == '__main__':
    main()
