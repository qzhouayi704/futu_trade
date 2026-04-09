#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置策略 — 统计计算

包含：
- calculate_daily_metrics: 计算每日涨跌幅和价格位置
- compute_zone_statistics: 按区间分组计算涨跌幅统计
- compute_stats: 计算统计指标（均值、中位数、标准差、分位数等）
- empty_stats: 空统计结果
"""

import numpy as np
from typing import Dict, List, Any, Optional

from .constants import (
    ZONE_NAMES,
    OPEN_TYPE_FLAT,
    SENTIMENT_NEUTRAL,
    DEFAULT_GAP_THRESHOLD,
)
from .classifiers import (
    classify_zone,
    classify_open_type,
)


def empty_stats() -> Dict[str, float]:
    """空统计结果"""
    return {'mean': 0, 'median': 0, 'std': 0, 'p25': 0, 'p75': 0, 'min': 0, 'max': 0}


def compute_stats(values: np.ndarray) -> Dict[str, float]:
    """
    计算统计指标

    Args:
        values: numpy 数组

    Returns:
        包含 mean, median, std, p25, p75, min, max 的字典
    """
    if len(values) == 0:
        return empty_stats()
    return {
        'mean': round(float(np.mean(values)), 4),
        'median': round(float(np.median(values)), 4),
        'std': round(float(np.std(values)), 4),
        'p25': round(float(np.percentile(values, 25)), 4),
        'p75': round(float(np.percentile(values, 75)), 4),
        'min': round(float(np.min(values)), 4),
        'max': round(float(np.max(values)), 4),
    }


def compute_zone_statistics(metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    按区间分组计算涨跌幅统计分布

    Args:
        metrics: calculate_daily_metrics() 的输出

    Returns:
        嵌套字典：{zone_name: {count, frequency_pct, rise_stats, drop_stats}}
    """
    total = len(metrics)
    if total == 0:
        return {}

    zone_data = {name: [] for name in ZONE_NAMES}
    for m in metrics:
        zone = m['zone']
        if zone in zone_data:
            zone_data[zone].append(m)

    result = {}
    for zone_name in ZONE_NAMES:
        data = zone_data[zone_name]
        count = len(data)
        frequency_pct = round(count / total * 100, 2) if total > 0 else 0.0

        if count == 0:
            result[zone_name] = {
                'count': 0,
                'frequency_pct': 0.0,
                'rise_stats': empty_stats(),
                'drop_stats': empty_stats(),
            }
            continue

        rises = np.array([d['high_rise_pct'] for d in data])
        drops = np.array([d['low_drop_pct'] for d in data])

        result[zone_name] = {
            'count': count,
            'frequency_pct': frequency_pct,
            'rise_stats': compute_stats(rises),
            'drop_stats': compute_stats(drops),
        }

    return result


def calculate_daily_metrics(
    kline_data: List[Dict[str, Any]],
    lookback_days: int,
    sentiment_map: Optional[Dict[str, Dict[str, Any]]] = None,
    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
) -> List[Dict[str, Any]]:
    """
    计算每日涨跌幅和价格位置

    Args:
        kline_data: 按时间正序的日线K线数据列表
        lookback_days: 回看天数
        sentiment_map: 日期→情绪映射表（可选）
        gap_threshold: 开盘类型判定阈值，默认 0.5%

    Returns:
        每日指标列表
    """
    metrics = []

    for i in range(1, len(kline_data)):
        current = kline_data[i]
        prev = kline_data[i - 1]

        prev_close = prev.get('close_price', 0)
        if prev_close <= 0:
            continue

        high_price = current.get('high_price', 0)
        low_price = current.get('low_price', 0)
        close_price = current.get('close_price', 0)

        if high_price <= 0 or low_price <= 0 or close_price <= 0:
            continue

        # 涨跌幅计算
        high_rise_pct = (high_price - prev_close) / prev_close * 100
        low_drop_pct = (low_price - prev_close) / prev_close * 100

        # 需要至少 lookback_days 天的历史数据
        if i < lookback_days:
            continue

        lookback_start = max(0, i - lookback_days)
        lookback_slice = kline_data[lookback_start:i + 1]  # 包含当天

        highs = [k.get('high_price', 0) for k in lookback_slice if k.get('high_price', 0) > 0]
        lows = [k.get('low_price', float('inf')) for k in lookback_slice if k.get('low_price', 0) > 0]

        if not highs or not lows:
            continue

        period_high = max(highs)
        period_low = min(lows)

        if period_high == period_low:
            price_position = 50.0
        else:
            price_position = (close_price - period_low) / (period_high - period_low) * 100
            price_position = max(0.0, min(100.0, price_position))

        zone = classify_zone(price_position)

        metric = {
            'date': current.get('time_key', '')[:10],
            'stock_code': current.get('stock_code', ''),
            'prev_close': prev_close,
            'open_price': current.get('open_price', 0),
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': round(high_rise_pct, 4),
            'low_drop_pct': round(low_drop_pct, 4),
            'price_position': round(price_position, 2),
            'zone': zone,
        }

        # 附加开盘类型数据
        cur_open_price = current.get('open_price', 0)
        if cur_open_price > 0 and prev_close > 0:
            open_gap_pct = (cur_open_price - prev_close) / prev_close * 100
            open_type = classify_open_type(cur_open_price, prev_close, gap_threshold)
        else:
            open_gap_pct = 0.0
            open_type = OPEN_TYPE_FLAT
        metric['open_type'] = open_type
        metric['open_gap_pct'] = round(open_gap_pct, 4)

        # 附加情绪数据
        if sentiment_map is not None:
            date_str = metric['date']
            sentiment_info = sentiment_map.get(date_str, {})
            metric['sentiment_pct'] = sentiment_info.get('sentiment_pct', 0.0)
            metric['sentiment_level'] = sentiment_info.get('sentiment_level', SENTIMENT_NEUTRAL)
        else:
            metric['sentiment_pct'] = 0.0
            metric['sentiment_level'] = SENTIMENT_NEUTRAL

        metrics.append(metric)

    return metrics
