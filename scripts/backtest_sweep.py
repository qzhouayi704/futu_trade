#!/usr/bin/env python3
"""
参数扫描回测 — 测试共振/仓位/止盈止损参数的最优组合

扫描维度:
  1. 共振窗口: 5/10/15/20/30 分钟
  2. 是否要求 accel_in 确认: True/False (False=纯mega_buy也入场)
  3. 最大持仓: 2/3/5
  4. 止损: -2%/-3%/-5%/-8%
  5. 追踪激活: 3%/5%/8%
  6. 追踪回撤: 2%/3%/5%
  7. 冷却期: 10/20/30/60 分钟
"""
import sqlite3
import itertools
from collections import defaultdict

DB = '/opt/futu_trade_sys/simple_trade/data/trade.db'

# ===== 加载数据(一次性) =====
def load_data():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    days = conn.execute("""
        SELECT DISTINCT trade_date FROM sniper_signals
        WHERE trade_date >= '2026-06-01' ORDER BY trade_date
    """).fetchall()
    trade_dates = [d['trade_date'] for d in days]

    data = {}
    for td in trade_dates:
        signals = [dict(s) for s in conn.execute(
            "SELECT * FROM sniper_signals WHERE trade_date=? ORDER BY time", (td,)).fetchall()]
        ticks_raw = conn.execute(
            "SELECT stock_code, price, timestamp FROM ticker_data WHERE trade_date=? ORDER BY timestamp", (td,)).fetchall()
        ticks = defaultdict(list)
        for t in ticks_raw:
            ticks[t['stock_code']].append({'price': float(t['price']), 'ts': int(t['timestamp'])})
        data[td] = {'signals': signals, 'ticks': dict(ticks)}
    conn.close()
    return trade_dates, data

def parse_time(t):
    try:
        p = t.split(':')
        return int(p[0])*3600 + int(p[1])*60 + (int(p[2]) if len(p)>2 else 0)
    except: return 0

