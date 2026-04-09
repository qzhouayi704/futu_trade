#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用响应模型

定义 API 统一响应格式，与原有 Flask 响应格式保持兼容
"""

from datetime import datetime
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

# 泛型类型变量
T = TypeVar("T")


class ErrorDetail(BaseModel):
    """错误详情"""
    code: str = Field(description="错误代码")
    details: Optional[Any] = Field(default=None, description="错误详情")


class PaginationMeta(BaseModel):
    """分页元数据"""
    page: int = Field(ge=1, description="当前页码")
    page_size: int = Field(ge=1, le=200, description="每页数量")
    total: int = Field(ge=0, description="总记录数")
    total_pages: int = Field(ge=0, description="总页数")


class APIResponse(BaseModel, Generic[T]):
    """
    统一 API 响应格式

    与原有 Flask 响应格式兼容：
    {
        "success": true/false,
        "message": "操作成功/失败原因",
        "data": {...} or [...],
        "timestamp": "2024-01-01T12:00:00",
        "error": null or {"code": "...", "details": ...}
    }
    """
    success: bool = Field(description="操作是否成功")
    message: str = Field(description="操作结果消息")
    data: Optional[T] = Field(default=None, description="响应数据")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="响应时间戳"
    )
    error: Optional[ErrorDetail] = Field(default=None, description="错误信息")

    @classmethod
    def ok(cls, data: T = None, message: str = "操作成功") -> "APIResponse[T]":
        """创建成功响应"""
        return cls(success=True, message=message, data=data)

    @classmethod
    def fail(
        cls,
        message: str = "操作失败",
        error_code: str = "UNKNOWN_ERROR",
        details: Any = None
    ) -> "APIResponse[None]":
        """创建失败响应"""
        return cls(
            success=False,
            message=message,
            error=ErrorDetail(code=error_code, details=details)
        )


class PaginatedResponse(BaseModel, Generic[T]):
    """
    分页响应格式

    {
        "success": true,
        "message": "获取成功",
        "data": [...],
        "meta": {"page": 1, "page_size": 20, "total": 100, "total_pages": 5},
        "extra": {...},  // 可选的额外元数据
        "timestamp": "2024-01-01T12:00:00"
    }
    """
    success: bool = Field(default=True, description="操作是否成功")
    message: str = Field(default="获取成功", description="操作结果消息")
    data: List[T] = Field(default_factory=list, description="分页数据列表")
    meta: PaginationMeta = Field(description="分页元数据")
    extra: Optional[dict] = Field(default=None, description="额外的元数据")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="响应时间戳"
    )

    @classmethod
    def create(
        cls,
        data: List[T],
        page: int = 1,
        page_size: int = 20,
        total: int = 0,
        message: str = "获取成功",
        extra: Optional[dict] = None
    ) -> "PaginatedResponse[T]":
        """创建分页响应"""
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(
            data=data,
            message=message,
            meta=PaginationMeta(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=total_pages
            ),
            extra=extra
        )
