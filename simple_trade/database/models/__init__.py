#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库模型包
导出所有模型类，保持向后兼容
"""

from .schema import DatabaseSchema, TableNames
from .core import PlateModel, StockModel, StockPlateModel, KlineDataModel
from .extended import Kline5MinDataModel, TradeSignalModel, PlateMatchLogModel, NewsModel

__all__ = [
    # Schema
    'DatabaseSchema',
    'TableNames',
    # Core models
    'PlateModel',
    'StockModel',
    'StockPlateModel',
    'KlineDataModel',
    # Extended models
    'Kline5MinDataModel',
    'TradeSignalModel',
    'PlateMatchLogModel',
    'NewsModel',
]
