#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异常模块
包含自定义异常类和异常处理器
"""

from .exceptions import (
    APIException,
    ValidationError,
    NotFoundError,
    UnauthorizedError,
    ForbiddenError,
    ConflictError,
    BusinessError,
    DatabaseError,
    ExternalAPIError,
)
from .exception_handlers import (
    register_exception_handlers,
)

__all__ = [
    # 异常类
    'APIException',
    'ValidationError',
    'NotFoundError',
    'UnauthorizedError',
    'ForbiddenError',
    'ConflictError',
    'BusinessError',
    'DatabaseError',
    'ExternalAPIError',
    # 异常处理器
    'register_exception_handlers',
]
