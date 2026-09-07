#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""富途成交时间解析工具。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


_INVALID_TEXT = {"", "nan", "nat", "none", "null"}
HK_TIMEZONE = timezone(timedelta(hours=8))


def market_datetime(value, stock_code: str = "HK.") -> Optional[datetime]:
    """解析事件时间，并将历史无时区时间视为对应市场的本地时间。"""
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if stock_code.upper().startswith("US."):
            from zoneinfo import ZoneInfo

            market_tz = ZoneInfo("America/New_York")
        else:
            market_tz = HK_TIMEZONE
        return (
            parsed.replace(tzinfo=market_tz)
            if parsed.tzinfo is None else parsed.astimezone(market_tz)
        )
    except (TypeError, ValueError, KeyError):
        return None


def is_hk_continuous_session(value) -> bool:
    """普通港股连续交易时段；竞价与休市日历由上层分别处理。"""
    parsed = market_datetime(value)
    if parsed is None or parsed.weekday() >= 5:
        return False
    from datetime import time

    local_time = parsed.time()
    return time(9, 30) <= local_time < time(12) or time(13) <= local_time <= time(16)


def normalize_futu_trade_time(value) -> Optional[str]:
    """把富途逐笔时间转成可持久化文本；无效值返回 ``None``。"""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _INVALID_TEXT:
        return None
    try:
        datetime.fromisoformat(text.replace("T", " ", 1))
    except (TypeError, ValueError):
        return None
    return text


def futu_trade_date(value) -> Optional[str]:
    """提取富途成交日（YYYY-MM-DD）；格式无效时返回 ``None``。"""
    text = normalize_futu_trade_time(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("T", " ", 1)).strftime("%Y-%m-%d")
    except ValueError:
        return None


def futu_trade_timestamp(value, market: str) -> Optional[float]:
    """把无时区的市场本地成交时间转换为 Unix 秒时间戳。"""
    text = normalize_futu_trade_time(value)
    if text is None:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("T", " ", 1))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        return dt.timestamp()

    if market == "US":
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo("America/New_York")
        except Exception:
            tz = timezone(timedelta(hours=-5))
    else:
        tz = timezone(timedelta(hours=8))
    return dt.replace(tzinfo=tz).timestamp()
