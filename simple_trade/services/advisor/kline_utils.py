#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""K线数据提取工具 - 统一的 K线字段提取方法，兼容 dict/对象属性/list 三种格式

K线数据在系统中存在三种格式：
1. dict: {'close': 10.5, 'volume': 1000, ...}
2. 对象属性: kline.close, kline.volume
3. list/tuple: [date, open, close, high, low, volume, ...]

本模块提供统一的提取接口，消除各模块中重复的格式兼容逻辑。
"""

from typing import List, Any

# list/tuple 格式下各字段的索引位置
# 格式: [date, open, close, high, low, volume, ...]
FIELD_INDEX_MAP = {
    'date': 0,
    'open': 1,
    'close': 2,
    'high': 3,
    'low': 4,
    'volume': 5,
}


def extract_field(kline: Any, field: str, index: int = -1) -> float:
    """从单条K线中提取指定字段，兼容 dict/对象属性/list 三种格式

    Args:
        kline: 单条K线数据（dict / 带属性的对象 / list / tuple）
        field: 字段名（如 'close', 'volume'）
        index: list/tuple 格式下该字段的索引位置，
               默认 -1 表示从 FIELD_INDEX_MAP 自动查找

    Returns:
        提取到的浮点数值，提取失败返回 0.0
    """
    # dict 格式
    if isinstance(kline, dict):
        return float(kline.get(field, 0))

    # 对象属性格式
    if hasattr(kline, field):
        return float(getattr(kline, field))

    # list/tuple 格式
    if isinstance(kline, (list, tuple)):
        if index < 0:
            index = FIELD_INDEX_MAP.get(field, -1)
        if 0 <= index < len(kline):
            return float(kline[index])

    return 0.0


def extract_closes(klines: List, count: int) -> List[float]:
    """从K线数据中提取收盘价，兼容 dict/对象/list 三种格式

    Args:
        klines: K线数据列表
        count: 从末尾取多少条

    Returns:
        收盘价列表
    """
    return [
        extract_field(k, 'close', FIELD_INDEX_MAP['close'])
        for k in klines[-count:]
    ]


def extract_volumes(klines: List, count: int) -> List[float]:
    """从K线数据中提取成交量，兼容 dict/对象/list 三种格式

    Args:
        klines: K线数据列表
        count: 从末尾取多少条

    Returns:
        成交量列表
    """
    return [
        extract_field(k, 'volume', FIELD_INDEX_MAP['volume'])
        for k in klines[-count:]
    ]
