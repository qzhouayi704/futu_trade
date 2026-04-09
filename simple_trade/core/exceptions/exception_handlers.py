#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局异常处理器

注册到 FastAPI 应用，统一处理所有异常
"""

import logging
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from .exceptions import APIException


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器"""

    @app.exception_handler(APIException)
    async def api_exception_handler(request: Request, exc: APIException):
        """处理自定义 API 异常"""
        logging.warning(f"API异常 [{exc.error_code}]: {exc.message}")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "message": exc.message,
                "data": None,
                "timestamp": datetime.now().isoformat(),
                "error": {
                    "code": exc.error_code,
                    "details": exc.details
                }
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """处理请求参数验证错误"""
        errors = exc.errors()
        details = [
            {
                "field": ".".join(str(loc) for loc in err["loc"]),
                "message": err["msg"],
                "type": err["type"]
            }
            for err in errors
        ]
        logging.warning(f"参数验证失败: {details}")
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "message": "参数验证失败",
                "data": None,
                "timestamp": datetime.now().isoformat(),
                "error": {
                    "code": "VALIDATION_ERROR",
                    "details": details
                }
            }
        )

    @app.exception_handler(PydanticValidationError)
    async def pydantic_validation_handler(request: Request, exc: PydanticValidationError):
        """处理 Pydantic 验证错误"""
        errors = exc.errors()
        details = [
            {
                "field": ".".join(str(loc) for loc in err["loc"]),
                "message": err["msg"],
                "type": err["type"]
            }
            for err in errors
        ]
        logging.warning(f"Pydantic验证失败: {details}")
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "message": "数据验证失败",
                "data": None,
                "timestamp": datetime.now().isoformat(),
                "error": {
                    "code": "VALIDATION_ERROR",
                    "details": details
                }
            }
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """处理值错误"""
        logging.warning(f"值错误: {str(exc)}")
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": str(exc),
                "data": None,
                "timestamp": datetime.now().isoformat(),
                "error": {
                    "code": "VALUE_ERROR",
                    "details": None
                }
            }
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """处理未捕获的异常"""
        logging.error(f"未处理异常: {type(exc).__name__}: {str(exc)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "服务器内部错误",
                "data": None,
                "timestamp": datetime.now().isoformat(),
                "error": {
                    "code": "INTERNAL_ERROR",
                    "details": str(exc) if logging.getLogger().level <= logging.DEBUG else None
                }
            }
        )
