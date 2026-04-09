#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多策略管理 API - 策略启用/禁用、预设切换、信号分组查询、自动交易策略"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...core import get_state_manager
from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse


router = APIRouter(prefix="/api", tags=["多策略管理"])


# ==================== Pydantic Models ====================

class EnableStrategyRequest(BaseModel):
    strategy_id: str = Field(..., min_length=1, description="策略ID")
    preset_name: str = Field(..., min_length=1, description="预设名称")


class DisableStrategyRequest(BaseModel):
    strategy_id: str = Field(..., min_length=1, description="策略ID")


class UpdatePresetRequest(BaseModel):
    preset_name: str = Field(..., min_length=1, description="预设名称")


class SetAutoTradeStrategyRequest(BaseModel):
    strategy_id: str = Field(..., min_length=1, description="策略ID")


# ==================== 多策略管理接口 ====================

@router.get("/strategy/enabled", response_model=APIResponse)
async def get_enabled_strategies(container=Depends(get_container)):
    """获取所有已启用策略列表"""
    svc = container.strategy_monitor_service
    return APIResponse(
        success=True,
        data={
            'enabled_strategies': svc.get_enabled_strategies(),
            'auto_trade_strategy': svc.get_auto_trade_strategy(),
        },
        message="获取已启用策略成功"
    )


@router.post("/strategy/enable", response_model=APIResponse)
async def enable_strategy(
    request: EnableStrategyRequest,
    container=Depends(get_container)
):
    """启用一个策略"""
    result = container.strategy_monitor_service.enable_strategy(
        request.strategy_id, request.preset_name
    )
    if not result.get('success'):
        raise BusinessError(result.get('message', '启用策略失败'))
    return APIResponse(success=True, data=result.get('data'), message=result['message'])


@router.post("/strategy/disable", response_model=APIResponse)
async def disable_strategy(
    request: DisableStrategyRequest,
    container=Depends(get_container)
):
    """禁用一个策略"""
    result = container.strategy_monitor_service.disable_strategy(request.strategy_id)
    if not result.get('success'):
        raise BusinessError(result.get('message', '禁用策略失败'))
    return APIResponse(
        success=True,
        data={'auto_trade_paused': result.get('auto_trade_paused', False)},
        message=result['message']
    )


@router.post("/strategy/{strategy_id}/preset", response_model=APIResponse)
async def update_strategy_preset(
    strategy_id: str,
    request: UpdatePresetRequest,
    container=Depends(get_container)
):
    """修改已启用策略的预设"""
    result = container.strategy_monitor_service.update_strategy_preset(
        strategy_id, request.preset_name
    )
    if not result.get('success'):
        raise BusinessError(result.get('message', '切换预设失败'))
    return APIResponse(success=True, data=result.get('data'), message=result['message'])


@router.get("/signals/by-strategy", response_model=APIResponse)
async def get_signals_by_strategy(container=Depends(get_container)):
    """获取按策略分组的信号数据"""
    state = get_state_manager()
    signals = state.get_signals_by_strategy()
    return APIResponse(success=True, data=signals, message="获取分组信号成功")


# ==================== 自动交易策略接口 ====================

@router.post("/strategy/auto-trade", response_model=APIResponse)
async def set_auto_trade_strategy(
    request: SetAutoTradeStrategyRequest,
    container=Depends(get_container)
):
    """设置自动交易跟随策略"""
    result = container.strategy_monitor_service.set_auto_trade_strategy(
        request.strategy_id
    )
    if not result.get('success'):
        raise BusinessError(result.get('message', '设置自动交易策略失败'))
    return APIResponse(success=True, message=result['message'])


@router.get("/strategy/auto-trade", response_model=APIResponse)
async def get_auto_trade_strategy(container=Depends(get_container)):
    """获取当前自动交易跟随策略"""
    strategy_id = container.strategy_monitor_service.get_auto_trade_strategy()
    return APIResponse(
        success=True,
        data={'auto_trade_strategy': strategy_id},
        message="获取自动交易策略成功"
    )
