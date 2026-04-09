#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略数据模型

从 base_strategy.py 中提取的数据类定义：
- StrategyResult: 策略检查结果
- ConditionDetail: 条件详情
- TradingConditionResult: 交易条件检查结果
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime


@dataclass
class StrategyResult:
    """
    策略检查结果

    统一的策略返回值格式，包含信号、原因和详细数据。
    """
    stock_code: str                          # 股票代码
    buy_signal: bool = False                 # 买入信号
    sell_signal: bool = False                # 卖出信号
    buy_reason: str = ""                     # 买入原因
    sell_reason: str = ""                    # 卖出原因
    signal_strength: float = 0.0             # 信号强度 (0-1)
    strategy_data: Dict[str, Any] = field(default_factory=dict)  # 策略相关数据
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def has_signal(self) -> bool:
        """是否有交易信号"""
        return self.buy_signal or self.sell_signal

    @property
    def signal_type(self) -> Optional[str]:
        """信号类型：BUY/SELL/None"""
        if self.buy_signal:
            return "BUY"
        elif self.sell_signal:
            return "SELL"
        return None

    @property
    def reason(self) -> str:
        """获取信号原因"""
        if self.buy_signal:
            return self.buy_reason
        elif self.sell_signal:
            return self.sell_reason
        return self.buy_reason or self.sell_reason  # 返回任一非空原因

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'stock_code': self.stock_code,
            'buy_signal': self.buy_signal,
            'sell_signal': self.sell_signal,
            'buy_reason': self.buy_reason,
            'sell_reason': self.sell_reason,
            'signal_strength': self.signal_strength,
            'signal_type': self.signal_type,
            'has_signal': self.has_signal,
            'reason': self.reason,
            'strategy_data': self.strategy_data,
            'timestamp': self.timestamp
        }


@dataclass
class ConditionDetail:
    """
    条件详情

    用于展示单个条件的检查结果。
    """
    name: str                    # 条件名称
    current_value: str           # 当前值
    target_value: str            # 目标值
    passed: bool                 # 是否通过
    description: str = ""        # 详细描述

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'current_value': self.current_value,
            'target_value': self.target_value,
            'passed': self.passed,
            'description': self.description
        }


@dataclass
class TradingConditionResult:
    """
    交易条件检查结果

    包含完整的条件检查信息，用于前端展示。
    """
    stock_code: str
    stock_name: str = ""
    plate_name: str = ""
    strategy_name: str = ""
    condition_passed: bool = False
    reason: str = ""
    details: List[ConditionDetail] = field(default_factory=list)
    strategy_result: Optional[StrategyResult] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def buy_signal(self) -> bool:
        """是否有买入信号"""
        return self.strategy_result.buy_signal if self.strategy_result else False

    @property
    def sell_signal(self) -> bool:
        """是否有卖出信号"""
        return self.strategy_result.sell_signal if self.strategy_result else False

    @property
    def strategy_data(self) -> Dict[str, Any]:
        """获取策略数据"""
        return self.strategy_result.strategy_data if self.strategy_result else {}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'plate_name': self.plate_name,
            'strategy_name': self.strategy_name,
            'condition_passed': self.condition_passed,
            'reason': self.reason,
            'details': [d.to_dict() for d in self.details],
            'buy_signal': self.buy_signal,
            'sell_signal': self.sell_signal,
            'strategy_data': self.strategy_data,
            'timestamp': self.timestamp
        }
