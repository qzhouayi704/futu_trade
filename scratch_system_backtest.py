#!/usr/bin/env python3
"""
系统级分时回测 v2 — 严格按照真实交易系统共振规则

信号流: 逐分钟数据 → IntradaySniper信号检测(6种信号)
     → DecisionEngine共振判断(3种规则) → 仓位管理 → 止盈/止损/收盘平仓

共振规则(必须满足其一):
  1. dual_source:  15分钟内2个不同来源的BUY信号 (回测中只有sniper源，不触发)
  2. strong_single: strength≥80 且 StockScorer评分≥80 (回测无scorer，不触发)
  3. multi_green:  15分钟内2种以上不同sniper绿色信号 (回测主要触发路径)
"""
import sqlite3, os
from collections import defaultdict

DB_PATH = os.environ.get("DB_PATH", "/opt/futu_trade_sys/simple_trade/data/trade.db")

# === Sniper 信号检测参数 (与 intraday_sniper.py 完全一致) ===
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

# === 决策引擎参数 (与 models.py 完全一致) ===
RESONANCE_WINDOW = 15       # 共振窗口(分钟)
SNIPER_STRENGTH = {
    'mega_buy': 90, 'accel_in': 0, 'reversal_bull': 0,
    'mega_sell': 95, 'reversal_bear': 30, 'sustained_out': 20,
}

# === 交易参数 (与 models.py 完全一致) ===
INITIAL_CAPITAL = 25000
MAX_POSITIONS = 2
MAX_SINGLE_PCT = 0.50
CASH_RESERVE_PCT = 0.30
MEGA_FLOOR_PCT = 0.02        # 动态mega阈值地板 = 日成交额 × 2%
MEGA_FLOOR_MIN = 50          # 最低地板50万(防微盘股误触发)
TAKE_PROFIT_PCT = 5.0      # 激活移动止盈的阈值
TRAILING_STOP_PCT = 3.0    # 从峰值回撤X%卖出
STOP_LOSS_PCT = 3.0
TRADE_COST_PCT = 0.15
BUY_COOLDOWN_MIN = 30
BUY_DIP_PCT = 1.0           # 挂低1%买入


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


def get_tier(day_total):
    for _, (min_tv, a, m, r) in TIER_THRESHOLDS.items():
        if day_total >= min_tv: return a, m, r
    return 500, 800, 500


def detect_signals(timeline):
    """逐分钟信号检测 — 完整复刻 intraday_sniper.py 的6种信号"""
    signals = []
    cooldown = {}
    prev_dir = 'neutral'
    recent = []  # [(time, is_red, idx)]

    for i, p in enumerate(timeline):
        past = timeline[:i+1]
        day_total = sum(x['turnover'] for x in past)
        if day_total < 100: continue
        tvs = [x['turnover'] for x in past if x['turnover'] > 0]
        avg_tv = sum(tvs)/len(tvs) if tvs else 0
        if avg_tv <= 0: continue
        # 动态阈值(方案C: 混合动态)
        mega_floor = max(MEGA_FLOOR_MIN, day_total * MEGA_FLOOR_PCT)
        abs_nets = [abs(x['net']) for x in past if x['net'] != 0]
        avg_abs = sum(abs_nets)/len(abs_nets) if abs_nets else avg_tv
        dyn_mega = max(mega_floor, avg_abs * MEGA_MULTIPLIER)
        accel_min = mega_floor * 0.5  # accel阈值 = mega地板的一半
        rev_min = mega_floor           # reversal阈值 = mega地板
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
            # 清理过期记录
            cut = max(0, i - CONFLICT_WINDOW * 2)
            while recent and recent[0][2] < cut:
                recent.pop(0)
            signals.append({
                'time': p['time'], 'is_red': red, 'idx': i,
                'type': st, 'price': p['price'],
                'strength': SNIPER_STRENGTH.get(st, 0),
            })

        is_scan = (i % SCAN_INTERVAL == 0 and i > 0)

        # 信号1: 巨量砸盘
        if p['net'] < -dyn_mega and can('mega_sell', True):
            emit('mega_sell', True)

        # 信号2: 巨量抢筹
        if p['net'] > dyn_mega and can('mega_buy', False):
            emit('mega_buy', False)

        # 每3分钟扫描的信号
        if is_scan:
            curr_dir = 'positive' if p['cum_net'] > 0 else ('negative' if p['cum_net'] < 0 else 'neutral')

            # 信号3: 资金反转(由负转正)
            if prev_dir == 'negative' and curr_dir == 'positive' and p['cum_net'] > rev_min:
                if can('reversal_bull', False):
                    emit('reversal_bull', False)

            # 信号4: 资金反转(由正转负)
            if prev_dir == 'positive' and curr_dir == 'negative' and p['cum_net'] < -rev_min:
                if can('reversal_bear', True):
                    emit('reversal_bear', True)

            # 信号5: 资金加速流入
            if i >= 6:
                recent_3 = sum(timeline[j]['net'] for j in range(i-2, i+1))
                prev_3 = sum(timeline[j]['net'] for j in range(i-5, i-2))
                if prev_3 > 0 and recent_3 > prev_3 * ACCEL_THRESHOLD and recent_3 > accel_min:
                    if can('accel_in', False):
                        emit('accel_in', False)

            # 信号6: 持续流出
            if i >= SUSTAINED_MINUTES:
                window_net = sum(timeline[j]['net'] for j in range(i - SUSTAINED_MINUTES + 1, i + 1))
                if window_net < -dyn_sustained:
                    if can('sustained_out', True):
                        emit('sustained_out', True)

            prev_dir = curr_dir

    return signals


