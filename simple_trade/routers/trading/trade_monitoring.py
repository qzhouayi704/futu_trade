#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格监控任务路由

包含监控任务的创建、查询、取消等接口
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Query, Path

from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse
from .trade_helpers import AddMonitorTaskRequest, ensure_monitor_service


router = APIRouter(prefix="/api/trading/monitor", tags=["价格监控"])


@router.get("/tasks", response_model=APIResponse)
async def get_monitor_tasks(
    status: Optional[str] = Query(None, description="状态过滤"),
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    container=Depends(get_container)
):
    """获取监控任务列表"""
    monitor_service = ensure_monitor_service(container)

    tasks = await asyncio.to_thread(monitor_service.get_all_tasks, status=status, limit=limit)

    return APIResponse(
        success=True,
        data=tasks,
        message=f"获取到 {len(tasks)} 个监控任务",
        meta={'count': len(tasks)}
    )


@router.get("/tasks/active", response_model=APIResponse)
async def get_active_monitor_tasks(container=Depends(get_container)):
    """获取活跃的监控任务"""
    monitor_service = ensure_monitor_service(container)

    tasks = await asyncio.to_thread(monitor_service.get_active_tasks)

    return APIResponse(
        success=True,
        data=tasks,
        message=f"获取到 {len(tasks)} 个活跃监控任务",
        meta={'count': len(tasks)}
    )


@router.get("/tasks/{task_id}", response_model=APIResponse)
async def get_monitor_task(
    task_id: int = Path(..., description="任务ID"),
    container=Depends(get_container)
):
    """获取单个监控任务详情"""
    monitor_service = ensure_monitor_service(container)

    task = await asyncio.to_thread(monitor_service.get_task, task_id)

    if not task:
        raise BusinessError("任务不存在")

    return APIResponse(
        success=True,
        data=task,
        message="获取任务详情成功"
    )


@router.post("/tasks", response_model=APIResponse)
async def add_monitor_task(
    request: AddMonitorTaskRequest,
    container=Depends(get_container)
):
    """添加监控任务"""
    # 验证数量
    request.validate_quantity()

    monitor_service = ensure_monitor_service(container)

    result = await asyncio.to_thread(
        monitor_service.add_task,
        stock=request.to_stock_info(),
        direction=request.direction,
        target_price=request.target_price,
        quantity=request.quantity,
        stop_loss_price=request.stop_loss_price
    )

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        data=result.get('task'),
        message=result['message']
    )


@router.post("/tasks/{task_id}/cancel", response_model=APIResponse)
async def cancel_monitor_task(
    task_id: int = Path(..., description="任务ID"),
    container=Depends(get_container)
):
    """取消监控任务"""
    monitor_service = ensure_monitor_service(container)

    result = await asyncio.to_thread(monitor_service.cancel_task, task_id)

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        message=result['message']
    )


@router.get("/summary", response_model=APIResponse)
async def get_monitor_summary(container=Depends(get_container)):
    """获取监控摘要"""
    monitor_service = ensure_monitor_service(container)

    summary = await asyncio.to_thread(monitor_service.get_monitor_summary)

    return APIResponse(
        success=True,
        data=summary,
        message="获取监控摘要成功"
    )
