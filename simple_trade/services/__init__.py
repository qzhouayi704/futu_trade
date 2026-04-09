#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
业务服务模块

服务层次结构：
1. 基础层（无服务依赖）：PlateManager, DataInitializer, AlertService, FutuTradeService
2. 初始化服务：PlateInitializerService, StockInitializerService, ExtendedInitializer
3. 中间层：RealtimeService, KlineDataService, StockPoolService
4. 应用层：TradeService, StrategyScreeningService, PriceMonitorService
5. 辅助服务：ActivityFilterService, StockMarkerService, SubscriptionVersionService
"""

# 基础层服务
from .market_data.plate import PlateManager
from .market_data.plate import PlateFetcher
from .market_data.plate import PlateStockManager
from .core import DataInitializer
from .alert.alert_checker import AlertChecker
from .trading import FutuTradeService

# 初始化服务（DataInitializer 拆分出的服务）
from .market_data.plate import PlateInitializerService
from .core import (
    StockInitializerService,
    ExtendedInitializer,
    InitializationHelper,
)
from .core import DefaultDataProvider

# 中间层服务
from .subscription.subscription_helper import SubscriptionHelper
from .realtime.realtime_query import RealtimeQuery
from .market_data.kline import KlineDataService
from .pool.stock_pool import StockPoolService

# 辅助服务（RealtimeService 拆分出的服务）
from .market_data.activity_filter import ActivityFilterService
from .core import StockMarkerService
from .subscription.subscription_version import SubscriptionVersionService
from .realtime.realtime_kline_service import RealtimeKlineService
from .realtime.realtime_stock_query_service import RealtimeStockQueryService
from .realtime.realtime_quote_service_wrapper import RealtimeQuoteServiceWrapper

# 应用层服务
from .trading import TradeService
from .core import (
    StrategyMonitorService,
    StrategyScreeningService,
)
from .alert.price_monitor_service import PriceMonitorService

# 激进策略相关服务
from .market_data.plate import PlateStrengthService, PlateStrengthScore
from .market_data import LeaderStockFilter, LeaderStockCandidate, LeaderFilterConfig
from .trading import AggressiveTradeService

# 股票池工具函数
from .pool.stock_pool import (
    get_global_stock_pool,
    set_global_stock_pool,
    get_active_stocks_from_pool,
    get_initialization_progress,
    refresh_global_stock_pool_from_db
)

__all__ = [
    # 基础层服务
    'PlateManager',
    'PlateFetcher',
    'PlateStockManager',
    'DataInitializer',
    'AlertChecker',
    'FutuTradeService',
    # 初始化服务
    'PlateInitializerService',
    'StockInitializerService',
    'ExtendedInitializer',
    'DefaultDataProvider',
    'InitializationHelper',
    # 中间层服务
    'SubscriptionHelper',
    'RealtimeQuery',
    'KlineDataService',
    'StockPoolService',
    # 辅助服务
    'ActivityFilterService',
    'StockMarkerService',
    'SubscriptionVersionService',
    'RealtimeKlineService',
    'RealtimeStockQueryService',
    'RealtimeQuoteServiceWrapper',
    # 应用层服务
    'TradeService',
    'StrategyMonitorService',
    'StrategyScreeningService',
    'PriceMonitorService',
    # 激进策略相关服务
    'PlateStrengthService',
    'PlateStrengthScore',
    'LeaderStockFilter',
    'LeaderStockCandidate',
    'LeaderFilterConfig',
    'AggressiveTradeService',
    # 股票池工具函数
    'get_global_stock_pool',
    'set_global_stock_pool',
    'get_active_stocks_from_pool',
    'get_initialization_progress',
    'refresh_global_stock_pool_from_db',
]
