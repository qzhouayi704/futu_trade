#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心模块

包含：
- StateManager: 统一状态管理器
- ServiceResult: 标准服务返回格式
- ServiceContainer: 服务容器
- SystemCoordinator: 系统协调器
- StrategyDispatcher: 策略调度器
- DataModels: 强类型数据模型
- SignalScorer: 信号评分器
- RiskChecker: 风险检查器
- Exceptions: FastAPI 异常类
- ExceptionHandlers: FastAPI 异常处理器
"""

from .state import StateManager, get_state_manager
from .service_result import ServiceResult, ServiceResultBuilder, success_result, error_result
from .container import ServiceContainer
from .coordination import SystemCoordinator, StrategyDispatcher
from .pipeline import (
    QuotePipeline,
    Plate,
    Stock,
    StockWithPlate,
    KlineData,
    TradeSignal,
    Quote,
    TradingCondition,
    IndexInfo,
    stocks_to_dict_list,
    plates_to_dict_list,
    klines_to_dict_list,
    signals_to_dict_list,
    quotes_to_dict_list,
)

# 激进策略相关
from .validation import SignalScorer, SignalScore, RiskChecker, RiskCheckResult, RiskAction, RiskConfig

# FastAPI 异常处理
from .exceptions import (
    APIException,
    ValidationError,
    NotFoundError,
    ConflictError,
    BusinessError,
    DatabaseError,
    ExternalAPIError,
    UnauthorizedError,
    ForbiddenError,
    register_exception_handlers,
)

__all__ = [
    'StateManager',
    'get_state_manager',
    'ServiceResult',
    'ServiceResultBuilder',
    'success_result',
    'error_result',
    'ServiceContainer',
    'SystemCoordinator',
    'StrategyDispatcher',
    'QuotePipeline',
    # 数据模型
    'Plate',
    'Stock',
    'StockWithPlate',
    'KlineData',
    'TradeSignal',
    'Quote',
    'TradingCondition',
    'IndexInfo',
    'stocks_to_dict_list',
    'plates_to_dict_list',
    'klines_to_dict_list',
    'signals_to_dict_list',
    'quotes_to_dict_list',
    # 激进策略相关
    'SignalScorer',
    'SignalScore',
    'RiskChecker',
    'RiskCheckResult',
    'RiskAction',
    'RiskConfig',
    # FastAPI 异常
    'APIException',
    'ValidationError',
    'NotFoundError',
    'ConflictError',
    'BusinessError',
    'DatabaseError',
    'ExternalAPIError',
    'UnauthorizedError',
    'ForbiddenError',
    'register_exception_handlers',
]

