#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票管理路由模块

拆分自 stock.py (481行 → 3个文件)，按功能组织为多个子模块：
- pool.py (~320行) - 股票池查询接口
- init.py (~130行) - 初始化和数据管理接口
- data.py (~20行) - 数据查询接口（预留）

拆分后每个文件都符合 <400行 的架构规范
"""

from fastapi import APIRouter

from . import pool, init, data


# 创建主路由（不设置prefix，由子路由各自定义）
router = APIRouter()

# 注册子路由（每个子路由已有自己的prefix="/api"）
router.include_router(pool.router, tags=["股票池查询"])
router.include_router(init.router, tags=["数据管理"])
router.include_router(data.router, tags=["股票数据"])


__all__ = ['router']
