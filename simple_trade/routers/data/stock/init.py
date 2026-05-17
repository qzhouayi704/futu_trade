#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据初始化和管理路由

包含数据初始化和管理相关接口：
- 数据初始化
- 数据刷新
- 初始化状态查询
- 活跃度记录重置
"""

import logging
import threading
from datetime import date

from fastapi import APIRouter, Depends, Query

from ....core import get_state_manager
from ....core.exceptions import BusinessError
from ....dependencies import get_container
from ....schemas.common import APIResponse


router = APIRouter(prefix="/api", tags=["数据管理"])


@router.post("/init")
async def init_data(
    force_refresh: bool = Query(default=False, description="是否强制刷新"),
    container=Depends(get_container)
):
    """数据初始化接口"""
    result = container.stock_pool_service.init_stock_pool(force_refresh=force_refresh)

    if result.get('success', False):
        return APIResponse.ok(
            data={
                'plates_count': result.get('plates_count', 0),
                'stocks_count': result.get('stocks_count', 0)
            },
            message=result.get('message', '数据初始化成功')
        )
    else:
        raise BusinessError(message=result.get('message', '数据初始化失败'))


@router.post("/refresh")
async def refresh_data(
    container=Depends(get_container)
):
    """增量更新板块和股票数据（不删除现有数据）"""
    result = container.stock_pool_service.refresh_stock_pool()

    if result.get('success', False):
        return APIResponse.ok(
            data={
                'plates_added': result.get('plates_added', 0),
                'plates_updated': result.get('plates_updated', 0),
                'stocks_added': result.get('stocks_added', 0),
                'stocks_updated': result.get('stocks_updated', 0),
                'plates_count': result.get('plates_count', 0),
                'stocks_count': result.get('stocks_count', 0)
            },
            message=result.get('message', '数据更新成功')
        )
    else:
        raise BusinessError(message=result.get('message', '数据更新失败'))


@router.get("/init/status")
async def get_init_status():
    """获取初始化状态"""
    state = get_state_manager()
    progress = state.get_init_progress()
    pool_data = state.get_stock_pool()

    return APIResponse.ok(
        data={
            'initialized': pool_data['initialized'],
            'plates_count': len(pool_data['plates']),
            'stocks_count': len(pool_data['stocks']),
            'last_update': pool_data['last_update'],
            'progress': progress
        },
        message="获取初始化状态成功"
    )


@router.post("/stocks/activity/reset")
async def reset_activity_records(
    container=Depends(get_container)
):
    """清空今日活跃度筛选记录并立即触发重新筛选"""
    try:
        today = date.today().strftime('%Y-%m-%d')

        # 先获取统计信息
        stats = container.db_manager.stock_activity_queries.get_daily_activity_stats(today)

        # 清空今日记录
        deleted = container.db_manager.stock_activity_queries.clear_daily_activity_records(today)

        logging.info(f"已清空今日活跃度记录: {deleted} 条")

        # 触发重新筛选（异步执行）
        from ...data.activity_refilter import trigger_refilter_async
        threading.Thread(
            target=trigger_refilter_async,
            args=(container,),
            daemon=True,
            name="reset-and-refilter"
        ).start()

        return APIResponse.ok(
            data={
                'deleted_count': deleted,
                'check_date': today,
                'previous_stats': stats
            },
            message=f"已清空 {deleted} 条记录，正在后台重新筛选活跃度"
        )
    except Exception as e:
        logging.error(f"清空活跃度记录失败: {e}", exc_info=True)
        raise BusinessError(message=f"清空活跃度记录失败: {str(e)}")
