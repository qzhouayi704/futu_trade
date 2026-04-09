#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐笔成交分析模块

提供基于富途 get_rt_ticker 的逐笔成交数据获取、
4维度成交分析、以及与挂单分析的综合多空判断。
"""

from .ticker_service import TickerService, TickerRecord, TickerData
from .ticker_analyzer import TickerAnalyzer, TickerDimensionSignal, TickerAnalysis
from .combined_analyzer import CombinedAnalyzer, CombinedAnalysis
from .price_distribution import PriceLevelItem, PriceLevelData, compute_price_distribution

__all__ = [
    # 数据服务
    'TickerService',
    'TickerRecord',
    'TickerData',
    # 成交分析器
    'TickerAnalyzer',
    'TickerDimensionSignal',
    'TickerAnalysis',
    # 综合分析器
    'CombinedAnalyzer',
    'CombinedAnalysis',
    # 价位成交分布
    'PriceLevelItem',
    'PriceLevelData',
    'compute_price_distribution',
]
