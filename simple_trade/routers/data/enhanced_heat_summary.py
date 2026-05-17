#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强热度分析 - 首页数据复用接口

供首页调用的热门板块摘要和热门股票摘要接口，
复用增强热度系统的计算结果，确保首页与增强热度分析页面数据一致。
"""

import logging

from fastapi import APIRouter, Depends, Query

from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse
from .helpers.enhanced_heat_helpers import (
    get_realtime_data as _get_realtime_data,
)


router = APIRouter(prefix="/api/enhanced-heat", tags=["增强热度分析"])


@router.get("/hot-plates-summary", response_model=APIResponse)
async def get_hot_plates_summary(container=Depends(get_container)):
    """供首页复用的热门板块摘要

    直接返回增强热度系统计算的实时热门板块排序结果，
    确保与增强热度分析页面展示的热门板块数据一致。
    """
    try:
        monitor = container.market_heat_monitor
        _, quotes_map, plates_monitor, _, _ = _get_realtime_data(
            container=container,
            heat_quote_svc=container.heat_quote_service
        )

        hot_plates = monitor.get_hot_plates(plates_monitor, quotes_map, top_n=10)

        return APIResponse(
            success=True,
            data={
                'hot_plates': hot_plates,
                'total': len(hot_plates),
            },
            message=f"获取热门板块摘要成功，共{len(hot_plates)}个板块"
        )
    except Exception as e:
        logging.error(f"获取热门板块摘要失败: {e}")
        raise BusinessError(f"获取热门板块摘要失败: {str(e)}")


@router.get("/hot-stocks-summary", response_model=APIResponse)
async def get_hot_stocks_summary(
    limit: int = Query(20, ge=1, le=100, description="返回数量限制"),
    container=Depends(get_container),
):
    """供首页复用的热门股票摘要

    直接返回增强热度系统筛选的热门股票结果，
    确保与增强热度分析页面展示的热门股票数据一致。
    """
    try:
        from ...services.analysis.heat.heat_score_engine import HeatScoreEngine
        from ...services.market_data.hot_stock.hot_stock_filter import HotStockFilter

        _, quotes_map, _, plates_filter, _ = _get_realtime_data(
            container=container,
            heat_quote_svc=container.heat_quote_service
        )

        score_engine = HeatScoreEngine()
        hot_filter = HotStockFilter(score_engine=score_engine)
        hot_stocks_by_plate = hot_filter.get_all_hot_stocks(plates_filter, quotes_map)

        # 合并所有板块的热门股票，按 heat_score 降序排序
        all_hot_stocks = [
            stock
            for stocks in hot_stocks_by_plate.values()
            for stock in stocks
        ]
        all_hot_stocks.sort(key=lambda x: x.heat_score, reverse=True)
        top_stocks = all_hot_stocks[:limit]

        return APIResponse(
            success=True,
            data={
                'hot_stocks': [s.to_dict() for s in top_stocks],
                'total': len(top_stocks),
            },
            message=f"获取热门股票摘要成功，共{len(top_stocks)}只"
        )
    except Exception as e:
        logging.error(f"获取热门股票摘要失败: {e}")
        raise BusinessError(f"获取热门股票摘要失败: {str(e)}")
