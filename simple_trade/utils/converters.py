#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
类型转换工具模块

提供安全的类型转换函数，处理 None、空字符串、N/A 等异常值
"""

from typing import Any, Union


def safe_float(value: Any, default: float = 0.0) -> float:
    """
    安全转换为 float，处理 N/A、None、空字符串等异常值

    Args:
        value: 待转换的值
        default: 转换失败时的默认值

    Returns:
        转换后的浮点数
    """
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """
    安全转换为 int，处理 None、空字符串等异常值

    Args:
        value: 待转换的值
        default: 转换失败时的默认值

    Returns:
        转换后的整数
    """
    if value is None:
        return default
    try:
        return int(float(value))  # 先转float再转int，处理 "1.5" 这种情况
    except (ValueError, TypeError):
        return default


def safe_str(value: Any, default: str = "") -> str:
    """
    安全转换为 str，处理 None 等异常值

    Args:
        value: 待转换的值
        default: 转换失败时的默认值

    Returns:
        转换后的字符串
    """
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def parse_percentage(value: Union[str, float, None], default: float = 0.0) -> float:
    """
    解析百分比字符串为浮点数

    Args:
        value: 百分比值，可以是 "5.5%"、"5.5"、5.5 等格式
        default: 解析失败时的默认值

    Returns:
        解析后的浮点数（不带百分号）

    Examples:
        >>> parse_percentage("5.5%")
        5.5
        >>> parse_percentage("5.5")
        5.5
        >>> parse_percentage(5.5)
        5.5
    """
    if value is None:
        return default

    try:
        if isinstance(value, str):
            # 移除百分号和空格
            value = value.strip().rstrip('%')
        return float(value)
    except (ValueError, TypeError):
        return default


def get_last_price(quote: dict, default: float = 0.0) -> float:
    """
    从报价字典中提取最新价格

    统一处理不同数据源返回的字段名差异：
    last_price / current_price / cur_price / price

    Args:
        quote: 报价字典
        default: 所有字段都不存在时的默认值

    Returns:
        最新价格
    """
    if not quote:
        return default
    for key in ('last_price', 'current_price', 'cur_price', 'price'):
        val = quote.get(key)
        if val is not None and val != 0:
            return safe_float(val, default)
    return default
