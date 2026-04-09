#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
错误解析工具模块

提供统一的富途API错误解析函数
"""

from typing import Tuple, Any


def parse_futu_error(ret: int, data: Any) -> Tuple[str, str]:
    """
    解析富途API错误信息

    Args:
        ret: 富途API返回码（-1表示失败）
        data: 富途API返回的错误信息

    Returns:
        (错误消息, 错误类型) 元组

    错误类型包括：
        - quota: 额度不足
        - rate_limit: 请求频率过高
        - not_found: 股票代码无效或已退市
        - timeout: 请求超时
        - api_error: API错误
        - unknown: 未知错误
    """
    if ret == -1:
        if data is not None:
            s = str(data).lower()
            if 'quota' in s or '额度' in s:
                return "K线额度不足", "quota"
            if 'frequency' in s or '频率' in s:
                return "请求频率过高", "rate_limit"
            if 'not found' in s or '不存在' in s:
                return "股票代码无效或已退市", "not_found"
            if 'timeout' in s or '超时' in s:
                return "请求超时", "timeout"
            # 返回原始错误信息
            return f"API错误: {data}", "api_error"
        return "API返回错误", "api_error"

    # ret != -1 但仍然可能有错误
    if data is not None and isinstance(data, str):
        return data, "unknown"

    return "未知错误", "unknown"


def format_error_message(ret: int, data: Any, prefix: str = "") -> str:
    """
    格式化富途API错误消息

    Args:
        ret: 富途API返回码
        data: 富途API返回的错误信息
        prefix: 错误消息前缀

    Returns:
        格式化后的错误消息
    """
    message, error_type = parse_futu_error(ret, data)

    if prefix:
        return f"{prefix}: {message}"
    return message
