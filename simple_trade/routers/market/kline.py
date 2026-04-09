#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线数据路由 - FastAPI Router

迁移自 routes/kline_routes.py
包含K线数据查询接口
"""

import logging

from fastapi import APIRouter, Depends, Query, Path

from ...dependencies import get_container
from ...schemas.common import APIResponse
from .kline_helpers import get_stock_info, get_kline_from_db, fetch_kline_from_api, get_trade_points


router = APIRouter(prefix="/api/kline", tags=["K线数据"])


@router.get("/{stock_code}", response_model=APIResponse)
async def get_kline_data(
    stock_code: str = Path(..., description="股票代码(如 HK.03690)"),
    days: int = Query(60, ge=10, le=365, description="获取天数(10-365)"),
    container=Depends(get_container)
):
    """获取股票K线数据"""
    # 1. 获取股票基本信息
    stock_info = get_stock_info(stock_code, container)

    # 2. 从数据库获取K线数据
    kline_data = get_kline_from_db(stock_code, days, container.db_manager)

    # 3. 只有当数据库完全没有数据时，才尝试从API获取
    if not kline_data:
        logging.info(f"数据库无K线数据，尝试从API获取: {stock_code}")
        kline_data = fetch_kline_from_api(stock_code, days, container)
    elif len(kline_data) < days:
        logging.info(f"K线数据量: {len(kline_data)}条，少于请求的{days}天，使用现有数据: {stock_code}")

    # 4. 获取交易记录（买卖点）
    trade_points = get_trade_points(stock_code, days, container.db_manager)

    # 5. 格式化K线数据为前端格式
    formatted_kline = []
    for row in kline_data:
        formatted_kline.append([
            row['date'],
            row['open'],
            row['close'],
            row['low'],
            row['high'],
            row['volume']
        ])

    return APIResponse(
        success=True,
        data={
            'stock_info': stock_info,
            'kline_data': formatted_kline,
            'trade_points': trade_points
        },
        message=f"获取K线数据成功，共{len(formatted_kline)}条"
    )


logging.info("K线数据路由已注册")
