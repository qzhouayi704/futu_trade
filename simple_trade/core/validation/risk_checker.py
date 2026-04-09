#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险检查器

检查交易信号的风险，实现止盈止损逻辑。
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime, date
from enum import Enum


class RiskAction(Enum):
    """风险动作"""
    HOLD = "HOLD"                    # 继续持有
    TAKE_PROFIT = "TAKE_PROFIT"      # 止盈卖出
    STOP_LOSS = "STOP_LOSS"          # 止损卖出
    QUICK_STOP = "QUICK_STOP"        # 快速止损
    PLATE_STOP = "PLATE_STOP"        # 板块止损
    TIME_STOP = "TIME_STOP"          # 时间止损


@dataclass
class RiskCheckResult:
    """风险检查结果"""
    stock_code: str
    action: RiskAction
    reason: str
    profit_pct: float = 0.0          # 当前盈亏比例 (%)
    holding_days: int = 0            # 持有天数
    plate_rank: int = 0              # 板块排名
    should_sell: bool = False        # 是否应该卖出
    urgency: int = 0                 # 紧急程度 (0-10)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'stock_code': self.stock_code,
            'action': self.action.value,
            'reason': self.reason,
            'profit_pct': round(self.profit_pct, 2),
            'holding_days': self.holding_days,
            'plate_rank': self.plate_rank,
            'should_sell': self.should_sell,
            'urgency': self.urgency
        }


@dataclass
class RiskConfig:
    """风险配置"""
    # 止盈参数
    target_profit_pct: float = 8.0       # 目标止盈 (%)
    trailing_trigger_pct: float = 6.0    # 移动止盈触发 (%)
    trailing_callback_pct: float = 2.0   # 移动止盈回撤 (%)

    # 止损参数
    fixed_stop_loss_pct: float = -5.0    # 固定止损 (%)
    quick_stop_loss_pct: float = -3.0    # 快速止损 (%)
    plate_rank_threshold: int = 5        # 板块止损排名阈值
    max_holding_days: int = 1            # 最大持有天数
    min_profit_after_days: float = 2.0   # N天后最低盈利要求 (%)


