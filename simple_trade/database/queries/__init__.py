#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库查询模块 - 各业务领域的查询实现
"""

from .stock_queries import StockQueries
from .stock_activity_queries import StockActivityQueries
from .plate_queries import PlateQueries
from .trade_queries import TradeQueries
from .trade_history_queries import TradeHistoryQueries
from .kline_queries import KlineQueries
from .news_queries import NewsQueries
from .system_queries import SystemQueries

__all__ = [
    'StockQueries',
    'StockActivityQueries',
    'PlateQueries',
    'TradeQueries',
    'TradeHistoryQueries',
    'KlineQueries',
    'NewsQueries',
    'SystemQueries',
]
