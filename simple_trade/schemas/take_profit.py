#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
止盈配置相关的 Pydantic 数据模型
"""

from pydantic import BaseModel, Field


class CreateLotTakeProfitRequest(BaseModel):
    """单笔订单止盈配置请求"""
    stock_code: str = Field(..., min_length=1, description="股票代码")
    deal_id: str = Field(..., min_length=1, description="成交ID")
    buy_price: float = Field(..., gt=0, description="买入价格")
    quantity: int = Field(..., gt=0, description="买入数量")
    take_profit_pct: float = Field(..., gt=0, le=100, description="止盈百分比")
    take_profit_price: float = Field(..., gt=0, description="止盈目标价格")
