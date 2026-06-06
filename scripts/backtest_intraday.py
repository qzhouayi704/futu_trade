#!/usr/bin/env python3
"""
分时回测引擎 — 基于历史 sniper_signals + ticker_data
回测逻辑:
  1. 遍历每个交易日的 sniper_signals (按时间排序)
  2. 对 mega_buy / accel_in / reversal_bull 信号 → 模拟买入
  3. 用 ticker_data 模拟分时价格变动
  4. 应用 Sniper 止盈追踪逻辑 (涨≥5%激活, 回撤3%止盈)
  5. 对 mega_sell / sustained_out 信号 → 如有持仓则止盈
  6. 收盘未平仓 → 以收盘价平仓
  7. 输出每日 P&L + 总绩效
"""
import sqlite3
import json
from datetime import datetime, timedelta
from collections import defaultdict

DB = '/opt/futu_trade_sys/simple_trade/data/trade.db'

# ============= 配置 =============
INITIAL_CAPITAL = 100000  # 初始资金 10万HKD
MAX_POSITIONS = 5         # 最大同时持仓
POSITION_SIZE_PCT = 0.15  # 每只仓位占总资金 15%
TRAILING_ACTIVATE_PCT = 5.0   # 涨≥5% 激活追踪
TRAILING_STOP_PCT = 3.0       # 回撤3% 止盈
STOP_LOSS_PCT = -5.0          # 固定止损 -5%
BUY_SIGNALS = {'mega_buy', 'accel_in', 'reversal_bull'}
SELL_SIGNALS = {'mega_sell', 'sustained_out', 'reversal_bear'}

# ============= 数据加载 =============
def load_data():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # 获取有 ticker_data 的交易日
    days = conn.execute("""
        SELECT DISTINCT trade_date FROM ticker_data
        WHERE trade_date >= '2026-06-01' AND trade_date <= '2026-06-05'
        ORDER BY trade_date
    """).fetchall()
    trade_dates = [d['trade_date'] for d in days]
    print(f"回测日期: {trade_dates}")

    data = {}
    for td in trade_dates:
        # 加载信号
        signals = conn.execute("""
            SELECT * FROM sniper_signals
            WHERE trade_date = ? ORDER BY time
        """, (td,)).fetchall()

        # 加载tick数据 (按stock_code分组)
        ticks_raw = conn.execute("""
            SELECT stock_code, price, volume, turnover, timestamp
            FROM ticker_data
            WHERE trade_date = ?
            ORDER BY timestamp
        """, (td,)).fetchall()

        ticks_by_stock = defaultdict(list)
        for t in ticks_raw:
            ticks_by_stock[t['stock_code']].append({
                'price': float(t['price']),
                'volume': int(t['volume']),
                'turnover': float(t['turnover']),
                'ts': int(t['timestamp']),
            })

        data[td] = {
            'signals': [dict(s) for s in signals],
            'ticks': dict(ticks_by_stock),
        }
        print(f"  {td}: {len(signals)} 信号, {len(ticks_by_stock)} 只股票, {len(ticks_raw)} ticks")

    conn.close()
    return trade_dates, data

# ============= 回测引擎 =============
class Position:
    def __init__(self, stock_code, stock_name, entry_price, quantity, entry_time, signal_type):
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.entry_price = entry_price
        self.quantity = quantity
        self.entry_time = entry_time
        self.signal_type = signal_type
        self.peak_price = entry_price
        self.trailing_activated = False
        self.exit_price = None
        self.exit_time = None
        self.exit_reason = None

    @property
    def pnl(self):
        if self.exit_price:
            return (self.exit_price - self.entry_price) * self.quantity
        return 0

    @property
    def pnl_pct(self):
        if self.exit_price and self.entry_price > 0:
            return (self.exit_price / self.entry_price - 1) * 100
        return 0