# ===== 快速回测引擎 =====
def run_backtest(dates, data, params):
    capital = 100000
    positions = {}
    closed = []
    cooldown = {}
    pending = defaultdict(list)

    window_sec = params['window_min'] * 60
    cooldown_sec = params['cooldown_min'] * 60
    require_accel = params['require_accel']
    max_pos = params['max_positions']
    stop_loss = params['stop_loss_pct']
    trail_act = params['trail_activate_pct']
    trail_dd = params['trail_drawdown_pct']

    resonance_total = 0
    resonance_pass = 0

    for td in dates:
        signals = data[td]['signals']
        ticks = data[td]['ticks']
        pending.clear()

        # 信号处理
        for sig in signals:
            code = sig['stock_code']
            sig_type = sig['signal_type']
            price = float(sig['price']) if sig['price'] else 0
            sig_time = sig.get('time', '')
            if price <= 0: continue

            # mega_sell → 卖出
            if sig_type == 'mega_sell':
                if code in positions:
                    pos = positions.pop(code)
                    pos['exit'] = price
                    pos['reason'] = 'mega_sell'
                    capital += price * pos['qty']
                    closed.append(pos)
                    cooldown[code] = parse_time(sig_time) + cooldown_sec
                continue

            if sig_type in ('sustained_out', 'reversal_bear'):
                continue

            # 缓存信号
            pending[code].append({
                'time_sec': parse_time(sig_time), 'type': sig_type,
                'price': price, 'name': sig['stock_name'], 'time': sig_time,
            })

            if sig_type != 'mega_buy': continue

            resonance_total += 1

            # 冷却
            cur_sec = parse_time(sig_time)
            if code in cooldown and cur_sec < cooldown[code]: continue

            # 共振检查
            recent = [s for s in pending[code] if 0 <= (cur_sec - s['time_sec']) < window_sec]
            passed = False

            if require_accel:
                # 需要 accel_in 确认
                types = set(s['type'] for s in recent if s['type'] in ('mega_buy','accel_in','reversal_bull'))
                if len(types) >= 2:
                    passed = True
            else:
                # 纯 mega_buy 也可以入场
                mega_count = sum(1 for s in recent if s['type'] == 'mega_buy')
                if mega_count >= 1:
                    passed = True

            if not passed: continue
            resonance_pass += 1

            if len(positions) >= max_pos: continue

            investable = capital * 0.70
            pos_capital = investable * (1.0 / max_pos)
            qty = int(pos_capital / price)
            if qty <= 0 or price * qty > capital * 0.70: continue

            # 入场(用下一个tick)
            entry = price
            if code in ticks:
                for tk in ticks[code]:
                    tk_sec = (tk['ts']/1000) % 86400 if tk['ts'] > 1e10 else tk['ts']
                    if tk_sec > cur_sec:
                        entry = tk['price']
                        break

            cost = entry * qty
            if cost > capital: continue
            capital -= cost
            positions[code] = {
                'code': code, 'name': sig['stock_name'], 'entry': entry,
                'qty': qty, 'peak': entry, 'trail_on': False, 'time': sig_time,
            }
            cooldown[code] = cur_sec + cooldown_sec

        # tick追踪
        to_close = []
        for code, pos in positions.items():
            if code not in ticks: continue
            for tk in ticks[code]:
                p = tk['price']
                if p > pos['peak']: pos['peak'] = p
                pnl_pct = (p / pos['entry'] - 1) * 100

                if pnl_pct <= stop_loss:
                    pos['exit'] = p; pos['reason'] = 'stop_loss'
                    capital += p * pos['qty']; to_close.append(code); closed.append(pos); break

                if not pos['trail_on'] and pnl_pct >= trail_act:
                    pos['trail_on'] = True

                if pos['trail_on']:
                    dd = (1 - p / pos['peak']) * 100
                    if dd >= trail_dd:
                        pos['exit'] = p; pos['reason'] = 'trailing'
                        capital += p * pos['qty']; to_close.append(code); closed.append(pos); break

        for c in to_close:
            if c in positions: del positions[c]

        # 收盘平仓
        for code in list(positions.keys()):
            pos = positions[code]
            if code in ticks and ticks[code]:
                pos['exit'] = ticks[code][-1]['price']
            else:
                pos['exit'] = pos['entry']
            pos['reason'] = 'eod'
            capital += pos['exit'] * pos['qty']
            closed.append(pos)
        positions.clear()

    # 统计
    total_trades = len(closed)
    if total_trades == 0:
        return {'pnl': 0, 'trades': 0, 'win_rate': 0, 'pf': 0, 'capital': capital,
                'resonance_pass': resonance_pass, 'resonance_total': resonance_total}

    wins = sum(1 for t in closed if (t['exit'] - t['entry']) * t['qty'] > 0)
    total_pnl = capital - 100000
    gross_win = sum((t['exit']-t['entry'])*t['qty'] for t in closed if (t['exit']-t['entry'])*t['qty'] > 0)
    gross_loss = abs(sum((t['exit']-t['entry'])*t['qty'] for t in closed if (t['exit']-t['entry'])*t['qty'] <= 0))
    pf = gross_win / gross_loss if gross_loss > 0 else 999

    by_exit = defaultdict(lambda: {'c': 0, 'pnl': 0})
    for t in closed:
        r = t.get('reason', '?')
        by_exit[r]['c'] += 1
        by_exit[r]['pnl'] += (t['exit'] - t['entry']) * t['qty']

    return {
        'pnl': total_pnl, 'trades': total_trades, 'win_rate': wins/total_trades*100,
        'pf': pf, 'capital': capital, 'resonance_pass': resonance_pass,
        'resonance_total': resonance_total, 'by_exit': dict(by_exit),
    }