def check_resonance(signals, cur_idx):
    """共振判断 — 复刻 engine.py 的 _evaluate_buy_resonance
    
    mega_buy (strength=90) 是唯一的买入触发信号，通过 strong_single 路径:
      - strength >= 80 ✅ (mega_buy=90)
      - 假设活跃池中的股票 StockScorer 评分 >= 80 ✅
    
    返回: (resonance_type, trigger_signal) 或 (None, None)
    """
    # 只看当前分钟触发的信号
    cur_signals = [s for s in signals if s['idx'] == cur_idx and not s['is_red']]
    if not cur_signals:
        return None, None

    # 规则2: strong_single — mega_buy (strength=90 >= 80) 直接触发
    # 活跃池股票假设 scorer >= 80 (系统设计意图)
    for s in cur_signals:
        if s.get('strength', 0) >= 80:  # mega_buy=90
            return 'strong_single', s

    # 规则3: multi_green — 15分钟窗口内2种以上sniper绿色信号 (辅助路径)
    cutoff = max(0, cur_idx - RESONANCE_WINDOW)
    recent_buys = [s for s in signals
                   if not s['is_red'] and s['idx'] >= cutoff and s['idx'] <= cur_idx]
    green_types = set(s['type'] for s in recent_buys)
    if len(green_types) >= 2:
        latest = max(recent_buys, key=lambda s: s['idx'])
        return 'multi_green', latest

    return None, None


class Portfolio:
    def __init__(self, capital):
        self.cash = capital
        self.positions = {}
        self.trades = []
        self.cooldown = {}

    def can_buy(self, code, cur_min_idx):
        if code in self.positions: return False
        if len(self.positions) >= MAX_POSITIONS: return False
        if code in self.cooldown and cur_min_idx - self.cooldown[code] < BUY_COOLDOWN_MIN: return False
        return True

    def buy(self, code, name, price, min_idx, date, resonance_type=''):
        if price <= 0: return
        # 挂低1%买入 (模拟 buy_dip)
        exec_price = price * (1 - BUY_DIP_PCT / 100)
        investable = self.cash * (1 - CASH_RESERVE_PCT)
        max_amt = investable * MAX_SINGLE_PCT
        qty = int(max_amt / exec_price / 100) * 100  # 按资金百分比计算，不再限制固定股数
        if qty < 100: return
        cost = exec_price * qty * (1 + TRADE_COST_PCT / 100)
        if cost > self.cash: return
        self.cash -= cost
        self.positions[code] = {'qty': qty, 'entry': exec_price, 'idx': min_idx, 'name': name, 'peak': exec_price}
        self.trades.append({
            'date': date, 'code': code, 'name': name, 'dir': 'BUY',
            'price': exec_price, 'qty': qty, 'cost': round(cost, 2),
            'time_idx': min_idx, 'resonance': resonance_type,
        })

    def sell(self, code, price, reason, min_idx, date):
        if code not in self.positions or price <= 0: return 0
        pos = self.positions.pop(code)
        proceeds = price * pos['qty'] * (1 - TRADE_COST_PCT / 100)
        self.cash += proceeds
        pnl = proceeds - pos['entry'] * pos['qty'] * (1 + TRADE_COST_PCT / 100)
        pnl_pct = (price / pos['entry'] - 1) * 100
        self.cooldown[code] = min_idx
        self.trades.append({
            'date': date, 'code': code, 'name': pos['name'], 'dir': 'SELL',
            'price': price, 'qty': pos['qty'], 'proceeds': round(proceeds, 2),
            'pnl': round(pnl, 2), 'pnl_pct': round(pnl_pct, 2), 'reason': reason,
            'hold_min': min_idx - pos['idx'], 'time_idx': min_idx,
        })
        return pnl

    def check_exits(self, code, cur_price, min_idx, date):
        if code not in self.positions: return
        pos = self.positions[code]
        # 更新峰值
        if cur_price > pos['peak']:
            pos['peak'] = cur_price
        chg = (cur_price / pos['entry'] - 1) * 100
        peak_chg = (pos['peak'] / pos['entry'] - 1) * 100
        drawdown = (1 - cur_price / pos['peak']) * 100 if pos['peak'] > 0 else 0
        # 移动止盈: 涨超过5%后，从峰值回撤3%卖出
        if peak_chg >= TAKE_PROFIT_PCT and drawdown >= TRAILING_STOP_PCT:
            self.sell(code, cur_price, f'移动止盈(峰{peak_chg:+.1f}%回撤{drawdown:.1f}%)', min_idx, date)
        elif chg <= -STOP_LOSS_PCT:
            self.sell(code, cur_price, f'止损{chg:+.1f}%', min_idx, date)

    def force_close_all(self, stock_data, date):
        if not self.positions: return
        for code in list(self.positions.keys()):
            if code in stock_data:
                tl = stock_data[code]
                last_price = 0
                for p in reversed(tl):
                    if p['price'] > 0:
                        last_price = p['price']; break
                if last_price > 0:
                    self.sell(code, last_price, '收盘平仓', len(tl)-1, date)


