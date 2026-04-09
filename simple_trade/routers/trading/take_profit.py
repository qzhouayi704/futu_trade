#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分仓止盈路由

提供仓位查询、止盈任务管理的API接口。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...dependencies import get_container
from ...schemas.common import APIResponse


router = APIRouter(prefix="/api/trading/take-profit", tags=["分仓止盈"])


# ==================== Pydantic Models ====================

class CreateTakeProfitRequest(BaseModel):
    """创建止盈任务请求"""
    stock_code: str = Field(..., min_length=1, description="股票代码")
    take_profit_pct: float = Field(..., gt=0, le=100, description="止盈百分比")


# ==================== Helper ====================

def _get_service(container):
    """获取分仓止盈服务"""
    if not hasattr(container, 'lot_take_profit_service') or not container.lot_take_profit_service:
        raise Exception("分仓止盈服务未初始化")
    return container.lot_take_profit_service


# ==================== API Endpoints ====================

@router.get("/lots/{stock_code}")
async def get_position_lots(stock_code: str, container=Depends(get_container)):
    """获取某只股票的分仓信息"""
    try:
        service = _get_service(container)
        lots = service.get_position_lots(stock_code)
        lots_data = [lot.to_dict() for lot in lots]
        return APIResponse.ok(data=lots_data, message=f"获取到 {len(lots)} 个仓位")
    except Exception as e:
        logging.error(f"获取分仓信息失败: {e}")
        return APIResponse.fail(message=str(e))


@router.post("/tasks")
async def create_take_profit_task(
    request: CreateTakeProfitRequest,
    container=Depends(get_container),
):
    """创建分仓止盈任务"""
    try:
        service = _get_service(container)
        result = service.create_task(
            stock_code=request.stock_code,
            take_profit_pct=request.take_profit_pct,
        )
        if result['success']:
            return APIResponse.ok(data=result.get('task'), message="止盈任务创建成功")
        return APIResponse.fail(message=result['message'])
    except Exception as e:
        logging.error(f"创建止盈任务失败: {e}")
        return APIResponse.fail(message=str(e))


@router.get("/tasks")
async def get_take_profit_tasks(container=Depends(get_container)):
    """获取所有止盈任务"""
    try:
        service = _get_service(container)
        tasks = service.get_all_tasks()
        return APIResponse.ok(data=tasks, message=f"获取到 {len(tasks)} 个任务")
    except Exception as e:
        logging.error(f"获取止盈任务列表失败: {e}")
        return APIResponse.fail(message=str(e))


@router.get("/tasks/{stock_code}")
async def get_take_profit_detail(stock_code: str, container=Depends(get_container)):
    """获取某只股票的止盈任务详情"""
    try:
        service = _get_service(container)
        detail = service.get_task_detail(stock_code)
        if detail:
            return APIResponse.ok(data=detail)
        return APIResponse.fail(message=f"{stock_code} 没有止盈任务")
    except Exception as e:
        logging.error(f"获取止盈任务详情失败: {e}")
        return APIResponse.fail(message=str(e))


@router.post("/tasks/{stock_code}/cancel")
async def cancel_take_profit_task(stock_code: str, container=Depends(get_container)):
    """取消止盈任务"""
    try:
        service = _get_service(container)
        result = service.cancel_task(stock_code)
        if result['success']:
            return APIResponse.ok(message=result['message'])
        return APIResponse.fail(message=result['message'])
    except Exception as e:
        logging.error(f"取消止盈任务失败: {e}")
        return APIResponse.fail(message=str(e))
