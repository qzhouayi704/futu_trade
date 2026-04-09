#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scalping 路由 - 日内超短线引擎 API

提供 Scalping 数据流的启动、停止、批量管理和状态查询接口。
"""

import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...dependencies import get_container
from ...schemas.common import APIResponse

logger = logging.getLogger("scalping")

router = APIRouter(prefix="/api/scalping", tags=["日内超短线"])


# ==================== 请求模型 ====================


class ScalpingStartRequest(BaseModel):
    """启动 Scalping 数据流请求"""

    stock_codes: list[str] = Field(
        ..., min_length=1, description="股票代码列表，至少一只"
    )
    turnover_rates: Optional[dict[str, float]] = Field(
        default=None,
        description="股票代码 → 换手率（%）映射，用于筛选低换手率股票",
    )


class ScalpingStopRequest(BaseModel):
    """停止 Scalping 数据流请求"""

    stock_codes: Optional[list[str]] = Field(
        default=None, description="股票代码列表，为空时停止全部"
    )


class ScalpingBatchRequest(BaseModel):
    """批量增减股票请求"""

    stock_codes: list[str] = Field(
        ..., min_length=1, description="股票代码列表"
    )
    turnover_rates: Optional[dict[str, float]] = Field(
        default=None, description="换手率映射（仅 batch-add 使用）"
    )


# ==================== 路由 ====================


@router.post("/start", response_model=APIResponse)
async def start_scalping(
    request: ScalpingStartRequest,
    container=Depends(get_container),
):
    """启动指定股票的 Scalping 数据流"""
    engine = container.scalping_engine
    if engine is None:
        return APIResponse(
            success=False,
            message="ScalpingEngine 未初始化",
        )

    try:
        result = await engine.start(
            request.stock_codes,
            turnover_rates=request.turnover_rates,
        )
        if result.rejected_reason:
            return APIResponse(
                success=False,
                message=result.rejected_reason,
                data=asdict(result),
            )
        return APIResponse(
            success=True,
            data=asdict(result),
            message=(
                f"已启动 {len(result.added)} 只股票，"
                f"{len(result.existing)} 只已在监控中，"
                f"{len(result.filtered)} 只因换手率不足被过滤"
            ),
        )
    except Exception as e:
        logger.error(f"启动 Scalping 失败: {e}", exc_info=True)
        return APIResponse(
            success=False, message=f"启动 Scalping 失败: {e}"
        )


@router.post("/stop", response_model=APIResponse)
async def stop_scalping(
    request: ScalpingStopRequest,
    container=Depends(get_container),
):
    """停止 Scalping 数据流"""
    engine = container.scalping_engine
    if engine is None:
        return APIResponse(
            success=False,
            message="ScalpingEngine 未初始化",
        )

    try:
        await engine.stop(request.stock_codes)
        if request.stock_codes:
            msg = f"已停止 {len(request.stock_codes)} 只股票的 Scalping 数据流"
        else:
            msg = "已停止全部 Scalping 数据流"
        return APIResponse(success=True, message=msg)
    except Exception as e:
        logger.error(f"停止 Scalping 失败: {e}", exc_info=True)
        return APIResponse(
            success=False, message=f"停止 Scalping 失败: {e}"
        )


@router.post("/batch-add", response_model=APIResponse)
async def batch_add_stocks(
    request: ScalpingBatchRequest,
    container=Depends(get_container),
):
    """追加股票到已运行的 Scalping 引擎"""
    engine = container.scalping_engine
    if engine is None:
        return APIResponse(
            success=False, message="ScalpingEngine 未初始化"
        )

    try:
        result = await engine.start(
            request.stock_codes,
            turnover_rates=request.turnover_rates,
        )
        if result.rejected_reason:
            return APIResponse(
                success=False,
                message=result.rejected_reason,
                data=asdict(result),
            )
        return APIResponse(
            success=True,
            data=asdict(result),
            message=f"已追加 {len(result.added)} 只股票",
        )
    except Exception as e:
        logger.error(f"批量追加失败: {e}", exc_info=True)
        return APIResponse(
            success=False, message=f"批量追加失败: {e}"
        )


@router.post("/batch-remove", response_model=APIResponse)
async def batch_remove_stocks(
    request: ScalpingBatchRequest,
    container=Depends(get_container),
):
    """从 Scalping 引擎中移除指定股票"""
    engine = container.scalping_engine
    if engine is None:
        return APIResponse(
            success=False, message="ScalpingEngine 未初始化"
        )

    try:
        await engine.stop(request.stock_codes)
        return APIResponse(
            success=True,
            data={"removed": request.stock_codes},
            message=f"已移除 {len(request.stock_codes)} 只股票",
        )
    except Exception as e:
        logger.error(f"批量移除失败: {e}", exc_info=True)
        return APIResponse(
            success=False, message=f"批量移除失败: {e}"
        )


@router.get("/status", response_model=APIResponse)
async def get_scalping_status(container=Depends(get_container)):
    """查询当前 Scalping 引擎状态"""
    engine = container.scalping_engine
    if engine is None:
        return APIResponse(
            success=False, message="ScalpingEngine 未初始化"
        )

    status = engine.get_status()
    return APIResponse(
        success=True,
        data=status,
        message=f"当前监控 {status['active_count']} 只股票",
    )
@router.get("/snapshot/{stock_code}", response_model=APIResponse)
async def get_scalping_snapshot(
    stock_code: str,
    container=Depends(get_container),
):
    """获取指定股票的 Scalping 数据快照（供前端初始加载）"""
    engine = container.scalping_engine
    if engine is None:
        return APIResponse(
            success=False, message="ScalpingEngine 未初始化"
        )

    try:
        snapshot = await engine.get_snapshot(stock_code)
        if snapshot is None:
            return APIResponse(
                success=False,
                message=f"{stock_code} 不在 Scalping 监控中",
            )

        return APIResponse(
            success=True,
            data=snapshot,
            message="快照获取成功",
        )
    except Exception as e:
        logger.error(f"获取 {stock_code} 快照失败: {e}", exc_info=True)
        return APIResponse(
            success=False, message=f"获取快照失败: {e}"
        )



