#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略管理路由 - 策略和预设管理、监控控制

包含策略切换、预设管理、监控启停等接口
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...core import get_state_manager
from ...core.exceptions import BusinessError
from ...dependencies import get_container, get_system_coordinator
from ...schemas.common import APIResponse


router = APIRouter(prefix="/api", tags=["策略管理"])


# ==================== Pydantic Models ====================

class SetActiveStrategyRequest(BaseModel):
    """设置激活策略请求"""
    strategy_id: str = Field(..., min_length=1, description="策略ID")


class SetActivePresetRequest(BaseModel):
    """设置激活预设请求"""
    preset_name: str = Field(..., min_length=1, description="预设名称")


# ==================== 策略和预设接口 ====================

@router.get("/strategy/list", response_model=APIResponse)
async def get_strategy_list(container=Depends(get_container)):
    """获取所有可用策略列表（第一级选择）"""
    strategies_dict = container.strategy_monitor_service.get_strategies()
    active = container.strategy_monitor_service.get_active_strategy()

    # 将字典转换为数组格式
    strategies_list = list(strategies_dict.values())

    return APIResponse(
        success=True,
        data={
            'strategies': strategies_list,
            'active_strategy': active
        },
        message="获取策略列表成功"
    )


@router.get("/strategy/presets", response_model=APIResponse)
async def get_strategy_presets(
    strategy_id: str = None,
    container=Depends(get_container)
):
    """获取策略的所有预设（第二级选择）"""
    # 如果指定了 strategy_id，返回该策略的预设
    if strategy_id:
        presets_dict = container.strategy_monitor_service.get_presets_by_strategy(strategy_id)
        strategy_config = container.strategy_monitor_service.strategies.get(strategy_id, {})
        strategy_name = strategy_config.get('name', strategy_id)
        active_preset_name = strategy_config.get('active_preset', '')
    else:
        # 否则返回当前激活策略的预设
        presets_dict = container.strategy_monitor_service.get_presets()
        active_preset = container.strategy_monitor_service.get_active_preset()
        active_strategy = container.strategy_monitor_service.get_active_strategy()
        strategy_name = active_strategy.get('name', '')
        active_preset_name = active_preset['name']

    # 将字典转换为数组格式
    presets_list = [
        {
            'name': name,
            'description': preset.get('description', ''),
            **preset  # 包含其他配置参数
        }
        for name, preset in presets_dict.items()
    ]

    return APIResponse(
        success=True,
        data={
            'strategy': strategy_name,
            'presets': presets_list,
            'active_preset': active_preset_name
        },
        message="获取策略预设成功"
    )


@router.get("/strategy/active", response_model=APIResponse)
async def get_active_strategy_and_preset(container=Depends(get_container)):
    """获取当前激活的策略和预设"""
    strategy = container.strategy_monitor_service.get_active_strategy()
    preset = container.strategy_monitor_service.get_active_preset()

    return APIResponse(
        success=True,
        data={
            'strategy_id': strategy.get('id', ''),
            'strategy_name': strategy.get('name', ''),
            'preset_name': preset.get('name', '')
        },
        message="获取激活策略/预设成功"
    )


@router.get("/strategy/indicators", response_model=APIResponse)
async def get_strategy_indicators(container=Depends(get_container)):
    """获取当前策略的详细指标信息"""
    indicators = container.strategy_monitor_service.get_strategy_indicators()

    return APIResponse(
        success=True,
        data=indicators,
        message="获取策略指标成功"
    )


@router.post("/strategy/active/strategy", response_model=APIResponse)
async def set_active_strategy(
    request: SetActiveStrategyRequest,
    container=Depends(get_container)
):
    """切换当前策略（第一级选择）"""
    result = container.strategy_monitor_service.set_active_strategy(request.strategy_id)

    if not result.get('success', False):
        raise BusinessError(result.get('message', '切换策略失败'))

    return APIResponse(
        success=True,
        data=result.get('data'),
        message=result.get('message', '切换策略成功')
    )


@router.post("/strategy/active/preset", response_model=APIResponse)
async def set_active_preset(
    request: SetActivePresetRequest,
    container=Depends(get_container)
):
    """切换当前预设（第二级选择）"""
    result = container.strategy_monitor_service.set_active_preset(request.preset_name)

    if not result.get('success', False):
        raise BusinessError(result.get('message', '切换预设失败'))

    return APIResponse(
        success=True,
        data=result.get('data'),
        message=result.get('message', '切换预设成功')
    )


@router.get("/strategy/status", response_model=APIResponse)
async def get_strategy_status(container=Depends(get_container)):
    """获取策略服务状态"""
    status = container.strategy_monitor_service.get_service_status()
    return APIResponse(
        success=True,
        data=status,
        message="获取策略状态成功"
    )


# ==================== 监控控制接口 ====================

@router.get("/monitor/status", response_model=APIResponse)
async def get_monitor_status(container=Depends(get_container)):
    """获取监控状态"""
    state = get_state_manager()
    return APIResponse(
        success=True,
        data={
            'is_running': state.is_running(),
            'last_update': state.get_last_update().isoformat() if state.get_last_update() else None,
            'target_stocks_count': len(state.get_target_stocks()),
            'active_preset': container.strategy_monitor_service.active_preset_name
        },
        message="获取监控状态成功"
    )


@router.post("/monitor/start", response_model=APIResponse)
async def start_monitor(
    container=Depends(get_container),
    monitor_coordinator=Depends(get_system_coordinator)
):
    """开始监控"""
    state = get_state_manager()
    if state.is_running():
        raise BusinessError('监控已在运行中')

    # 启动异步监控
    await monitor_coordinator.start()

    return APIResponse(
        success=True,
        data={
            'target_stocks_count': len(state.get_target_stocks())
        },
        message='监控已启动'
    )


@router.post("/monitor/stop", response_model=APIResponse)
async def stop_monitor(
    container=Depends(get_container),
    monitor_coordinator=Depends(get_system_coordinator)
):
    """停止监控"""
    state = get_state_manager()
    if not state.is_running():
        raise BusinessError('监控未在运行')

    # 停止异步监控
    await monitor_coordinator.stop()

    return APIResponse(
        success=True,
        message='监控已停止'
    )
