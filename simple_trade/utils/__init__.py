#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具模块
提供系统中所有公用工具类和函数

模块结构:
- field_mapper: 字段映射器
- plate_matcher: 板块匹配器
- rate_limiter: 频率限制器
- market_helper: 市场工具
- logger: 日志配置

注意：以下模块已废弃（Flask 相关）：
- api_response: API响应格式（已迁移到 FastAPI）
- error_handler: 全局错误处理器（已迁移到 FastAPI）
- validators: 参数验证器（已迁移到 Pydantic）
- response_helper: 响应帮助类（已迁移到 FastAPI）
"""

# 日志配置
from .logger import setup_logging, get_logger, set_log_level

# 字段映射器
from .field_mapper import FieldMapper

# 板块匹配器
from .plate_matcher import PlateMatcher, MatchResult, get_plate_matcher

# 频率限制器
from .rate_limiter import (
    RateLimiter,
    get_rate_limiter,
    wait_for_api,
    can_call_api,
    get_api_status
)


# 市场工具
from .market_helper import (
    MarketTimeHelper,
    get_current_primary_market,
    get_current_active_markets,
    should_subscribe_hk,
    should_subscribe_us
)

__all__ = [
    # 日志
    'setup_logging', 'get_logger', 'set_log_level',

    # 字段映射器
    'FieldMapper',

    # 板块匹配器
    'PlateMatcher', 'MatchResult', 'get_plate_matcher',

    # 频率限制器
    'RateLimiter', 'get_rate_limiter', 'wait_for_api',
    'can_call_api', 'get_api_status',

    # 市场工具
    'MarketTimeHelper', 'get_current_primary_market', 'get_current_active_markets',
    'should_subscribe_hk', 'should_subscribe_us'
]
