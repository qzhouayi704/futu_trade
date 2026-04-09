#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘口分析模块

包含盘口数据服务、盘口深度分析器和维度分析函数。
"""

from .order_book_service import OrderBookService, OrderBookData, OrderBookLevel
from .order_book_analyzer import (
    OrderBookAnalyzer,
    OrderBookAnalysis,
    DimensionSignal,
    SIGNAL_BULLISH,
    SIGNAL_SLIGHTLY_BULLISH,
    SIGNAL_NEUTRAL,
    SIGNAL_SLIGHTLY_BEARISH,
    SIGNAL_BEARISH,
    SIGNAL_LABELS,
    _score_to_signal,
    _clamp,
    WEIGHTS,
    DIM_NAMES,
)

__all__ = [
    'OrderBookService',
    'OrderBookData',
    'OrderBookLevel',
    'OrderBookAnalyzer',
    'OrderBookAnalysis',
    'DimensionSignal',
    'SIGNAL_BULLISH',
    'SIGNAL_SLIGHTLY_BULLISH',
    'SIGNAL_NEUTRAL',
    'SIGNAL_SLIGHTLY_BEARISH',
    'SIGNAL_BEARISH',
    'SIGNAL_LABELS',
    '_score_to_signal',
    '_clamp',
    'WEIGHTS',
    'DIM_NAMES',
]
