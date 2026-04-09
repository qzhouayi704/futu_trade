#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义异常类

用于 FastAPI 全局异常处理
"""

from typing import Any, Optional


class APIException(Exception):
    """API 异常基类"""

    def __init__(
        self,
        message: str = "服务器内部错误",
        error_code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Any] = None
    ):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class ValidationError(APIException):
    """参数验证错误"""

    def __init__(self, message: str = "参数验证失败", details: Optional[Any] = None):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            status_code=422,
            details=details
        )


class NotFoundError(APIException):
    """资源不存在"""

    def __init__(self, message: str = "资源不存在", details: Optional[Any] = None):
        super().__init__(
            message=message,
            error_code="NOT_FOUND",
            status_code=404,
            details=details
        )


class ConflictError(APIException):
    """资源冲突"""

    def __init__(self, message: str = "资源冲突", details: Optional[Any] = None):
        super().__init__(
            message=message,
            error_code="CONFLICT",
            status_code=409,
            details=details
        )


class BusinessError(APIException):
    """业务逻辑错误"""

    def __init__(self, message: str = "业务处理失败", details: Optional[Any] = None):
        super().__init__(
            message=message,
            error_code="BUSINESS_ERROR",
            status_code=400,
            details=details
        )


class DatabaseError(APIException):
    """数据库操作错误"""

    def __init__(self, message: str = "数据库操作失败", details: Optional[Any] = None):
        super().__init__(
            message=message,
            error_code="DATABASE_ERROR",
            status_code=500,
            details=details
        )


class ExternalAPIError(APIException):
    """外部 API 调用错误"""

    def __init__(self, message: str = "外部服务调用失败", details: Optional[Any] = None):
        super().__init__(
            message=message,
            error_code="EXTERNAL_API_ERROR",
            status_code=502,
            details=details
        )


class UnauthorizedError(APIException):
    """未授权"""

    def __init__(self, message: str = "未授权访问", details: Optional[Any] = None):
        super().__init__(
            message=message,
            error_code="UNAUTHORIZED",
            status_code=401,
            details=details
        )


class ForbiddenError(APIException):
    """禁止访问"""

    def __init__(self, message: str = "禁止访问", details: Optional[Any] = None):
        super().__init__(
            message=message,
            error_code="FORBIDDEN",
            status_code=403,
            details=details
        )