if __name__ == '__main__':
    print("🔄 加载数据...")
    dates, data = load_data()
    print(f"  日期: {dates}\n")

    # ===== 扫描1: 共振窗口 + 是否需要确认 =====
    print("=" * 80)
    print("📊 扫描1: 共振窗口 × 是否需要accel_in确认")
    print("=" * 80)
    print(f"{'窗口':>6} {'确认':>6} {'交易':>6} {'P&L':>10} {'胜率':>8} {'盈亏比':>8} {'共振通过':>10} {'过滤率':>8}")
    print("-" * 80)

    for window in [5, 10, 15, 20, 30]:
        for req_accel in [True, False]:
            r = run_backtest(dates, data, {
                'window_min': window, 'require_accel': req_accel,
                'max_positions': 2, 'stop_loss_pct': -3,
                'trail_activate_pct': 5, 'trail_drawdown_pct': 3, 'cooldown_min': 30,
            })
            filt = (1 - r['resonance_pass']/max(r['resonance_total'],1))*100
            label = "需确认" if req_accel else "不需要"
            print(f"{window:>4}min {label:>6} {r['trades']:>6} {r['pnl']:>+10,.0f} "
                  f"{r['win_rate']:>7.1f}% {r['pf']:>7.2f} {r['resonance_pass']:>10} {filt:>7.1f}%")

    # ===== 扫描2: 最大持仓数 =====
    print(f"\n{'=' * 80}")
    print("📊 扫描2: 最大持仓数")
    print("=" * 80)
    print(f"{'持仓':>6} {'交易':>6} {'P&L':>10} {'胜率':>8} {'盈亏比':>8}")
    print("-" * 50)

    for max_p in [1, 2, 3, 5, 8]:
        r = run_backtest(dates, data, {
            'window_min': 15, 'require_accel': True,
            'max_positions': max_p, 'stop_loss_pct': -3,
            'trail_activate_pct': 5, 'trail_drawdown_pct': 3, 'cooldown_min': 30,
        })
        print(f"{max_p:>6} {r['trades']:>6} {r['pnl']:>+10,.0f} "
              f"{r['win_rate']:>7.1f}% {r['pf']:>7.2f}")

    # ===== 扫描3: 止损比例 =====
    print(f"\n{'=' * 80}")
    print("📊 扫描3: 止损比例")
    print("=" * 80)
    print(f"{'止损':>6} {'交易':>6} {'P&L':>10} {'胜率':>8} {'盈亏比':>8}")
    print("-" * 50)

    for sl in [-1.5, -2, -3, -5, -8]:
        r = run_backtest(dates, data, {
            'window_min': 15, 'require_accel': True,
            'max_positions': 2, 'stop_loss_pct': sl,
            'trail_activate_pct': 5, 'trail_drawdown_pct': 3, 'cooldown_min': 30,
        })
        print(f"{sl:>5.1f}% {r['trades']:>6} {r['pnl']:>+10,.0f} "
              f"{r['win_rate']:>7.1f}% {r['pf']:>7.2f}")

    # ===== 扫描4: 追踪止盈参数 =====
    print(f"\n{'=' * 80}")
    print("📊 扫描4: 追踪止盈(激活% × 回撤%)")
    print("=" * 80)
    print(f"{'激活':>6} {'回撤':>6} {'交易':>6} {'P&L':>10} {'胜率':>8} {'盈亏比':>8}")
    print("-" * 60)

    for act in [3, 5, 8, 10]:
        for dd in [1.5, 2, 3, 5]:
            r = run_backtest(dates, data, {
                'window_min': 15, 'require_accel': True,
                'max_positions': 2, 'stop_loss_pct': -3,
                'trail_activate_pct': act, 'trail_drawdown_pct': dd, 'cooldown_min': 30,
            })
            print(f"{act:>5.0f}% {dd:>5.1f}% {r['trades']:>6} {r['pnl']:>+10,.0f} "
                  f"{r['win_rate']:>7.1f}% {r['pf']:>7.2f}")

    # ===== 扫描5: 冷却期 =====
    print(f"\n{'=' * 80}")
    print("📊 扫描5: 冷却期")
    print("=" * 80)
    print(f"{'冷却':>8} {'交易':>6} {'P&L':>10} {'胜率':>8} {'盈亏比':>8}")
    print("-" * 50)

    for cd in [5, 10, 20, 30, 60]:
        r = run_backtest(dates, data, {
            'window_min': 15, 'require_accel': True,
            'max_positions': 2, 'stop_loss_pct': -3,
            'trail_activate_pct': 5, 'trail_drawdown_pct': 3, 'cooldown_min': cd,
        })
        print(f"{cd:>6}min {r['trades']:>6} {r['pnl']:>+10,.0f} "
              f"{r['win_rate']:>7.1f}% {r['pf']:>7.2f}")

    # ===== 最优组合搜索 =====
    print(f"\n{'=' * 80}")
    print("📊 TOP 10 最优参数组合")
    print("=" * 80)

    results = []
    for window in [10, 15, 20]:
        for req in [True, False]:
            for maxp in [2, 3, 5]:
                for sl in [-2, -3, -5]:
                    for act in [3, 5, 8]:
                        for dd in [2, 3]:
                            for cd in [10, 20, 30]:
                                r = run_backtest(dates, data, {
                                    'window_min': window, 'require_accel': req,
                                    'max_positions': maxp, 'stop_loss_pct': sl,
                                    'trail_activate_pct': act, 'trail_drawdown_pct': dd, 'cooldown_min': cd,
                                })
                                if r['trades'] >= 3:  # 至少3笔交易才有意义
                                    results.append({
                                        'window': window, 'accel': req, 'maxp': maxp,
                                        'sl': sl, 'act': act, 'dd': dd, 'cd': cd,
                                        **r
                                    })

    # 按P&L排序
    results.sort(key=lambda x: x['pnl'], reverse=True)

    print(f"{'#':>3} {'窗口':>5} {'确认':>5} {'仓':>3} {'止损':>5} {'激活':>5} {'回撤':>5} {'冷却':>5} "
          f"{'交易':>5} {'P&L':>10} {'胜率':>7} {'盈亏比':>7}")
    print("-" * 90)
    for i, r in enumerate(results[:10]):
        ack = "Y" if r['accel'] else "N"
        print(f"{i+1:>3} {r['window']:>4}m {ack:>5} {r['maxp']:>3} {r['sl']:>4.0f}% {r['act']:>4.0f}% "
              f"{r['dd']:>4.0f}% {r['cd']:>4}m {r['trades']:>5} {r['pnl']:>+10,.0f} "
              f"{r['win_rate']:>6.1f}% {r['pf']:>6.2f}")

    print(f"\n共测试 {len(results)} 种参数组合")

    # 当前参数对比
    print(f"\n{'=' * 80}")
    print("📊 当前参数 vs 最优参数")
    print("=" * 80)
    current = run_backtest(dates, data, {
        'window_min': 15, 'require_accel': True,
        'max_positions': 2, 'stop_loss_pct': -3,
        'trail_activate_pct': 5, 'trail_drawdown_pct': 3, 'cooldown_min': 30,
    })
    best = results[0] if results else None
    print(f"  当前: 窗口15m 确认Y 仓2 止损-3% 激活5% 回撤3% 冷却30m → P&L: {current['pnl']:+,.0f} 胜率{current['win_rate']:.1f}% 盈亏比{current['pf']:.2f}")
    if best:
        ack = "Y" if best['accel'] else "N"
        print(f"  最优: 窗口{best['window']}m 确认{ack} 仓{best['maxp']} 止损{best['sl']:.0f}% 激活{best['act']:.0f}% 回撤{best['dd']:.0f}% 冷却{best['cd']}m → P&L: {best['pnl']:+,.0f} 胜率{best['win_rate']:.1f}% 盈亏比{best['pf']:.2f}")