class RiskChecker:
    """
    风险检查器

    检查持仓的风险状态，提供止盈止损建议。

    止盈条件：
    1. 目标止盈：盈利 >= 8%
    2. 移动止盈：盈利 >= 6% 后，从高点回撤 2%

    止损条件：
    1. 固定止损：亏损 >= 5%
    2. 快速止损：亏损 >= 3% 且板块走弱
    3. 板块止损：板块跌出前5名
    4. 时间止损：持有超过1天且盈利 < 2%
    """

    def __init__(self, config: RiskConfig = None):
        """
        初始化风险检查器

        Args:
            config: 风险配置
        """
        self.config = config or RiskConfig()
        self.logger = logging.getLogger(__name__)

        # 最高价记录（用于移动止盈）
        self._highest_prices: Dict[str, float] = {}

    def check_risk(
        self,
        stock_code: str,
        entry_price: float,
        current_price: float,
        entry_date: date,
        plate_rank: int = 1,
        plate_strength: float = 100.0
    ) -> RiskCheckResult:
        """
        检查单只股票的风险

        Args:
            stock_code: 股票代码
            entry_price: 买入价格
            current_price: 当前价格
            entry_date: 买入日期
            plate_rank: 当前板块排名
            plate_strength: 当前板块强势度

        Returns:
            RiskCheckResult: 风险检查结果
        """
        # 计算盈亏比例
        profit_pct = (current_price - entry_price) / entry_price * 100

        # 计算持有天数
        holding_days = (date.today() - entry_date).days

        # 更新最高价
        self._update_highest_price(stock_code, current_price)
        highest_price = self._highest_prices.get(stock_code, current_price)

        # 检查各种止盈止损条件
        # 1. 目标止盈
        if profit_pct >= self.config.target_profit_pct:
            return RiskCheckResult(
                stock_code=stock_code,
                action=RiskAction.TAKE_PROFIT,
                reason=f"目标止盈: 盈利 {profit_pct:.2f}% >= {self.config.target_profit_pct}%",
                profit_pct=profit_pct,
                holding_days=holding_days,
                plate_rank=plate_rank,
                should_sell=True,
                urgency=8
            )

        # 2. 移动止盈
        if profit_pct >= self.config.trailing_trigger_pct:
            # 计算从最高点的回撤
            highest_profit = (highest_price - entry_price) / entry_price * 100
            drawdown = highest_profit - profit_pct

            if drawdown >= self.config.trailing_callback_pct:
                return RiskCheckResult(
                    stock_code=stock_code,
                    action=RiskAction.TAKE_PROFIT,
                    reason=f"移动止盈: 从最高点回撤 {drawdown:.2f}% >= {self.config.trailing_callback_pct}%",
                    profit_pct=profit_pct,
                    holding_days=holding_days,
                    plate_rank=plate_rank,
                    should_sell=True,
                    urgency=7
                )

        # 3. 固定止损
        if profit_pct <= self.config.fixed_stop_loss_pct:
            return RiskCheckResult(
                stock_code=stock_code,
                action=RiskAction.STOP_LOSS,
                reason=f"固定止损: 亏损 {profit_pct:.2f}% <= {self.config.fixed_stop_loss_pct}%",
                profit_pct=profit_pct,
                holding_days=holding_days,
                plate_rank=plate_rank,
                should_sell=True,
                urgency=10
            )

        # 4. 快速止损（亏损+板块走弱）
        if profit_pct <= self.config.quick_stop_loss_pct:
            if plate_rank > self.config.plate_rank_threshold or plate_strength < 70:
                return RiskCheckResult(
                    stock_code=stock_code,
                    action=RiskAction.QUICK_STOP,
                    reason=f"快速止损: 亏损 {profit_pct:.2f}% 且板块走弱 (排名第{plate_rank})",
                    profit_pct=profit_pct,
                    holding_days=holding_days,
                    plate_rank=plate_rank,
                    should_sell=True,
                    urgency=9
                )

        # 5. 板块止损
        if plate_rank > self.config.plate_rank_threshold:
            return RiskCheckResult(
                stock_code=stock_code,
                action=RiskAction.PLATE_STOP,
                reason=f"板块止损: 板块跌出前{self.config.plate_rank_threshold}名 (当前第{plate_rank}名)",
                profit_pct=profit_pct,
                holding_days=holding_days,
                plate_rank=plate_rank,
                should_sell=True,
                urgency=6
            )

        # 6. 时间止损
        if holding_days >= self.config.max_holding_days:
            if profit_pct < self.config.min_profit_after_days:
                return RiskCheckResult(
                    stock_code=stock_code,
                    action=RiskAction.TIME_STOP,
                    reason=f"时间止损: 持有{holding_days}天, 盈利{profit_pct:.2f}% < {self.config.min_profit_after_days}%",
                    profit_pct=profit_pct,
                    holding_days=holding_days,
                    plate_rank=plate_rank,
                    should_sell=True,
                    urgency=5
                )

        # 继续持有
        return RiskCheckResult(
            stock_code=stock_code,
            action=RiskAction.HOLD,
            reason=f"继续持有: 盈利{profit_pct:.2f}%, 持有{holding_days}天, 板块第{plate_rank}名",
            profit_pct=profit_pct,
            holding_days=holding_days,
            plate_rank=plate_rank,
            should_sell=False,
            urgency=0
        )

    def _update_highest_price(self, stock_code: str, current_price: float):
        """更新最高价记录"""
        if stock_code not in self._highest_prices:
            self._highest_prices[stock_code] = current_price
        else:
            self._highest_prices[stock_code] = max(
                self._highest_prices[stock_code],
                current_price
            )

    def reset_highest_price(self, stock_code: str):
        """重置最高价记录（清仓时调用）"""
        if stock_code in self._highest_prices:
            del self._highest_prices[stock_code]

    def batch_check_risk(
        self,
        positions: List[Dict[str, Any]],
        plate_ranks: Dict[str, int] = None,
        plate_strengths: Dict[str, float] = None
    ) -> List[RiskCheckResult]:
        """
        批量检查持仓风险

        Args:
            positions: 持仓列表 [{stock_code, entry_price, current_price, entry_date, plate_code}]
            plate_ranks: 板块排名 {plate_code: rank}
            plate_strengths: 板块强势度 {plate_code: strength}

        Returns:
            风险检查结果列表
        """
        results = []
        plate_ranks = plate_ranks or {}
        plate_strengths = plate_strengths or {}

        for pos in positions:
            stock_code = pos.get('stock_code', '')
            entry_price = pos.get('entry_price', 0)
            current_price = pos.get('current_price', 0)
            entry_date = pos.get('entry_date')
            plate_code = pos.get('plate_code', '')

            if isinstance(entry_date, str):
                entry_date = date.fromisoformat(entry_date)

            plate_rank = plate_ranks.get(plate_code, 1)
            plate_strength = plate_strengths.get(plate_code, 100)

            result = self.check_risk(
                stock_code=stock_code,
                entry_price=entry_price,
                current_price=current_price,
                entry_date=entry_date,
                plate_rank=plate_rank,
                plate_strength=plate_strength
            )

            results.append(result)

        # 按紧急程度排序
        results.sort(key=lambda x: x.urgency, reverse=True)

        return results

    def get_sell_signals(self, results: List[RiskCheckResult]) -> List[RiskCheckResult]:
        """
        获取需要卖出的信号

        Args:
            results: 风险检查结果列表

        Returns:
            需要卖出的结果列表
        """
        return [r for r in results if r.should_sell]

    def get_risk_summary(self, results: List[RiskCheckResult]) -> Dict[str, Any]:
        """
        获取风险摘要

        Args:
            results: 风险检查结果列表

        Returns:
            风险摘要
        """
        sell_count = sum(1 for r in results if r.should_sell)
        hold_count = sum(1 for r in results if not r.should_sell)

        # 统计各类动作
        action_counts = {}
        for r in results:
            action = r.action.value
            action_counts[action] = action_counts.get(action, 0) + 1

        # 计算平均盈亏
        avg_profit = sum(r.profit_pct for r in results) / len(results) if results else 0

        return {
            'total_positions': len(results),
            'sell_count': sell_count,
            'hold_count': hold_count,
            'avg_profit_pct': round(avg_profit, 2),
            'action_counts': action_counts,
            'urgent_sells': [r.to_dict() for r in results if r.urgency >= 8]
        }

    def update_config(self, **kwargs):
        """
        更新配置

        Args:
            **kwargs: 配置参数
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                self.logger.info(f"更新风险配置 {key} = {value}")

    def clear_cache(self):
        """清空缓存"""
        self._highest_prices.clear()
