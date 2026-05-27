#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日内波段卖后跟踪器

解决核心问题：卖出后股票从 positions 消失，系统不再关注该股。

机制：
1. 持仓股卖出后，自动进入"卖后跟踪"列表
2. 跟踪期间继续接收报价和资金流数据
3. 当多个买回条件满足时，发出买回信号
4. 每只股票每日仅允许一次卖出-买回配对

买回条件（至少2/3满足）：
- 价格从卖出后高点回撤 ≥ N%（默认3%）
- 主力资金重新流入（net_inflow > 0 且 inflow_change > 0）
- 5分钟动量转正（momentum_direction > 0 且有底分型）

由 QuotePipeline.run_monitoring_cycle() 在每轮中调用。
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Any, Optional

logger = logging.getLogger("intraday.swing")


class SwingState(Enum):
    """配对交易状态"""
    TRACKING_SELL = "tracking_sell"    # 持仓中，等待卖出条件
    SOLD_WATCHING = "sold_watching"    # 已卖出，追踪买回时机
    BUYBACK_SENT = "buyback_sent"     # 已发出买回信号
    COMPLETED = "completed"           # 配对完成，当日不再触发


@dataclass
class SwingRecord:
    """单只股票的日内波段记录"""
    stock_code: str
    stock_name: str = ""
    state: SwingState = SwingState.TRACKING_SELL

    # 卖出信息
    sell_price: float = 0.0
    sell_time: str = ""
    sell_reason: str = ""

    # 卖出后追踪
    peak_after_sell: float = 0.0      # 卖出后最高价
    trough_after_sell: float = 0.0    # 卖出后最低价
    current_price: float = 0.0

    # 日期
    trade_date: str = field(default_factory=lambda: date.today().isoformat())


