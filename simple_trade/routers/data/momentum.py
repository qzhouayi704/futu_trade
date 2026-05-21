#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动量引擎 API 路由

提供动量引擎状态查询和信号数据接口。
"""

import logging
from fastapi import APIRouter, Depends

from ...dependencies import get_container
from ...schemas.common import APIResponse

router = APIRouter(prefix="/api/momentum", tags=["动量引擎"])
logger = logging.getLogger(__name__)


@router.get("/status", response_model=APIResponse)
async def get_momentum_status(container=Depends(get_container)):
    """获取动量引擎运行状态"""
    engine = getattr(container, 'momentum_engine', None)
    if not engine:
        return APIResponse(success=False, message="动量引擎未启动", data={})

    return APIResponse(
        success=True,
        data=engine.get_status(),
        message="动量引擎运行中",
    )


@router.get("/stock/{stock_code}", response_model=APIResponse)
async def get_stock_momentum(stock_code: str, container=Depends(get_container)):
    """获取单只股票的动量状态"""
    engine = getattr(container, 'momentum_engine', None)
    if not engine:
        return APIResponse(success=False, message="动量引擎未启动", data={})

    data = engine.get_stock_momentum(stock_code)
    return APIResponse(
        success=True,
        data=data,
        message=f"{stock_code} 动量状态",
    )


@router.get("/all-states", response_model=APIResponse)
async def get_all_momentum_states(container=Depends(get_container)):
    """获取所有监控股票的动量状态"""
    engine = getattr(container, 'momentum_engine', None)
    if not engine:
        return APIResponse(success=False, message="动量引擎未启动", data={})

    states = engine.get_all_states()
    return APIResponse(
        success=True,
        data={
            "stocks": states,
            "count": len(states),
        },
        message=f"共 {len(states)} 只有数据的股票",
    )


logger.info("动量引擎路由已注册")
