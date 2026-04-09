"""
回测日期工具模块

提供日期范围计算、交易日推算等功能
"""

from datetime import datetime, timedelta
from typing import Tuple, Optional


def get_default_date_range(days: int = 365) -> Tuple[str, str]:
    """
    获取默认日期范围

    Args:
        days: 回看天数（默认365天，即1年）

    Returns:
        (start_date, end_date) 格式为 'YYYY-MM-DD'
    """
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    return start_date, end_date


def parse_date_range(
    start: Optional[str] = None,
    end: Optional[str] = None,
    default_days: int = 365
) -> Tuple[str, str]:
    """
    从参数解析日期范围

    Args:
        start: 开始日期（YYYY-MM-DD），如果为None则使用默认值
        end: 结束日期（YYYY-MM-DD），如果为None则使用今天
        default_days: 默认回看天数（当start为None时使用）

    Returns:
        (start_date, end_date) 格式为 'YYYY-MM-DD'
    """
    if end:
        end_date = end
    else:
        end_date = datetime.now().strftime('%Y-%m-%d')

    if start:
        start_date = start
    else:
        start_dt = datetime.now() - timedelta(days=default_days)
        start_date = start_dt.strftime('%Y-%m-%d')

    return start_date, end_date


def validate_date_format(date_str: str) -> bool:
    """
    验证日期格式是否为 YYYY-MM-DD

    Args:
        date_str: 日期字符串

    Returns:
        True if valid, False otherwise
    """
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False


def validate_date_range(start: str, end: str) -> bool:
    """
    验证日期范围是否有效

    Args:
        start: 开始日期（YYYY-MM-DD）
        end: 结束日期（YYYY-MM-DD）

    Returns:
        True if valid (start <= end), False otherwise
    """
    try:
        start_dt = datetime.strptime(start, '%Y-%m-%d')
        end_dt = datetime.strptime(end, '%Y-%m-%d')
        return start_dt <= end_dt
    except ValueError:
        return False


def calculate_days_between(start: str, end: str) -> int:
    """
    计算两个日期之间的天数

    Args:
        start: 开始日期（YYYY-MM-DD）
        end: 结束日期（YYYY-MM-DD）

    Returns:
        天数（包含起始日）
    """
    start_dt = datetime.strptime(start, '%Y-%m-%d')
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    return (end_dt - start_dt).days + 1
