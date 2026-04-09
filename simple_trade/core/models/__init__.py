#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模型模块

导出所有数据模型类和工具函数
"""

from .plate_models import Plate
from .stock_models import Stock, StockWithPlate
from .stock_info import StockInfo
from .kline_models import KlineData
from .trade_models import TradeSignal, TradingCondition
from .quote_models import Quote, IndexInfo
from typing import List


# 工具函数

def stocks_to_dict_list(stocks: List[Stock]) -> List[dict]:
    """批量转换 Stock 列表为字典列表"""
    return [stock.to_dict() for stock in stocks]


def plates_to_dict_list(plates: List[Plate]) -> List[dict]:
    """批量转换 Plate 列表为字典列表"""
    return [plate.to_dict() for plate in plates]


def klines_to_dict_list(klines: List[KlineData]) -> List[dict]:
    """批量转换 KlineData 列表为字典列表"""
    return [kline.to_dict() for kline in klines]


def signals_to_dict_list(signals: List[TradeSignal]) -> List[dict]:
    """批量转换 TradeSignal 列表为字典列表"""
    return [signal.to_dict() for signal in signals]


def quotes_to_dict_list(quotes: List[Quote]) -> List[dict]:
    """批量转换 Quote 列表为字典列表"""
    return [quote.to_dict() for quote in quotes]


__all__ = [
    'Plate',
    'Stock',
    'StockWithPlate',
    'StockInfo',
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
]
