#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成交分析路由模块

拆分自 ticker_analysis_routes.py (417行 → 3个文件)，按功能组织：
- helpers.py (~200行) - 共享辅助函数和服务工厂
- ticker_analysis.py (~120行) - 逐笔成交分析接口
- order_book_analysis.py (~140行) - 盘口分析接口

拆分后每个文件都符合 <400行 的架构规范
"""

from fastapi import APIRouter

from . import ticker_analysis, order_book_analysis


# 创建主路由（不设置prefix，由子路由各自定义）
router = APIRouter()

# 注册子路由（每个子路由已有自己的prefix="/api/enhanced-heat"）
router.include_router(ticker_analysis.router, tags=["逐笔成交分析"])
router.include_router(order_book_analysis.router, tags=["盘口分析"])


__all__ = ['router']
