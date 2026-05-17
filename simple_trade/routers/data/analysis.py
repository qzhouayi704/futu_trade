#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置分析 + 自动交易 API 路由
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Path
from pydantic import BaseModel, Field

from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse


router = APIRouter(prefix="/api/analysis", tags=["价格位置分析"])


# ==================== Pydantic Models ====================

class AnalyzeRequest(BaseModel):
    """分析请求"""
    stock_code: str = Field(..., min_length=1, description="股票代码，如 HK.00700")


class AutoTradeStartRequest(BaseModel):
    """启动自动交易请求"""
    stock_code: str = Field(..., min_length=1, description="股票代码")
    quantity: int = Field(..., gt=0, description="交易数量（100的倍数）")
    zone: str = Field(..., description="价格位置区间")
    buy_dip_pct: float = Field(..., gt=0, description="买入跌幅百分比")
    sell_rise_pct: float = Field(..., gt=0, description="卖出涨幅百分比")
    stop_loss_pct: float = Field(..., gt=0, description="止损百分比")
    prev_close: float = Field(..., gt=0, description="前收盘价")


class AutoTradeStopRequest(BaseModel):
    """停止自动交易请求"""
    stock_code: str = Field(..., min_length=1, description="股票代码")


# ==================== Helper ====================

_analysis_service = None
_auto_trade_service = None


def _get_analysis_service(container):
    """获取或创建分析服务"""
    global _analysis_service
    if _analysis_service is None:
        from ...services.analysis.analysis_service import AnalysisService
        _analysis_service = AnalysisService(
            db_manager=container.db_manager,
            kline_service=container.kline_service,
            futu_client=container.futu_client,
        )
    return _analysis_service


def _get_auto_trade_service(container):
    """获取或创建自动交易服务"""
    global _auto_trade_service
    if _auto_trade_service is None:
        from ...services.trading.aggressive import AutoTradeService
        _auto_trade_service = AutoTradeService(container)
    return _auto_trade_service


def _sync_to_params_cache(container, stock_code: str, result: dict):
    """将分析结果同步到价格位置参数缓存（供实时策略使用）"""
    try:
        strategy_monitor = getattr(container, 'strategy_monitor', None)
        if not strategy_monitor:
            return
        cache = getattr(strategy_monitor, 'params_cache_manager', None)
        if not cache:
            return
        if not cache.get_params(stock_code):
            cache.put_params(stock_code, result)
    except Exception as e:
        logging.debug(f"同步分析结果到参数缓存失败: {e}")


# ==================== 分析接口 ====================

@router.post("/analyze", response_model=APIResponse)
async def start_analysis(
    request: AnalyzeRequest,
    container=Depends(get_container),
):
    """启动价格位置分析"""
    service = _get_analysis_service(container)
    task_id = service.start_analysis(request.stock_code)

    return APIResponse(
        success=True,
        data={'task_id': task_id, 'stock_code': request.stock_code},
        message=f'分析任务已启动: {request.stock_code}',
    )


@router.get("/analyze/status/{task_id}", response_model=APIResponse)
async def get_analysis_status(
    task_id: str = Path(..., description="任务ID"),
    container=Depends(get_container),
):
    """查询分析进度和结果"""
    service = _get_analysis_service(container)
    task = service.get_task_status(task_id)

    if not task:
        raise BusinessError(f'任务 {task_id} 不存在')

    # 分析完成时，将结果写入价格位置参数缓存（供实时策略使用）
    if task.get('status') == 'completed' and task.get('result'):
        _sync_to_params_cache(container, task['stock_code'], task['result'])

    return APIResponse(
        success=True,
        data=task,
        message=task.get('progress', ''),
    )


# ==================== 自动交易接口 ====================

@router.post("/auto-trade/start", response_model=APIResponse)
async def start_auto_trade(
    request: AutoTradeStartRequest,
    container=Depends(get_container),
):
    """启动自动交易"""
    service = _get_auto_trade_service(container)

    result = service.start_auto_trade(
        stock_code=request.stock_code,
        quantity=request.quantity,
        zone=request.zone,
        buy_dip_pct=request.buy_dip_pct,
        sell_rise_pct=request.sell_rise_pct,
        stop_loss_pct=request.stop_loss_pct,
        prev_close=request.prev_close,
    )

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        data=result.get('task'),
        message=f'{request.stock_code} 自动交易已启动',
    )


@router.post("/auto-trade/stop", response_model=APIResponse)
async def stop_auto_trade(
    request: AutoTradeStopRequest,
    container=Depends(get_container),
):
    """停止自动交易"""
    service = _get_auto_trade_service(container)
    result = service.stop_auto_trade(request.stock_code)

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        message=result['message'],
    )


@router.get("/auto-trade/status", response_model=APIResponse)
async def get_auto_trade_status(
    container=Depends(get_container),
):
    """查询所有自动交易状态"""
    service = _get_auto_trade_service(container)
    tasks = service.get_all_status()

    return APIResponse(
        success=True,
        data=tasks,
        message=f'{len(tasks)} 个自动交易任务',
    )


logging.info("价格位置分析路由已注册")
