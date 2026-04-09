#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置策略 — 分类函数

包含：
- classify_zone: 价格位置 → 区间名称
- classify_open_type: 开盘价 → 开盘类型
- classify_sentiment: 涨跌幅 → 情绪等级
- build_sentiment_map: ETF K线数据 → 日期情绪映射表
"""

from typing import Dict, List, Any, Optional

from .constants import (
    ZONE_DEFINITIONS,
    ZONE_NAMES,
    DEFAULT_GAP_THRESHOLD,
    OPEN_TYPE_GAP_UP,
    OPEN_TYPE_FLAT,
    OPEN_TYPE_GAP_DOWN,
    DEFAULT_SENTIMENT_THRESHOLDS,
    SENTIMENT_BEARISH,
    SENTIMENT_NEUTRAL,
    SENTIMENT_BULLISH,
)


def classify_zone(position: float) -> str:
    """
    将价格位置(0-100)映射到5个区间名称

    Args:
        position: 价格位置百分比 [0, 100]

    Returns:
        区间名称
    """
    # 钳位到 [0, 100]
    position = max(0.0, min(100.0, position))

    for zone_name, (low, high) in ZONE_DEFINITIONS.items():
        if low <= position < high:
            return zone_name
        # 最后一个区间包含右边界 100
        if high == 100 and position == 100:
            return zone_name

    # 不应到达这里，但作为安全回退
    return ZONE_NAMES[-1]


def classify_open_type(
    open_price: float,
    prev_close: float,
    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
) -> str:
    """
    将开盘价相对前收盘价的涨跌幅映射到开盘类型

    Args:
        open_price: 开盘价（> 0）
        prev_close: 前收盘价（> 0）
        gap_threshold: 阈值百分比，默认 0.5%

    Returns:
        'gap_up' / 'flat' / 'gap_down'
    """
    open_gap_pct = (open_price - prev_close) / prev_close * 100

    if open_gap_pct > gap_threshold:
        return OPEN_TYPE_GAP_UP
    elif open_gap_pct < -gap_threshold:
        return OPEN_TYPE_GAP_DOWN
    else:
        return OPEN_TYPE_FLAT


def classify_sentiment(
    sentiment_pct: float,
    thresholds: Optional[Dict[str, float]] = None,
) -> str:
    """
    将恒生科技ETF涨跌幅映射到情绪等级

    Args:
        sentiment_pct: 当天涨跌幅百分比
        thresholds: 阈值配置，包含 bearish_threshold 和 bullish_threshold

    Returns:
        'bearish' / 'neutral' / 'bullish'
    """
    if thresholds is None:
        thresholds = DEFAULT_SENTIMENT_THRESHOLDS

    bearish_th = thresholds.get('bearish_threshold', -1.0)
    bullish_th = thresholds.get('bullish_threshold', 1.0)

    if sentiment_pct < bearish_th:
        return SENTIMENT_BEARISH
    elif sentiment_pct > bullish_th:
        return SENTIMENT_BULLISH
    else:
        return SENTIMENT_NEUTRAL


def build_sentiment_map(
    etf_kline_data: List[Dict[str, Any]],
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    从恒生科技ETF的K线数据构建日期→情绪映射表

    Args:
        etf_kline_data: ETF日线K线数据（按时间正序）
        thresholds: 情绪阈值配置

    Returns:
        {date_str: {'sentiment_pct': float, 'sentiment_level': str}}
    """
    if thresholds is None:
        thresholds = DEFAULT_SENTIMENT_THRESHOLDS

    sentiment_map = {}

    for i in range(1, len(etf_kline_data)):
        current = etf_kline_data[i]
        prev = etf_kline_data[i - 1]

        prev_close = prev.get('close_price', 0)
        close_price = current.get('close_price', 0)

        if prev_close <= 0 or close_price <= 0:
            continue

        sentiment_pct = (close_price - prev_close) / prev_close * 100
        # 直接调用同模块的 classify_sentiment（而非原来的类方法）
        sentiment_level = classify_sentiment(sentiment_pct, thresholds)

        date_str = current.get('time_key', '')[:10]
        sentiment_map[date_str] = {
            'sentiment_pct': round(sentiment_pct, 4),
            'sentiment_level': sentiment_level,
        }

    return sentiment_map
