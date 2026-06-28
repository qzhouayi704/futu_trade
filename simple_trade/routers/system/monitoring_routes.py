#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
监控统计路由 - FastAPI Router

包含股票池监控统计信息接口
"""

import logging
from fastapi import APIRouter, Depends

from ...dependencies import get_container
from ...schemas.common import APIResponse


router = APIRouter(tags=["监控统计"])


@router.get("/stocks/monitor-stats", response_model=APIResponse)
async def get_monitor_stats(container=Depends(get_container)):
    """获取股票池监控统计信息"""
    hot_service = container.hot_stock_service

    heat_status = hot_service.get_heat_status()
    plate_overview = hot_service.get_plate_overview()

    total_stocks = heat_status.get('total_stock_count', 0)
    hot_stocks = heat_status.get('hot_stock_count', 0)
    non_hot_stocks = max(0, total_stocks - hot_stocks)

    return APIResponse(
        success=True,
        data={
            'hot_count': hot_stocks,
            'non_hot_count': non_hot_stocks,
            'total_count': total_stocks,
            'last_update': heat_status.get('last_update'),
            'is_analyzing': heat_status.get('is_analyzing', False),
            'plates': plate_overview
        },
        message="获取监控统计成功"
    )


# 注：本函数不再在此处注册（路径 /api/monitoring/link-health 已由统一路由 system/monitoring.py 注册），
# 仅保留定义供统一路由导入，避免同路径双重注册。
async def get_link_health(container=Depends(get_container)):
    """P1-2: 链路健康指标（P50/P95/P99延迟、成功率、重连频率）"""
    link_monitor = getattr(container, 'link_health_monitor', None)
    if link_monitor is None:
        return APIResponse(
            success=False,
            data={},
            message="链路健康监控未启用"
        )
    return APIResponse(
        success=True,
        data=link_monitor.get_health(),
        message="获取链路健康指标成功"
    )


logging.info("监控统计路由已注册")