class IntradaySwingTracker:
    """日内波段卖后跟踪器

    Args:
        buyback_drawdown_pct: 从卖出后峰值回撤多少触发买回（默认3%）
    """

    def __init__(self, buyback_drawdown_pct: float = 3.0):
        self.buyback_drawdown_pct = buyback_drawdown_pct
        self._records: Dict[str, SwingRecord] = {}
        self._current_date: str = ""

    def _reset_if_new_day(self):
        """新交易日重置"""
        today = date.today().isoformat()
        if today != self._current_date:
            if self._records:
                logger.info(
                    f"[SwingTracker] 新交易日，清除 {len(self._records)} 条记录"
                )
            self._records.clear()
            self._current_date = today

    def on_sell_signal(
        self,
        stock_code: str,
        stock_name: str,
        sell_price: float,
        reason: str = "",
    ):
        """当系统产生卖出信号时调用 — 将股票加入卖后跟踪列表

        由 QuotePipeline 在处理卖出信号时调用。
        """
        self._reset_if_new_day()

        # 如果已经有记录且不是 TRACKING_SELL，说明已在流程中
        existing = self._records.get(stock_code)
        if existing and existing.state != SwingState.TRACKING_SELL:
            logger.debug(f"[SwingTracker] {stock_code} 已在追踪中({existing.state.value})，跳过")
            return

        record = SwingRecord(
            stock_code=stock_code,
            stock_name=stock_name,
            state=SwingState.SOLD_WATCHING,
            sell_price=sell_price,
            sell_time=datetime.now().strftime('%H:%M:%S'),
            sell_reason=reason,
            peak_after_sell=sell_price,
            trough_after_sell=sell_price,
            current_price=sell_price,
        )
        self._records[stock_code] = record
        logger.info(
            f"[SwingTracker] {stock_name}({stock_code}) 进入卖后跟踪 "
            f"@ {sell_price:.3f}，原因: {reason}"
        )

    def check_buyback(
        self,
        quotes: List[Dict[str, Any]],
        capital_flows: Dict[str, Dict] = None,
        momentum_snapshots: Dict = None,
    ) -> List[Dict[str, Any]]:
        """检查卖后跟踪列表中的股票是否满足买回条件

        Args:
            quotes: 实时报价列表
            capital_flows: 资金流数据 {stock_code: flow_data}
            momentum_snapshots: 5分钟动量快照 {stock_code: MomentumSnapshot}

        Returns:
            买回信号列表
        """
        self._reset_if_new_day()

        if not self._records:
            return []

        quotes_map = {q.get('code', ''): q for q in quotes if q.get('code')}
        signals = []

        for code, record in list(self._records.items()):
            if record.state != SwingState.SOLD_WATCHING:
                continue

            quote = quotes_map.get(code)
            if not quote:
                continue

            current_price = quote.get('last_price', 0) or quote.get('current_price', 0)
            if current_price <= 0:
                continue

            # 更新追踪价格
            record.current_price = current_price
            if current_price > record.peak_after_sell:
                record.peak_after_sell = current_price
            if current_price < record.trough_after_sell or record.trough_after_sell <= 0:
                record.trough_after_sell = current_price

            # 评估买回条件
            signal = self._evaluate_buyback(
                record, quote,
                capital_flows.get(code) if capital_flows else None,
                momentum_snapshots.get(code) if momentum_snapshots else None,
            )
            if signal:
                record.state = SwingState.BUYBACK_SENT
                signals.append(signal)

        return signals

    def _evaluate_buyback(
        self,
        record: SwingRecord,
        quote: Dict[str, Any],
        flow: Optional[Dict] = None,
        momentum = None,
    ) -> Optional[Dict[str, Any]]:
        """评估单只股票的买回条件

        至少2/3条件满足才触发买回：
        1. 价格从峰值回撤 ≥ buyback_drawdown_pct
        2. 资金流转正（主力净流入 > 0 且在增加）
        3. 5分钟动量转正（方向为正 或 出现底分型）
        """
        conditions_met = 0
        reasons = []

        price = record.current_price

        # 条件1：价格回撤
        if record.peak_after_sell > 0:
            drawdown = (record.peak_after_sell - price) / record.peak_after_sell * 100
            if drawdown >= self.buyback_drawdown_pct:
                conditions_met += 1
                reasons.append(
                    f"从峰值{record.peak_after_sell:.3f}回撤{drawdown:.1f}%"
                )

        # 条件2：资金流转正
        if flow:
            net_inflow = flow.get('main_net_inflow', 0)
            inflow_change = flow.get('inflow_change', 0)
            if net_inflow > 0 and inflow_change > 0:
                conditions_met += 1
                reasons.append(
                    f"资金回流(净流入{net_inflow/10000:.0f}万,变化+{inflow_change/10000:.0f}万)"
                )

        # 条件3：动量转正
        if momentum:
            direction = getattr(momentum, 'momentum_direction', 0)
            has_bottom = getattr(momentum, 'has_bottom_pattern', False)
            lower_support = getattr(momentum, 'lower_shadow_support', False)
            if direction > 0 or has_bottom or lower_support:
                conditions_met += 1
                detail = []
                if direction > 0:
                    detail.append(f"动量转正({direction:.2f})")
                if has_bottom:
                    detail.append("底分型")
                if lower_support:
                    detail.append("下影支撑")
                reasons.append(", ".join(detail))

        # 至少2/3条件满足
        if conditions_met < 2:
            return None

        # 额外校验：买回价不能高于卖出价（否则波段亏损）
        if price >= record.sell_price:
            return None

        profit_pct = (record.sell_price - price) / record.sell_price * 100
        reason_text = " + ".join(reasons)

        logger.info(
            f"[SwingTracker] 买回信号: {record.stock_name}({record.stock_code}) "
            f"@ {price:.3f}，卖出价{record.sell_price:.3f}，"
            f"波段利润{profit_pct:.1f}%，条件({conditions_met}/3): {reason_text}"
        )

        return {
            'signal_type': 'BUY',
            'stock_code': record.stock_code,
            'stock_name': record.stock_name,
            'price': price,
            'reason': f"日内波段买回({conditions_met}/3): {reason_text}",
            'message': (
                f"🟢 日内波段买回: {record.stock_name}({record.stock_code}) "
                f"@ {price:.3f}，波段利润{profit_pct:.1f}%"
            ),
            'action': 'intraday_swing_buyback',
            'source': 'swing_tracker',
            'swing_detail': {
                'sell_price': record.sell_price,
                'sell_time': record.sell_time,
                'buyback_price': price,
                'profit_pct': round(profit_pct, 2),
                'conditions_met': conditions_met,
                'reasons': reasons,
            },
        }

    def mark_completed(self, stock_code: str):
        """标记配对完成（买回执行后调用）"""
        record = self._records.get(stock_code)
        if record:
            record.state = SwingState.COMPLETED
            logger.info(f"[SwingTracker] {stock_code} 配对完成")

    def get_watching_codes(self) -> List[str]:
        """获取正在卖后跟踪的股票代码列表

        供 QuotePipeline 使用：确保这些股票继续接收报价数据。
        """
        self._reset_if_new_day()
        return [
            code for code, r in self._records.items()
            if r.state == SwingState.SOLD_WATCHING
        ]

    def get_status(self) -> Dict[str, Any]:
        """返回当前状态（供 API 查询）"""
        return {
            'date': self._current_date,
            'buyback_drawdown_pct': self.buyback_drawdown_pct,
            'records': {
                code: {
                    'state': r.state.value,
                    'stock_name': r.stock_name,
                    'sell_price': r.sell_price,
                    'sell_time': r.sell_time,
                    'current_price': r.current_price,
                    'peak_after_sell': r.peak_after_sell,
                }
                for code, r in self._records.items()
            },
        }
