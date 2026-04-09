#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pydantic 数据模型包

用于替代原有的自建验证框架，提供：
- 请求参数验证
- 响应数据序列化
- OpenAPI 文档自动生成
"""

from .common import (
    APIResponse,
    PaginatedResponse,
    ErrorDetail,
    PaginationMeta,
)
from .take_profit import CreateLotTakeProfitRequest

__all__ = [
    "APIResponse",
    "PaginatedResponse",
    "ErrorDetail",
    "PaginationMeta",
    "CreateLotTakeProfitRequest",
]
