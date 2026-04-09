#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易策略模块

提供策略基类、策略注册器和具体策略实现。

使用示例：
```python
# 1. 导入策略相关模块
from simple_trade.strategy import (
    BaseStrategy, 
    StrategyResult, 
    StrategyRegistry,
    SwingStrategy
)

# 2. 通过注册器获取策略
strategy = StrategyRegistry.create_instance("swing", data_service=service)

# 3. 或直接使用具体策略类
strategy = SwingStrategy(data_service=service)

# 4. 检查交易信号
result = strategy.check_signals(code, quote_data, kline_data)

# 5. 列出所有可用策略
all_strategies = StrategyRegistry.list_strategies()
```
"""

# 策略基类和数据类
from .base_strategy import (
    BaseStrategy,
    StrategyResult,
    ConditionDetail,
    TradingConditionResult
)

# 策略注册器
from .strategy_registry import (
    StrategyRegistry,
    register_strategy,
    auto_discover_strategies
)

# 具体策略实现
from .swing_strategy import SwingStrategy
from .trend_reversal import TrendReversalStrategy
from .aggressive_strategy import AggressiveStrategy
from .price_position_live_strategy import PricePositionLiveStrategy

# 导出列表
__all__ = [
    # 基类和数据类
    'BaseStrategy',
    'StrategyResult',
    'ConditionDetail',
    'TradingConditionResult',

    # 注册器
    'StrategyRegistry',
    'register_strategy',
    'auto_discover_strategies',

    # 具体策略
    'SwingStrategy',
    'TrendReversalStrategy',
    'AggressiveStrategy',
    'PricePositionLiveStrategy',
]


def get_available_strategies():
    """
    获取所有可用策略的简要信息
    
    Returns:
        策略信息列表
    """
    return StrategyRegistry.list_strategies()


def get_default_strategy(data_service=None, config=None):
    """
    获取默认策略实例
    
    Args:
        data_service: 数据服务
        config: 策略配置
        
    Returns:
        默认策略实例
    """
    return StrategyRegistry.create_instance(data_service=data_service, config=config)
