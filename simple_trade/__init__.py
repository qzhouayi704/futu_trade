#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版富途量化交易系统 - FastAPI 版本
"""

__version__ = "2.0.0"
__author__ = "Claude"
__description__ = "简化版富途量化交易系统 - FastAPI 重构版"

# 导出 FastAPI 应用
from .app import fastapi_app

__all__ = ['fastapi_app']

