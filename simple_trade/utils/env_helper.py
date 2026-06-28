#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境变量解析工具

统一散落各处的 `os.environ.get(...).lower() in ("1","true","yes","on")` 写法，
避免每个 feature flag 各写一套布尔解析、accept-set/strip 行为不一致。
"""

import os
from typing import Optional

# 真值集合（取各处历史写法的超集）：含 "on" 并容忍首尾空白
_TRUTHY = {"1", "true", "yes", "on"}


def env_flag(name: str, default: bool = False) -> bool:
    """读取布尔型环境变量。

    Args:
        name: 环境变量名。
        default: 未设置（None）时的默认值。

    规则：未设置返回 default；否则 strip+lower 后命中 {1,true,yes,on} 为 True，其余 False。
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def parse_flag(raw, default: bool = False) -> bool:
    """解析任意来源（env/config/system_config）的布尔值。

    与 env_flag 的区别：raw 由调用方提供（可来自 config 字段或 system_config），
    None 时返回 default；bool 原样返回；其余按真值集合判定。
    """
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in _TRUTHY