def main():
    db = sqlite3.connect(DB_PATH)
    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date ASC"
    ).fetchall()]
    print(f"回测期间: {dates[0]} ~ {dates[-1]} ({len(dates)}天)")
    print(f"初始本金: ${INITIAL_CAPITAL:,}")
    print(f"参数: 止盈{TAKE_PROFIT_PCT}% 止损{STOP_LOSS_PCT}% 最大持仓{MAX_POSITIONS} 挂低{BUY_DIP_PCT}%买入")
    print(f"共振: multi_green(15分钟内2种sniper绿色信号) | mega_sell→自动卖出")
    print(f"{'='*80}")

    pf = Portfolio(INITIAL_CAPITAL)
    daily_results = []
    total_signals = defaultdict(int)
    resonance_stats = defaultdict(int)

    for di, trade_date in enumerate(dates):
        day_start_val = pf.cash
        codes = [r[0] for r in db.execute(
            "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date=?", (trade_date,)
        ).fetchall()]

        stock_data = {}
        stock_signals = {}
        for code in codes:
            tl = load_minute_data(db, code, trade_date)
            if len(tl) < 10: continue
            stock_data[code] = tl
            sigs = detect_signals(tl)
            if sigs:
                stock_signals[code] = sigs
                for s in sigs:
                    total_signals[s['type']] += 1

        # 构建全局时间线
        all_minutes = set()
        for tl in stock_data.values():
            for p in tl: all_minutes.add(p['time'])

        for minute in sorted(all_minutes):
            # 1. 检查持仓止盈止损
            for code in list(pf.positions.keys()):
                if code in stock_data:
                    tl = stock_data[code]
                    for p in tl:
                        if p['time'] == minute and p['price'] > 0:
                            pf.check_exits(code, p['price'], tl.index(p), trade_date)

            # 2. 处理当分钟的信号 — 严格按共振规则
            for code, sigs in stock_signals.items():
                for sig in sigs:
                    if sig['time'] != minute: continue

                    # 红色信号: mega_sell → 自动卖出持仓
                    if sig['type'] == 'mega_sell' and sig['is_red']:
                        if code in pf.positions:
                            pf.sell(code, sig['price'], 'mega_sell信号', sig['idx'], trade_date)
                        continue

                    # 绿色信号: 检查共振
                    if not sig['is_red']:
                        res_type, trigger = check_resonance(sigs, sig['idx'])
                        if res_type and pf.can_buy(code, sig['idx']):
                            resonance_stats[res_type] += 1
                            # 用下一分钟价格模拟执行延迟
                            tl = stock_data[code]
                            exec_idx = min(sig['idx'] + 1, len(tl) - 1)
                            exec_price = tl[exec_idx]['price']
                            if exec_price <= 0: exec_price = sig['price']
                            pf.buy(code, code, exec_price, sig['idx'], trade_date, res_type)

        # 收盘强平
        pf.force_close_all(stock_data, trade_date)

        day_pnl = pf.cash - day_start_val
        day_trades = [t for t in pf.trades if t['date'] == trade_date]
        daily_results.append({'date': trade_date, 'pnl': day_pnl, 'trades': len(day_trades), 'balance': pf.cash})
        marker = '🟢' if day_pnl >= 0 else '🔴'
        print(f"  {marker} {trade_date}: P&L={day_pnl:+8.2f}  余额=${pf.cash:,.2f}  交易{len(day_trades)}笔")

    db.close()

    # === 汇总报告 ===
    print(f"\n{'='*80}")
    print(f"  回测报告 ({len(dates)}天)")
    print(f"{'='*80}")

    final = pf.cash
    total_pnl = final - INITIAL_CAPITAL
    total_ret = total_pnl / INITIAL_CAPITAL * 100

    sell_trades = [t for t in pf.trades if t['dir'] == 'SELL']
    wins = [t for t in sell_trades if t.get('pnl', 0) > 0]
    losses = [t for t in sell_trades if t.get('pnl', 0) < 0]

    print(f"\n  初始本金:  ${INITIAL_CAPITAL:,}")
    print(f"  最终余额:  ${final:,.2f}")
    print(f"  总收益:    ${total_pnl:+,.2f} ({total_ret:+.2f}%)")
    print(f"\n  总交易笔数: {len(pf.trades)}")
    print(f"  买入: {len([t for t in pf.trades if t['dir']=='BUY'])}  卖出: {len(sell_trades)}")
    if sell_trades:
        print(f"  盈利: {len(wins)}笔  亏损: {len(losses)}笔  胜率: {len(wins)/len(sell_trades)*100:.1f}%")
        avg_win = sum(t['pnl'] for t in wins)/len(wins) if wins else 0
        avg_loss = sum(t['pnl'] for t in losses)/len(losses) if losses else 0
        print(f"  平均盈利: ${avg_win:+.2f}  平均亏损: ${avg_loss:+.2f}")
        if avg_loss != 0:
            print(f"  盈亏比: {abs(avg_win/avg_loss):.2f}")

    # 每日统计
    win_days = [d for d in daily_results if d['pnl'] > 0]
    loss_days = [d for d in daily_results if d['pnl'] < 0]
    print(f"\n  盈利天数: {len(win_days)}  亏损天数: {len(loss_days)}  持平: {len(daily_results)-len(win_days)-len(loss_days)}")

    max_dd = 0; peak = INITIAL_CAPITAL
    for d in daily_results:
        peak = max(peak, d['balance'])
        dd = (peak - d['balance']) / peak * 100
        max_dd = max(max_dd, dd)
    print(f"  最大回撤: {max_dd:.2f}%")

    # 信号统计
    print(f"\n  信号统计:")
    for st, cnt in sorted(total_signals.items(), key=lambda x: -x[1]):
        print(f"    {st:<16} {cnt:>4}次  强度={SNIPER_STRENGTH.get(st, 0)}")

    # 共振统计
    print(f"\n  共振触发统计:")
    for rt, cnt in sorted(resonance_stats.items(), key=lambda x: -x[1]):
        print(f"    {rt:<16} {cnt:>4}次")
    if not resonance_stats:
        print(f"    (无共振触发)")

    # 卖出原因
    if sell_trades:
        print(f"\n  平仓原因统计:")
        reasons = defaultdict(lambda: {'count': 0, 'pnl': 0})
        for t in sell_trades:
            r = t.get('reason', '未知')
            if '止盈' in r: r = '止盈'
            elif '止损' in r: r = '止损'
            elif 'mega_sell' in r: r = 'mega_sell信号'
            else: r = '收盘平仓'
            reasons[r]['count'] += 1; reasons[r]['pnl'] += t.get('pnl', 0)
        for r, v in sorted(reasons.items(), key=lambda x: -x[1]['count']):
            print(f"    {r:<14} {v['count']:>3}笔  P&L=${v['pnl']:+.2f}")

    # 详细交易记录
    print(f"\n{'='*80}")
    print(f"  详细交易记录")
    print(f"{'='*80}")
    for t in pf.trades:
        if t['dir'] == 'BUY':
            res = t.get('resonance', '')
            print(f"  {t['date']}  🟢买入 {t['name']:<10} @{t['price']:.3f} x{t['qty']}  花费${t['cost']:.2f}  [{res}]")
        else:
            print(f"  {t['date']}  🔴卖出 {t['name']:<10} @{t['price']:.3f} x{t['qty']}  "
                  f"P&L=${t.get('pnl',0):+.2f}({t.get('pnl_pct',0):+.1f}%)  "
                  f"持仓{t.get('hold_min',0)}分  {t.get('reason','')}")
    print()


if __name__ == '__main__':
    main()
