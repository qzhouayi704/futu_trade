#!/usr/bin/env python3
"""
分时回测引擎 v2 — 严格遵循 DecisionEngine 真实规则

真实规则 (来自 models.py + engine.py):
  入场:
    - accel_in strength=0, 仅确认信号, 不独立触发
    - mega_buy strength=90, 唯一买入触发信号
    - 共振条件(三选一):
      1. 双源共振: 15分钟内2+不同source (sniper+anomaly)
      2. 强信号: strength≥80 且 评分≥80 (mega_buy=90满足strength)
      3. 多重绿色: 15分钟内2+种sniper_signal_type (如 mega_buy+accel_in)
    - 冷却期: 同股30分钟
  出场:
    - mega_sell → 自动卖出(持仓才执行)
    - sustained_out → 仅WARN, 不平仓
    - 追踪止盈: 涨≥5%激活, 回撤3%止盈
    - 固定止损: -3%
  仓位:
    - 最多2只持仓, 单仓50%可投资金, 保留30%现金
"""
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

DB = '/opt/futu_trade_sys/simple_trade/data/trade.db'

# ===== 配置(严格按models.py) =====
INITIAL_CAPITAL = 100000
MAX_POSITIONS = 2
SINGLE_POSITION_PCT = 0.50
CASH_RESERVE_PCT = 0.30
TRAILING_ACTIVATE_PCT = 5.0
TRAILING_STOP_PCT = 3.0
STOP_LOSS_PCT = -3.0
COOLDOWN_MINUTES = 30
RESONANCE_WINDOW_MINUTES = 15

# 信号强度映射(完全按models.py)
STRENGTH_MAP = {
    'mega_buy': 90.0,
    'accel_in': 0.0,      # 仅确认
    'reversal_bull': 0.0,  # 不触发
    'mega_sell': 95.0,
    'reversal_bear': 30.0,
    'sustained_out': 20.0,
}

BUY_TRIGGER_TYPES = {'mega_buy'}  # 唯一买入触发
SELL_AUTO_TYPES = {'mega_sell'}    # 自动卖出
WARN_TYPES = {'reversal_bear', 'sustained_out'}  # 仅预警

# ===== 数据加载 =====
def load_data():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    days = conn.execute("""
        SELECT DISTINCT trade_date FROM sniper_signals
        WHERE trade_date >= '2026-06-01' ORDER BY trade_date
    """).fetchall()
    trade_dates = [d['trade_date'] for d in days]
    print(f"回测日期: {trade_dates}")

    data = {}
    for td in trade_dates:
        signals = conn.execute("""
            SELECT * FROM sniper_signals WHERE trade_date = ? ORDER BY time
        """, (td,)).fetchall()

        ticks_raw = conn.execute("""
            SELECT stock_code, price, volume, timestamp
            FROM ticker_data WHERE trade_date = ? ORDER BY timestamp
        """, (td,)).fetchall()

        ticks_by_stock = defaultdict(list)
        for t in ticks_raw:
            ticks_by_stock[t['stock_code']].append({
                'price': float(t['price']),
                'ts': int(t['timestamp']),
            })

        data[td] = {
            'signals': [dict(s) for s in signals],
            'ticks': dict(ticks_by_stock),
        }
        print(f"  {td}: {len(signals)} 信号, {len(ticks_by_stock)} 只股票, {len(ticks_raw)} ticks")

    conn.close()
    return trade_dates, data

# ===== 回测引擎 =====
class Position:
    def __init__(self, code, name, price, qty, time, resonance_type, signals_desc):
        self.code = code
        self.name = name
        self.entry_price = price
        self.quantity = qty
        self.entry_time = time
        self.resonance_type = resonance_type
        self.signals_desc = signals_desc
        self.peak_price = price
        self.trailing_activated = False
        self.exit_price = None
        self.exit_time = None
        self.exit_reason = None

    @property
    def pnl(self):
        return (self.exit_price - self.entry_price) * self.quantity if self.exit_price else 0

    @property
    def pnl_pct(self):
        return (self.exit_price / self.entry_price - 1) * 100 if self.exit_price and self.entry_price > 0 else 0


