#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
富途API模块

模块结构：
- futu_client: 连接管理和K线服务
- subscription_manager: 订阅状态管理（唯一数据源）
- quote_service: 报价获取服务
- market_types: 类型包装
- stock_data: 股票数据服务
"""

from .futu_client import FutuClient
from .subscription_manager import SubscriptionManager
from .quote_service import QuoteService
from .market_types import MarketType, SubscriptionType, ReturnCode
from .stock_data import StockDataService

__all__ = [
    'FutuClient',
    'SubscriptionManager',
    'QuoteService',
    'MarketType',
    'SubscriptionType',
    'ReturnCode',
    'StockDataService'
]
