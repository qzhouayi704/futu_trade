#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐笔成交分析路由

提供逐笔成交分析和价位成交分布接口
"""

import asyncio
import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends

from ....core.exceptions import BusinessError
from ....dependencies import get_container
from ....schemas.common import APIResponse
from .helpers import (
    get_ticker_analyzer,
    get_ticker_service,
    get_stock_quote,
    get_avg_daily_turnover,
)

router = APIRouter(prefix="/api/enhanced-heat", tags=["逐笔成交分析"])
logger = logging.getLogger(__name__)


@router.get("/ticker-analysis/{stock_code}", response_model=APIResponse)
async def get_ticker_analysis(
    stock_code: str,
    container=Depends(get_container),
):
    """获取逐笔成交分析结果（支持临时订阅）"""
    try:
        # 临时订阅股票（如果未订阅）
        subscription_helper = container.subscription_helper
        sub_result = subscription_helper.subscribe_for_analysis(stock_code)

        if not sub_result['success']:
            return APIResponse(
                success=False,
                data=None,
                message=f"订阅失败: {sub_result['message']}",
            )

        analyzer = get_ticker_analyzer(container)
        quote, avg_turnover = await asyncio.gather(
            get_stock_quote(container, stock_code),
            get_avg_daily_turnover(container, stock_code),
        )
        current_price = quote.get("last_price", 0.0)
        result = await analyzer.analyze(
            stock_code,
            current_price=current_price,
            quote=quote,
            avg_daily_turnover=avg_turnover,
        )

        if result is None:
            return APIResponse(
                success=True,
                data=None,
                message="成交数据暂不可用",
            )

        # 添加订阅信息到响应
        response_data = asdict(result)
        response_data['subscription_info'] = {
            'replaced': sub_result.get('replaced'),
            'is_temporary': sub_result.get('replaced') is not None
        }

        return APIResponse(
            success=True,
            data=response_data,
            message=f"获取 {stock_code} 成交分析成功",
        )
    except Exception as e:
        logger.error(f"获取成交分析失败 {stock_code}: {e}")
        raise BusinessError(f"获取成交分析失败: {str(e)}")


@router.get("/price-distribution/{stock_code}", response_model=APIResponse)
async def get_price_distribution(
    stock_code: str,
    container=Depends(get_container),
):
    """获取价位成交分布数据"""
    try:
        ticker_service = get_ticker_service(container)
        ticker_data = await ticker_service.get_ticker_data(stock_code)

        if ticker_data is None:
            return APIResponse(
                success=True,
                data=None,
                message="逐笔成交数据不可用",
            )

        from ....services.market_data.ticker_analysis import compute_price_distribution
        result = compute_price_distribution(stock_code, ticker_data.records)

        return APIResponse(
            success=True,
            data=asdict(result),
            message=f"获取 {stock_code} 价位成交分布成功",
        )
    except Exception as e:
        logger.error(f"获取价位成交分布失败 {stock_code}: {e}")
        raise BusinessError(f"获取价位成交分布失败: {str(e)}")


logger.info("逐笔成交分析路由已注册")
