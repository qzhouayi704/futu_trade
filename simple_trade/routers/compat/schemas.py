#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
兼容路由的Pydantic模型定义
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class AddPlateRequest(BaseModel):
    """添加板块请求"""
    plate_code: str = Field(..., min_length=1, description="板块代码")


class BatchAddPlatesRequest(BaseModel):
    """批量添加板块请求"""
    plate_codes: List[str] = Field(..., min_items=1, description="板块代码列表")


class AddStocksRequest(BaseModel):
    """添加股票请求"""
    stock_codes: List[str] = Field(..., min_items=1, description="股票代码列表")
    plate_id: Optional[int] = Field(None, description="板块ID")
    is_manual: bool = Field(True, description="是否为手动添加")


class InitDataRequest(BaseModel):
    """数据初始化请求"""
    force_refresh: bool = Field(False, description="是否强制刷新")
