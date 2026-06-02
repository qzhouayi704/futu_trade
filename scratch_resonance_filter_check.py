#!/usr/bin/env python3
"""
共振过滤回测 — 检查高涨幅股票是否被信号一致性仲裁过滤

目标: 找出近几天涨幅高的股票, 分析它们:
  1. 是否产生了sniper信号(mega_buy等)
  2. 信号是否通过了共振判断
  3. 被过滤的原因是什么

结论: 判断共振规则是否系统性过滤了高涨幅好股票
"""
import sqlite3, os
from collections import defaultdict

DB_PATH = os.environ.get("DB_PATH", "/opt/futu_trade_sys/simple_trade/data/trade.db")

# === Sniper参数 ===
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
                'dyn_mega': round(dyn_mega, 1),
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


def check_all_resonance(signals):
    """对每个绿色信号检查共振, 返回所有可能触发的共振"""
    results = []
    for sig in signals:
        if sig['is_red']:
            continue
        idx = sig['idx']

        # 规则2: strong_single (mega_buy strength=90 >= 80)
        # 这里需要 scorer >= 80, 我们分两种情况分析
        if sig.get('strength', 0) >= 80:
            results.append({
                'signal': sig,
                'resonance': 'strong_single',
                'needs_scorer': True,  # 标记: 需要scorer>=80才能通过
                'detail': f"strength={sig['strength']} >= 80, 但需scorer>=80",
            })

        # 规则3: multi_green (15分钟内2种以上sniper绿色信号)
        cutoff = max(0, idx - RESONANCE_WINDOW)
        recent_buys = [s for s in signals
                       if not s['is_red'] and cutoff <= s['idx'] <= idx]
        green_types = set(s['type'] for s in recent_buys)
        if len(green_types) >= 2:
            results.append({
                'signal': sig,
                'resonance': 'multi_green',
                'needs_scorer': False,
                'detail': f"绿色信号类型: {'+'.join(green_types)}",
            })

    return results


def get_day_gain(timeline):
    """计算日内涨幅: 最后价格 vs 第一个价格"""
    first_price, last_price = 0, 0
    for p in timeline:
        if p['price'] > 0:
            if first_price == 0:
                first_price = p['price']
            last_price = p['price']
    if first_price <= 0:
        return 0
    return round((last_price - first_price) / first_price * 100, 2)


def get_max_gain(timeline):
    """计算日内最大涨幅: 最高价 vs 开盘价"""
    first_price = 0
    max_price = 0
    for p in timeline:
        if p['price'] > 0:
            if first_price == 0:
                first_price = p['price']
            max_price = max(max_price, p['price'])
    if first_price <= 0:
        return 0
    return round((max_price - first_price) / first_price * 100, 2)


