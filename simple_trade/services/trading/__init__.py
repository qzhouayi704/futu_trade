#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易服务模块
包含订单管理、持仓管理、账户管理、激进策略交易和分仓止盈子服务
"""

# 从子模块导入，保持向后兼容
from .execution import (
    OrderManager,
    PositionManager,
    AccountManager,
    TradeConfirmer,
    PendingConfirmation,
)
from .risk import (
    RiskCoordinator,
    RiskDecision,
    DynamicStopLossStrategy,
    DynamicStopLossConfig,
)
from .profit import (
    LotTakeProfitService,
    LotOrderTakeProfitService,
    LotPriceMonitor,
    LotTaskManager,
    PositionLot,
    TakeProfitTask,
    TakeProfitExecution,
)
from .aggressive import (
    AggressiveSignalProcessor,
    AggressiveOrderManager,
    AggressiveTradeService,
    AutoTradeService,
    AutoTradeTask,
    MarketContext,
)
# 协调服务
from .futu_trade_service import FutuTradeService
from .trade_service import TradeService

__all__ = [
    # execution
    'OrderManager',
    'PositionManager',
    'AccountManager',
    'TradeConfirmer',
    'PendingConfirmation',
    # risk
    'RiskCoordinator',
    'RiskDecision',
    'DynamicStopLossStrategy',
    'DynamicStopLossConfig',
    # profit
    'LotTakeProfitService',
    'LotOrderTakeProfitService',
    'LotPriceMonitor',
    'LotTaskManager',
    'PositionLot',
    'TakeProfitTask',
    'TakeProfitExecution',
    # aggressive
    'AggressiveSignalProcessor',
    'AggressiveOrderManager',
    'AggressiveTradeService',
    'AutoTradeService',
    'AutoTradeTask',
    'MarketContext',
    # coordination
    'FutuTradeService',
    'TradeService',
]