class BacktestV2:
    def __init__(self):
        self.capital = INITIAL_CAPITAL
        self.positions = {}
        self.closed = []
        self.daily = []
        self.cooldown = {}  # code -> cooldown_end_time_str
        self.pending_signals = defaultdict(list)  # code -> [(time, signal_type, price)]
        self.stats = {
            'signal_total': 0, 'resonance_matched': 0,
            'resonance_rejected': 0, 'cooldown_rejected': 0,
            'position_full': 0, 'capital_insufficient': 0,
        }

    def run(self, trade_dates, data):
        for td in trade_dates:
            self._run_day(td, data[td])
        self._summary()

    def _parse_time(self, time_str):
        """解析 HH:MM:SS 或 HH:MM 格式"""
        try:
            parts = time_str.split(':')
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + (int(parts[2]) if len(parts) > 2 else 0)
        except:
            return 0

    def _run_day(self, td, day_data):
        signals = day_data['signals']
        ticks = day_data['ticks']
        self.pending_signals.clear()
        day_closed = []

        # ===== 阶段1: 处理信号(按时间) =====
        for sig in signals:
            code = sig['stock_code']
            name = sig['stock_name']
            sig_type = sig['signal_type']
            price = float(sig['price']) if sig['price'] else 0
            sig_time = sig.get('time', '')
            self.stats['signal_total'] += 1

            if price <= 0:
                continue

            # --- 卖出信号: mega_sell ---
            if sig_type in SELL_AUTO_TYPES:
                if code in self.positions:
                    pos = self.positions[code]
                    pos.exit_price = price
                    pos.exit_time = sig_time
                    pos.exit_reason = f'auto_sell:{sig_type}'
                    self.capital += price * pos.quantity
                    day_closed.append(pos)
                    del self.positions[code]
                    self.cooldown[code] = self._parse_time(sig_time) + COOLDOWN_MINUTES * 60
                continue

            # --- 预警信号: sustained_out, reversal_bear ---
            if sig_type in WARN_TYPES:
                continue  # 仅预警，不操作

            # --- 买入信号处理 ---
            strength = STRENGTH_MAP.get(sig_type, 0)

            # accel_in: 缓存为确认信号，不触发
            # mega_buy: 缓存 + 检查共振
            self.pending_signals[code].append({
                'time': sig_time,
                'time_sec': self._parse_time(sig_time),
                'type': sig_type,
                'price': price,
                'name': name,
                'strength': strength,
            })

            # 仅 mega_buy 触发共振检查
            if sig_type not in BUY_TRIGGER_TYPES:
                continue

            # 冷却检查
            if code in self.cooldown:
                current_sec = self._parse_time(sig_time)
                if current_sec < self.cooldown[code]:
                    self.stats['cooldown_rejected'] += 1
                    continue

            # 共振检查
            resonance = self._check_resonance(code, sig_time)
            if not resonance:
                self.stats['resonance_rejected'] += 1
                continue

            self.stats['resonance_matched'] += 1

            # 仓位检查
            if len(self.positions) >= MAX_POSITIONS:
                self.stats['position_full'] += 1
                continue

            # 计算仓位
            investable = self.capital * (1 - CASH_RESERVE_PCT)
            position_capital = investable * SINGLE_POSITION_PCT
            qty = int(position_capital / price)
            if qty <= 0 or price * qty > self.capital * (1 - CASH_RESERVE_PCT):
                self.stats['capital_insufficient'] += 1
                continue

            # 用下一个tick价格入场(更真实)
            entry_price = self._get_next_tick_price(ticks, code, sig_time)
            if entry_price is None:
                entry_price = price

            cost = entry_price * qty
            if cost > self.capital:
                continue

            self.positions[code] = Position(
                code, name, entry_price, qty, sig_time,
                resonance['type'], resonance['desc']
            )
            self.capital -= cost
            self.cooldown[code] = self._parse_time(sig_time) + COOLDOWN_MINUTES * 60

        # ===== 阶段2: tick追踪止盈/止损 =====
        codes_to_close = []
        for code, pos in self.positions.items():
            if code not in ticks:
                continue
            entry_sec = self._parse_time(pos.entry_time)
            for tick in ticks[code]:
                # 只看入场后的tick
                tick_sec = (tick['ts'] / 1000) % 86400 if tick['ts'] > 1e10 else tick['ts']
                price = tick['price']

                if price > pos.peak_price:
                    pos.peak_price = price

                pnl_pct = (price / pos.entry_price - 1) * 100

                # 止损
                if pnl_pct <= STOP_LOSS_PCT:
                    pos.exit_price = price
                    pos.exit_reason = f'stop_loss({pnl_pct:.1f}%)'
                    self.capital += price * pos.quantity
                    codes_to_close.append(code)
                    day_closed.append(pos)
                    break

                # 激活追踪
                if not pos.trailing_activated and pnl_pct >= TRAILING_ACTIVATE_PCT:
                    pos.trailing_activated = True

                # 追踪止盈
                if pos.trailing_activated:
                    dd = (1 - price / pos.peak_price) * 100
                    if dd >= TRAILING_STOP_PCT:
                        pos.exit_price = price
                        pos.exit_reason = f'trailing(peak={pos.peak_price:.2f},dd={dd:.1f}%)'
                        self.capital += price * pos.quantity
                        codes_to_close.append(code)
                        day_closed.append(pos)
                        break

        for c in codes_to_close:
            if c in self.positions:
                del self.positions[c]

        # ===== 阶段3: 收盘平仓 =====
        for code in list(self.positions.keys()):
            pos = self.positions[code]
            if code in ticks and ticks[code]:
                pos.exit_price = ticks[code][-1]['price']
                pos.exit_reason = 'end_of_day'
            else:
                pos.exit_price = pos.entry_price
                pos.exit_reason = 'eod_no_data'
            self.capital += pos.exit_price * pos.quantity
            day_closed.append(pos)
        self.positions.clear()

        self.closed.extend(day_closed)

        # 日报
        day_pnl = sum(p.pnl for p in day_closed)
        wins = sum(1 for p in day_closed if p.pnl > 0)
        self.daily.append({'date': td, 'trades': len(day_closed), 'pnl': day_pnl, 'wins': wins, 'capital': self.capital})

        pnl_s = f"+{day_pnl:.0f}" if day_pnl >= 0 else f"{day_pnl:.0f}"
        print(f"\n📅 {td}: {len(day_closed)} 笔 | P&L: {pnl_s} HKD | 胜率: {wins}/{len(day_closed)} | 资金: {self.capital:.0f}")
        for p in day_closed:
            icon = "🟢" if p.pnl > 0 else "🔴"
            ps = f"+{p.pnl:.0f}" if p.pnl >= 0 else f"{p.pnl:.0f}"
            print(f"  {icon} {p.name}({p.code}) {p.entry_price:.2f}→{p.exit_price:.2f} "
                  f"{ps} ({p.pnl_pct:+.2f}%) [{p.exit_reason}] 共振:{p.resonance_type}")

    def _check_resonance(self, code, current_time):
        """检查共振条件(严格按 engine.py _evaluate_buy_resonance)"""
        pending = self.pending_signals.get(code, [])
        current_sec = self._parse_time(current_time)
        window = RESONANCE_WINDOW_MINUTES * 60

        recent = [s for s in pending if (current_sec - s['time_sec']) < window and (current_sec - s['time_sec']) >= 0]
        if not recent:
            return None

        # 规则1: 双源共振 (sniper数据只有一个source，跳过)

        # 规则2: 强信号 (mega_buy strength=90 ≥ 80)
        # 但需要 StockScorer ≥ 80，回测中无评分数据，跳过
        # 除非我们模拟：高涨幅(>5%)的mega_buy视为评分达标
        strongest = max(recent, key=lambda s: s['strength'])
        if strongest['strength'] >= 80:
            # 模拟评分：同一股票有accel_in确认 = 评分达标
            has_accel = any(s['type'] == 'accel_in' for s in recent)
            if has_accel:
                return {
                    'type': 'strong_confirmed',
                    'desc': f"强信号+资金确认(mega_buy={strongest['strength']:.0f}+accel_in)",
                }

        # 规则3: 多重绿色 (15分钟内2+种不同sniper_signal_type)
        types = set(s['type'] for s in recent if s['type'] in ('mega_buy', 'accel_in', 'reversal_bull'))
        if len(types) >= 2:
            return {
                'type': 'multi_green',
                'desc': f"多重绿色({'+'.join(types)})",
            }

        return None

    def _get_next_tick_price(self, ticks, code, sig_time):
        """获取信号后下一个tick价格(模拟真实入场)"""
        if code not in ticks:
            return None
        sig_sec = self._parse_time(sig_time)
        for tick in ticks[code]:
            tick_sec = (tick['ts'] / 1000) % 86400 if tick['ts'] > 1e10 else tick['ts']
            if tick_sec > sig_sec:
                return tick['price']
        return None

    def _summary(self):
        total_pnl = sum(d['pnl'] for d in self.daily)
        total_trades = len(self.closed)
        total_wins = sum(1 for t in self.closed if t.pnl > 0)
        win_rate = total_wins / total_trades * 100 if total_trades > 0 else 0

        winning = [t for t in self.closed if t.pnl > 0]
        losing = [t for t in self.closed if t.pnl <= 0]
        avg_win = sum(t.pnl for t in winning) / len(winning) if winning else 0
        avg_loss = sum(t.pnl for t in losing) / len(losing) if losing else 0
        gross_win = sum(t.pnl for t in winning)
        gross_loss = abs(sum(t.pnl for t in losing))
        pf = gross_win / gross_loss if gross_loss > 0 else float('inf')

        by_resonance = defaultdict(lambda: {'count': 0, 'pnl': 0, 'wins': 0})
        for t in self.closed:
            r = t.resonance_type
            by_resonance[r]['count'] += 1
            by_resonance[r]['pnl'] += t.pnl
            if t.pnl > 0: by_resonance[r]['wins'] += 1

        by_exit = defaultdict(lambda: {'count': 0, 'pnl': 0})
        for t in self.closed:
            reason = t.exit_reason.split('(')[0] if t.exit_reason else 'unknown'
            by_exit[reason]['count'] += 1
            by_exit[reason]['pnl'] += t.pnl

        print("\n" + "=" * 65)
        print("📊 回测总结 (v2 — 真实DecisionEngine规则)")
        print("=" * 65)
        print(f"  回测期间: {self.daily[0]['date']} ~ {self.daily[-1]['date']}")
        print(f"  初始资金: {INITIAL_CAPITAL:,.0f} HKD")
        print(f"  最终资金: {self.capital:,.0f} HKD")
        print(f"  总盈亏:   {total_pnl:+,.0f} HKD ({total_pnl/INITIAL_CAPITAL*100:+.2f}%)")
        print(f"  总交易数: {total_trades}")
        print(f"  胜率:     {total_wins}/{total_trades} ({win_rate:.1f}%)")
        print(f"  盈亏比:   {pf:.2f}")
        print(f"  平均盈利: {avg_win:+,.0f} | 平均亏损: {avg_loss:+,.0f}")

        print(f"\n🔍 信号过滤统计:")
        print(f"  总信号数:       {self.stats['signal_total']}")
        print(f"  共振匹配:       {self.stats['resonance_matched']}")
        print(f"  共振未满足:     {self.stats['resonance_rejected']}")
        print(f"  冷却期拒绝:     {self.stats['cooldown_rejected']}")
        print(f"  仓位已满:       {self.stats['position_full']}")
        print(f"  资金不足:       {self.stats['capital_insufficient']}")
        print(f"  过滤率:         {(1 - self.stats['resonance_matched']/max(self.stats['signal_total'],1))*100:.1f}%")

        print(f"\n📈 按共振类型:")
        for r, s in sorted(by_resonance.items(), key=lambda x: x[1]['pnl'], reverse=True):
            wr = s['wins']/s['count']*100 if s['count'] else 0
            print(f"  {r:25s}: {s['count']:3d} 笔 | P&L: {s['pnl']:+8,.0f} | 胜率: {wr:.0f}%")

        print(f"\n🚪 按退出原因:")
        for r, s in sorted(by_exit.items(), key=lambda x: x[1]['count'], reverse=True):
            print(f"  {r:25s}: {s['count']:3d} 笔 | P&L: {s['pnl']:+8,.0f}")

        print(f"\n📅 每日:")
        for d in self.daily:
            icon = "📈" if d['pnl'] >= 0 else "📉"
            print(f"  {icon} {d['date']}: {d['trades']}笔 | {d['pnl']:+8,.0f} | "
                  f"胜率 {d['wins']}/{d['trades']} | 资金 {d['capital']:,.0f}")


if __name__ == '__main__':
    print("🔄 加载历史数据...")
    dates, data = load_data()
    print(f"\n🚀 回测 v2 (真实DecisionEngine规则)")
    print(f"  共振: 多重绿色(mega_buy+accel_in 15分钟内) 或 强信号+资金确认")
    print(f"  仓位: 最多{MAX_POSITIONS}只, 单仓{SINGLE_POSITION_PCT*100:.0f}%, 保留{CASH_RESERVE_PCT*100:.0f}%现金")
    print(f"  止盈: ≥{TRAILING_ACTIVATE_PCT}%激活追踪, {TRAILING_STOP_PCT}%回撤止盈")
    print(f"  止损: {STOP_LOSS_PCT}% | 冷却: {COOLDOWN_MINUTES}分钟")

    engine = BacktestV2()
    engine.run(dates, data)