def main():
    db = sqlite3.connect(DB_PATH)

    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date DESC LIMIT 7"
    ).fetchall()]
    dates.sort()
    print(f"分析日期: {dates[0]} ~ {dates[-1]} ({len(dates)}天)")
    print(f"{'='*90}")

    # 收集所有股票每天的数据
    all_stock_days = []

    for trade_date in dates:
        codes = [r[0] for r in db.execute(
            "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date=?",
            (trade_date,)
        ).fetchall()]

        for code in codes:
            tl = load_minute_data(db, code, trade_date)
            if len(tl) < 10:
                continue
            gain = get_day_gain(tl)
            max_gain = get_max_gain(tl)
            sigs = detect_signals(tl)
            resonances = check_all_resonance(sigs)

            green_sigs = [s for s in sigs if not s['is_red']]
            red_sigs = [s for s in sigs if s['is_red']]

            # 检查共振是否能通过(不依赖scorer)
            can_pass_no_scorer = any(r['resonance'] == 'multi_green' for r in resonances)
            # 检查共振是否能通过(假设scorer>=80)
            can_pass_with_scorer = can_pass_no_scorer or any(
                r['resonance'] == 'strong_single' for r in resonances
            )

            all_stock_days.append({
                'date': trade_date,
                'code': code,
                'gain': gain,
                'max_gain': max_gain,
                'green_sigs': green_sigs,
                'red_sigs': red_sigs,
                'resonances': resonances,
                'can_pass_no_scorer': can_pass_no_scorer,
                'can_pass_with_scorer': can_pass_with_scorer,
                'timeline': tl,
            })

    db.close()

    # === 分析1: 高涨幅股票的信号和共振情况 ===
    print(f"\n{'='*90}")
    print(f"  分析1: 高涨幅股票(日内涨幅>3%)的信号与共振情况")
    print(f"{'='*90}")

    high_gain = [s for s in all_stock_days if s['max_gain'] >= 3]
    high_gain.sort(key=lambda x: -x['max_gain'])

    if not high_gain:
        print("  无涨幅>3%的股票")
    else:
        # 分类统计
        has_signal = [s for s in high_gain if s['green_sigs']]
        no_signal = [s for s in high_gain if not s['green_sigs']]
        has_signal_pass = [s for s in has_signal if s['can_pass_with_scorer']]
        has_signal_blocked = [s for s in has_signal if not s['can_pass_with_scorer']]
        has_signal_blocked_no_scorer = [s for s in has_signal
                                        if not s['can_pass_no_scorer'] and s['can_pass_with_scorer']]

        print(f"\n  高涨幅股票总数: {len(high_gain)}")
        print(f"  ├─ 有绿色信号: {len(has_signal)} ({len(has_signal)/len(high_gain)*100:.0f}%)")
        print(f"  │  ├─ 共振通过(含scorer): {len(has_signal_pass)} ({len(has_signal_pass)/max(len(has_signal),1)*100:.0f}%)")
        print(f"  │  │  ├─ multi_green(不需scorer): {len([s for s in has_signal if s['can_pass_no_scorer']])}")
        print(f"  │  │  └─ 仅strong_single(需scorer≥80): {len(has_signal_blocked_no_scorer)}")
        print(f"  │  └─ 共振全部失败: {len(has_signal_blocked)} ({len(has_signal_blocked)/max(len(has_signal),1)*100:.0f}%)")
        print(f"  └─ 无绿色信号: {len(no_signal)} ({len(no_signal)/len(high_gain)*100:.0f}%)")

        # 详细列出被过滤的高涨幅股票
        print(f"\n  --- 被共振过滤的高涨幅股票(有信号但不能交易) ---")
        for s in has_signal_blocked[:15]:
            green_types = [g['type'] for g in s['green_sigs']]
            red_types = [r['type'] for r in s['red_sigs']]
            print(f"  {s['date']} {s['code']:<12} 涨幅={s['gain']:+.1f}% 最高={s['max_gain']:+.1f}%")
            green_desc_parts = []
            for t in set(green_types):
                t_time = next((g['time'] for g in s['green_sigs'] if g['type'] == t), '?')
                green_desc_parts.append(f"{t}@{t_time}")
            print(f"    绿色: {', '.join(green_desc_parts)}")
            if red_types:
                print(f"    红色: {', '.join(set(red_types))}")
            print(f"    过滤原因: 仅有单类型信号, 无multi_green; 无scorer所以strong_single也不通")

        # 详细列出有信号且通过共振的
        print(f"\n  --- 共振通过的高涨幅股票(系统会交易) ---")
        for s in has_signal_pass[:10]:
            res_types = list(set(r['resonance'] for r in s['resonances']))
            green_types = list(set(g['type'] for g in s['green_sigs']))
            print(f"  {s['date']} {s['code']:<12} 涨幅={s['gain']:+.1f}% 最高={s['max_gain']:+.1f}%  共振={'+'.join(res_types)}  信号={'+'.join(green_types)}")

    # === 分析2: 按涨幅分段统计过滤率 ===
    print(f"\n{'='*90}")
    print(f"  分析2: 按涨幅分段统计共振过滤率")
    print(f"{'='*90}")

    bins = [(0, 1), (1, 3), (3, 5), (5, 8), (8, 12), (12, 20), (20, 100)]
    print(f"\n  {'涨幅区间':<10} {'总数':<6} {'有信号':<8} {'共振通过':<10} {'被过滤':<8} {'过滤率':<8} {'无信号':<8}")
    print(f"  {'-'*68}")

    for lo, hi in bins:
        subset = [s for s in all_stock_days if lo <= s['max_gain'] < hi]
        if not subset:
            continue
        has_sig = [s for s in subset if s['green_sigs']]
        passed = [s for s in has_sig if s['can_pass_with_scorer']]
        blocked = [s for s in has_sig if not s['can_pass_with_scorer']]
        no_sig = [s for s in subset if not s['green_sigs']]
        filter_rate = len(blocked) / max(len(has_sig), 1) * 100

        label = f"{lo}~{hi}%"
        print(f"  {label:<10} {len(subset):<6} {len(has_sig):<8} {len(passed):<10} {len(blocked):<8} {filter_rate:<7.0f}% {len(no_sig):<8}")

    # === 分析3: 冲突窗口过滤分析 ===
    print(f"\n{'='*90}")
    print(f"  分析3: 冲突窗口(CONFLICT_WINDOW)对高涨幅股票的影响")
    print(f"{'='*90}")

    conflict_filtered = 0
    conflict_examples = []
    for s in high_gain:
        sigs = detect_signals(s['timeline'])
        # 检查是否有绿色信号被冲突窗口压制
        for i, p in enumerate(s['timeline']):
            if p['price'] <= 0:
                continue
            past = s['timeline'][:i+1]
            day_total = sum(x['turnover'] for x in past)
            if day_total < 100:
                continue
            abs_nets = [abs(x['net']) for x in past if x['net'] != 0]
            avg_abs = sum(abs_nets)/len(abs_nets) if abs_nets else 0
            mega_floor = max(MEGA_FLOOR_MIN, day_total * MEGA_FLOOR_PCT)
            dyn_mega = max(mega_floor, avg_abs * MEGA_MULTIPLIER)

            if p['net'] > dyn_mega:
                # 这个分钟满足mega_buy条件, 但可能被冲突窗口压制
                actually_emitted = any(
                    sig['type'] == 'mega_buy' and sig['idx'] == i
                    for sig in sigs
                )
                if not actually_emitted:
                    conflict_filtered += 1
                    if len(conflict_examples) < 5:
                        # 查找冲突的红色信号
                        conflicting = [sig for sig in sigs
                                       if sig['is_red'] and max(0, i - CONFLICT_WINDOW) <= sig['idx'] <= i]
                        conflict_examples.append({
                            'date': s['date'], 'code': s['code'],
                            'time': p['time'], 'gain': s['max_gain'],
                            'net': p['net'], 'threshold': round(dyn_mega, 1),
                            'conflicting': conflicting,
                        })

    print(f"\n  高涨幅股票中, 满足mega_buy条件但被冲突窗口压制的信号: {conflict_filtered}个")
    for ex in conflict_examples:
        conf_desc = ', '.join(f"{c['type']}@{c['time']}" for c in ex['conflicting']) or '冷却期'
        print(f"  {ex['date']} {ex['code']} {ex['time']} 涨{ex['gain']:.1f}% "
              f"净买{ex['net']}万>{ex['threshold']}万 被压制: {conf_desc}")

    # === 分析4: 如果放宽共振规则, 能多抓多少高涨幅股? ===
    print(f"\n{'='*90}")
    print(f"  分析4: 如果放宽共振规则(mega_buy直接触发, 无需scorer), 效果如何?")
    print(f"{'='*90}")

    # mega_buy直接触发 vs 需要共振
    mega_only = [s for s in all_stock_days
                 if any(g['type'] == 'mega_buy' for g in s['green_sigs'])]
    mega_pass_current = [s for s in mega_only if s['can_pass_with_scorer']]
    mega_blocked = [s for s in mega_only if not s['can_pass_with_scorer']]

    print(f"\n  有mega_buy信号的股票: {len(mega_only)}")
    print(f"  当前共振能通过: {len(mega_pass_current)}")
    print(f"  被过滤(仅有mega_buy无其他绿色): {len(mega_blocked)}")

    if mega_blocked:
        # 统计被过滤的mega_buy后续走势
        gains_after = []
        for s in mega_blocked:
            for sig in s['green_sigs']:
                if sig['type'] != 'mega_buy':
                    continue
                idx = sig['idx']
                # 信号后15分钟的价格变化
                target = min(idx + 15, len(s['timeline']) - 1)
                if target <= idx:
                    continue
                if sig['price'] <= 0 or s['timeline'][target]['price'] <= 0:
                    continue
                pct = (s['timeline'][target]['price'] - sig['price']) / sig['price'] * 100
                gains_after.append({
                    'date': s['date'], 'code': s['code'],
                    'time': sig['time'], 'gain': s['max_gain'],
                    'pct_15m': round(pct, 2),
                })

        if gains_after:
            avg_pct = sum(g['pct_15m'] for g in gains_after) / len(gains_after)
            win = sum(1 for g in gains_after if g['pct_15m'] > 0)
            win_rate = win / len(gains_after) * 100
            print(f"\n  被过滤的mega_buy信号后续15分钟表现:")
            print(f"    样本: {len(gains_after)}个")
            print(f"    平均收益: {avg_pct:+.3f}%")
            print(f"    胜率: {win_rate:.1f}%")
            print(f"    → {'✅ 过滤合理(后续表现差)' if avg_pct < 0 or win_rate < 50 else '❌ 过滤不合理! 错过盈利机会'}")

            # 列出详细
            gains_after.sort(key=lambda x: -x['pct_15m'])
            print(f"\n    详细(按后续收益排序):")
            for g in gains_after[:10]:
                marker = '🟢' if g['pct_15m'] > 0 else '🔴'
                print(f"    {marker} {g['date']} {g['code']} @{g['time']} 日涨{g['gain']:.1f}% 后续15m={g['pct_15m']:+.2f}%")
            if len(gains_after) > 10:
                print(f"    ... 还有{len(gains_after)-10}条")

    # === 总结 ===
    print(f"\n{'='*90}")
    print(f"  总结")
    print(f"{'='*90}")

    total_high = len(high_gain)
    total_has_sig = len([s for s in high_gain if s['green_sigs']])
    total_passed = len([s for s in high_gain if s['green_sigs'] and s['can_pass_with_scorer']])
    total_blocked = total_has_sig - total_passed
    total_no_sig = total_high - total_has_sig

    if total_high > 0:
        print(f"""
  高涨幅股票(>3%): {total_high}只
  - 无信号(未监控/成交不够): {total_no_sig}只 ({total_no_sig/total_high*100:.0f}%)
  - 有信号但被共振过滤:      {total_blocked}只 ({total_blocked/total_high*100:.0f}%)
  - 有信号且共振通过:        {total_passed}只 ({total_passed/total_high*100:.0f}%)

  共振过滤率(有信号股中): {total_blocked/max(total_has_sig,1)*100:.0f}%
  
  主要过滤原因:
  1. 仅有mega_buy单类型信号 → 无法触发multi_green
  2. 无StockScorer评分(或<80) → 无法触发strong_single
  3. 冲突窗口: 红绿信号在15分钟内互相压制
""")
    print()


if __name__ == '__main__':
    main()
