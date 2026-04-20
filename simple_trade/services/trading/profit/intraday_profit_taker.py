#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日内高抛低吸信号推送

持仓股日内涨幅 ≥ 阈值时推送卖出信号，价格回落后推送买回信号。
每只股票每种信号仅推送一次，避免重复。
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Dict, List, Any

logger = logging.getLogger("intraday_profit")


class StockState(Enum):
    WATCHING = "watching"       # 监控中，等待涨幅触发
    SELL_SIGNALED = "sell_signaled"  # 已推送卖出信号，等待回落
    COMPLETED = "completed"     # 已推送买回信号，当日不再触发


@dataclass
class StockTracker:
    """单只股票的日内追踪状态"""
    state: StockState = StockState.WATCHING
    sell_price: float = 0.0       # 卖出信号时的价格
    peak_since_sell: float = 0.0  # 卖出信号后的最高价
    signal_date: date = field(default_factory=date.today)


class IntradayProfitTaker:
    """日内高抛低吸信号生成器

    参数:
        sell_trigger_pct: 日内涨幅触发卖出信号的百分比（相对昨收）
        buyback_drawdown_pct: 从卖出后峰值回撤触发买回信号的百分比
    """

    def __init__(
        self,
        sell_trigger_pct: float = 10.0,
        buyback_drawdown_pct: float = 3.0,
    ):
        self.sell_trigger_pct = sell_trigger_pct
        self.buyback_drawdown_pct = buyback_drawdown_pct
        self._trackers: Dict[str, StockTracker] = {}
        self._current_date: date = date.today()
        logger.info(
            f"日内高抛低吸初始化: 卖出触发={sell_trigger_pct}%, "
            f"买回回撤={buyback_drawdown_pct}%"
        )

    def _reset_if_new_day(self):
        """新交易日自动重置所有状态"""
        today = date.today()
        if today != self._current_date:
            if self._trackers:
                logger.info(f"新交易日，重置 {len(self._trackers)} 只股票的日内追踪状态")
            self._trackers.clear()
            self._current_date = today

    def check(
        self,
        quotes: List[Dict[str, Any]],
        positions: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """检查持仓股的日内高抛低吸信号

        Args:
            quotes: 实时报价列表，每项含 code, last_price, prev_close, change_percent 等
            positions: 持仓字典 {stock_code: position_info}

        Returns:
            信号列表，每项含 signal_type, stock_code, price, reason, message
        """
        self._reset_if_new_day()

        if not positions:
            return []

        signals = []
        quotes_map = {q['code']: q for q in quotes if 'code' in q}

        for stock_code in positions:
            quote = quotes_map.get(stock_code)
            if not quote:
                continue

            current_price = quote.get('last_price', 0)
            prev_close = quote.get('prev_close', 0)
            stock_name = quote.get('name', stock_code)

            if current_price <= 0 or prev_close <= 0:
                continue

            change_pct = ((current_price - prev_close) / prev_close) * 100
            tracker = self._trackers.setdefault(stock_code, StockTracker())

            signal = self._evaluate(
                stock_code, stock_name, current_price,
                prev_close, change_pct, tracker,
            )
            if signal:
                signals.append(signal)

        return signals

    def _evaluate(
        self,
        code: str, name: str,
        price: float, prev_close: float,
        change_pct: float,
        tracker: StockTracker,
    ) -> Dict[str, Any] | None:
        """评估单只股票，返回信号或 None"""

        # 已完成：当日不再触发
        if tracker.state == StockState.COMPLETED:
            return None

        # 状态1: 监控中 → 检查是否触发卖出
        if tracker.state == StockState.WATCHING:
            if change_pct >= self.sell_trigger_pct:
                tracker.state = StockState.SELL_SIGNALED
                tracker.sell_price = price
                tracker.peak_since_sell = price
                logger.info(
                    f"[{code}] 日内涨幅 {change_pct:.1f}% ≥ {self.sell_trigger_pct}%，"
                    f"推送卖出信号 @ {price:.3f}"
                )
                return {
                    'signal_type': 'SELL',
                    'stock_code': code,
                    'stock_name': name,
                    'price': price,
                    'reason': (
                        f"日内涨幅 {change_pct:.1f}% 达到 {self.sell_trigger_pct}% 止盈线，"
                        f"昨收 {prev_close:.3f}"
                    ),
                    'message': (
                        f"🔴 日内止盈信号: {name}({code}) "
                        f"涨幅 {change_pct:.1f}% @ {price:.3f}"
                    ),
                    'action': 'intraday_take_profit',
                    'source': 'intraday_profit_taker',
                }
            return None

        # 状态2: 已推卖出信号 → 追踪峰值，检查回落买回
        if tracker.state == StockState.SELL_SIGNALED:
            if price > tracker.peak_since_sell:
                tracker.peak_since_sell = price

            if tracker.peak_since_sell > 0:
                drawdown = ((tracker.peak_since_sell - price)
                            / tracker.peak_since_sell) * 100
            else:
                drawdown = 0

            if drawdown >= self.buyback_drawdown_pct:
                tracker.state = StockState.COMPLETED
                gain_from_sell = ((price - tracker.sell_price)
                                  / tracker.sell_price) * 100
                logger.info(
                    f"[{code}] 从峰值 {tracker.peak_since_sell:.3f} "
                    f"回撤 {drawdown:.1f}% ≥ {self.buyback_drawdown_pct}%，"
                    f"推送买回信号 @ {price:.3f}"
                )
                return {
                    'signal_type': 'BUY',
                    'stock_code': code,
                    'stock_name': name,
                    'price': price,
                    'reason': (
                        f"从日内峰值 {tracker.peak_since_sell:.3f} "
                        f"回撤 {drawdown:.1f}%，可考虑接回"
                    ),
                    'message': (
                        f"🟢 日内买回信号: {name}({code}) "
                        f"回撤 {drawdown:.1f}% @ {price:.3f}"
                    ),
                    'action': 'intraday_buyback',
                    'source': 'intraday_profit_taker',
                }
            return None

        return None

    def get_status(self) -> Dict[str, Any]:
        """返回当前追踪状态（供 API 查询）"""
        return {
            'date': str(self._current_date),
            'sell_trigger_pct': self.sell_trigger_pct,
            'buyback_drawdown_pct': self.buyback_drawdown_pct,
            'tracked_stocks': {
                code: {
                    'state': t.state.value,
                    'sell_price': t.sell_price,
                    'peak_since_sell': t.peak_since_sell,
                }
                for code, t in self._trackers.items()
                if t.state != StockState.WATCHING
            },
        }