class BacktestEngine:
    def __init__(self):
        self.capital = INITIAL_CAPITAL
        self.positions = {}  # stock_code -> Position
        self.closed_trades = []
        self.daily_pnl = []

    def run(self, trade_dates, data):
        for td in trade_dates:
            day_data = data[td]
            self._run_day(td, day_data)

        self._print_summary()

    def _run_day(self, trade_date, day_data):
        signals = day_data['signals']
        ticks = day_data['ticks']
        day_closed = []

        # 按信号时间处理
        for sig in signals:
            code = sig['stock_code']
            name = sig['stock_name']
            sig_type = sig['signal_type']
            sig_price = float(sig['price']) if sig['price'] else 0

            if sig_price <= 0:
                continue

            # 买入信号
            if sig_type in BUY_SIGNALS and code not in self.positions:
                if len(self.positions) >= MAX_POSITIONS:
                    continue
                qty = int((self.capital * POSITION_SIZE_PCT) / sig_price)
                if qty <= 0:
                    continue
                cost = sig_price * qty
                if cost > self.capital:
                    continue

                self.positions[code] = Position(
                    code, name, sig_price, qty,
                    sig.get('time', ''), sig_type
                )
                self.capital -= cost

            # 卖出信号
            elif sig_type in SELL_SIGNALS and code in self.positions:
                pos = self.positions[code]
                pos.exit_price = sig_price
                pos.exit_time = sig.get('time', '')
                pos.exit_reason = f'signal:{sig_type}'
                self.capital += sig_price * pos.quantity
                day_closed.append(pos)
                del self.positions[code]

        # 用tick数据模拟追踪止盈
        codes_to_close = []
        for code, pos in self.positions.items():
            if code not in ticks:
                continue
            stock_ticks = ticks[code]

            for tick in stock_ticks:
                price = tick['price']
                # 更新峰值
                if price > pos.peak_price:
                    pos.peak_price = price

                # 检查止损
                pnl_pct = (price / pos.entry_price - 1) * 100
                if pnl_pct <= STOP_LOSS_PCT:
                    pos.exit_price = price
                    pos.exit_time = str(tick['ts'])
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
                    drawdown = (1 - price / pos.peak_price) * 100
                    if drawdown >= TRAILING_STOP_PCT:
                        pos.exit_price = price
                        pos.exit_time = str(tick['ts'])
                        pos.exit_reason = f'trailing_stop(peak={pos.peak_price:.2f},dd={drawdown:.1f}%)'
                        self.capital += price * pos.quantity
                        codes_to_close.append(code)
                        day_closed.append(pos)
                        break

        for code in codes_to_close:
            if code in self.positions:
                del self.positions[code]

        # 收盘强制平仓（取最后一条tick价格）
        eod_closed = []
        for code in list(self.positions.keys()):
            pos = self.positions[code]
            if code in ticks and ticks[code]:
                last_price = ticks[code][-1]['price']
                pos.exit_price = last_price
                pos.exit_time = 'EOD'
                pos.exit_reason = 'end_of_day'
                self.capital += last_price * pos.quantity
                eod_closed.append(pos)
                day_closed.append(pos)
            # 如果没有tick数据，保持原价
            else:
                pos.exit_price = pos.entry_price
                pos.exit_time = 'EOD_NO_DATA'
                pos.exit_reason = 'no_tick_data'
                self.capital += pos.entry_price * pos.quantity
                eod_closed.append(pos)
                day_closed.append(pos)

        for pos in eod_closed:
            if pos.stock_code in self.positions:
                del self.positions[pos.stock_code]

        self.closed_trades.extend(day_closed)

        # 日统计
        day_pnl = sum(p.pnl for p in day_closed)
        win_count = sum(1 for p in day_closed if p.pnl > 0)
        loss_count = sum(1 for p in day_closed if p.pnl <= 0)

        self.daily_pnl.append({
            'date': trade_date,
            'trades': len(day_closed),
            'pnl': day_pnl,
            'wins': win_count,
            'losses': loss_count,
            'capital': self.capital,
        })

        # 打印日报
        pnl_str = f"+{day_pnl:.0f}" if day_pnl >= 0 else f"{day_pnl:.0f}"
        print(f"\n📅 {trade_date}: {len(day_closed)} 笔交易 | P&L: {pnl_str} HKD | "
              f"胜率: {win_count}/{win_count+loss_count} | 资金: {self.capital:.0f}")

        # 打印每笔交易
        for p in day_closed:
            pnl_s = f"+{p.pnl:.0f}" if p.pnl >= 0 else f"{p.pnl:.0f}"
            icon = "🟢" if p.pnl > 0 else "🔴"
            print(f"  {icon} {p.stock_name}({p.stock_code}) "
                  f"{p.signal_type} {p.entry_price:.2f}→{p.exit_price:.2f} "
                  f"{pnl_s} ({p.pnl_pct:+.2f}%) [{p.exit_reason}]")

    def _print_summary(self):
        total_pnl = sum(d['pnl'] for d in self.daily_pnl)
        total_trades = sum(d['trades'] for d in self.daily_pnl)
        total_wins = sum(d['wins'] for d in self.daily_pnl)
        total_losses = sum(d['losses'] for d in self.daily_pnl)
        win_rate = total_wins / total_trades * 100 if total_trades > 0 else 0

        winning_trades = [t for t in self.closed_trades if t.pnl > 0]
        losing_trades = [t for t in self.closed_trades if t.pnl <= 0]
        avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0
        profit_factor = abs(sum(t.pnl for t in winning_trades)) / abs(sum(t.pnl for t in losing_trades)) if losing_trades else float('inf')

        max_win = max((t.pnl for t in self.closed_trades), default=0)
        max_loss = min((t.pnl for t in self.closed_trades), default=0)

        # 按信号类型统计
        by_signal = defaultdict(lambda: {'count': 0, 'pnl': 0, 'wins': 0})
        for t in self.closed_trades:
            st = t.signal_type
            by_signal[st]['count'] += 1
            by_signal[st]['pnl'] += t.pnl
            if t.pnl > 0:
                by_signal[st]['wins'] += 1

        # 按退出原因统计
        by_exit = defaultdict(lambda: {'count': 0, 'pnl': 0})
        for t in self.closed_trades:
            reason = t.exit_reason.split('(')[0] if t.exit_reason else 'unknown'
            by_exit[reason]['count'] += 1
            by_exit[reason]['pnl'] += t.pnl

        print("\n" + "=" * 60)
        print("📊 回测总结")
        print("=" * 60)
        print(f"  回测期间: {self.daily_pnl[0]['date']} ~ {self.daily_pnl[-1]['date']}")
        print(f"  初始资金: {INITIAL_CAPITAL:,.0f} HKD")
        print(f"  最终资金: {self.capital:,.0f} HKD")
        print(f"  总盈亏:   {total_pnl:+,.0f} HKD ({total_pnl/INITIAL_CAPITAL*100:+.2f}%)")
        print(f"  总交易数: {total_trades}")
        print(f"  胜率:     {total_wins}/{total_trades} ({win_rate:.1f}%)")
        print(f"  盈亏比:   {profit_factor:.2f}")
        print(f"  平均盈利: {avg_win:+,.0f} HKD")
        print(f"  平均亏损: {avg_loss:+,.0f} HKD")
        print(f"  最大盈利: {max_win:+,.0f} HKD")
        print(f"  最大亏损: {max_loss:+,.0f} HKD")

        print(f"\n📈 按入场信号分类:")
        for sig, stats in sorted(by_signal.items(), key=lambda x: x[1]['pnl'], reverse=True):
            wr = stats['wins'] / stats['count'] * 100 if stats['count'] > 0 else 0
            print(f"  {sig:20s}: {stats['count']:3d} 笔 | P&L: {stats['pnl']:+8,.0f} | 胜率: {wr:.0f}%")

        print(f"\n🚪 按退出原因分类:")
        for reason, stats in sorted(by_exit.items(), key=lambda x: x[1]['count'], reverse=True):
            print(f"  {reason:20s}: {stats['count']:3d} 笔 | P&L: {stats['pnl']:+8,.0f}")

        print(f"\n📅 每日汇总:")
        for d in self.daily_pnl:
            icon = "📈" if d['pnl'] >= 0 else "📉"
            print(f"  {icon} {d['date']}: {d['trades']}笔 | {d['pnl']:+8,.0f} HKD | "
                  f"胜率 {d['wins']}/{d['trades']} | 累计资金 {d['capital']:,.0f}")


# ============= 主入口 =============
if __name__ == '__main__':
    print("🔄 加载历史数据...")
    trade_dates, data = load_data()
    print(f"\n🚀 开始回测 ({len(trade_dates)} 个交易日)")
    print(f"  策略: Sniper信号入场 + 追踪止盈(≥{TRAILING_ACTIVATE_PCT}%激活, {TRAILING_STOP_PCT}%回撤止盈) + 止损({STOP_LOSS_PCT}%)")
    print(f"  资金: {INITIAL_CAPITAL:,} HKD | 最大持仓: {MAX_POSITIONS} | 单仓: {POSITION_SIZE_PCT*100}%")

    engine = BacktestEngine()
    engine.run(trade_dates, data)
