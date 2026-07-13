#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""富途成交时间解析工具。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


_INVALID_TEXT = {"", "nan", "nat", "none", "null"}


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
