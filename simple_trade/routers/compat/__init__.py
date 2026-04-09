#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
兼容路由模块 - FastAPI Router

迁移自 routes/compat_routes.py
提供前端期望的 RESTful 风格 API 端点，转发到现有实现
解决前后端 API 路径不匹配的问题
"""

from fastapi import APIRouter

from .plate_routes import router as plate_router
from .stock_routes import router as stock_router


# 创建主路由器
router = APIRouter(prefix="/api", tags=["兼容接口"])

# 包含所有子路由
router.include_router(plate_router)
router.include_router(stock_router)
