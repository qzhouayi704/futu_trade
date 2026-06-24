#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持仓做T助手路由（高抛低吸 / 正T）

查看当日做T腿状态、开关/模式配置；半自动确认/取消（Phase 2 接入真实下单）。
响应统一 {success, data, message}（APIResponse）。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...dependencies import get_container
from ...schemas.common import APIResponse


router = APIRouter(prefix="/api/trading/t-trade", tags=["持仓做T"])


class TConfigRequest(BaseModel):
    enabled: Optional[bool] = Field(None, description="做T总开关")
    mode: Optional[str] = Field(None, pattern="^(alert|semi|full)$", description="执行模式")


class TLegActionRequest(BaseModel):
    leg_id: int = Field(..., description="做T腿 id")


def _assistant(container):
    a = getattr(container, 't_trade_assistant', None)
    if not a:
        raise RuntimeError("做T助手未初始化")
    return a


@router.get("/status")
async def t_trade_status(container=Depends(get_container)):
    """当日做T腿状态 + 当前开关/模式 + 已实现盈亏。"""
    try:
        data = _assistant(container).get_status()
        return APIResponse.ok(data=data, message="ok")
    except Exception as e:
        logging.error(f"查询做T状态失败: {e}")
        return APIResponse.fail(message=str(e))


@router.get("/config")
async def get_t_trade_config(container=Depends(get_container)):
    """读取做T开关/模式（含护栏默认值）。"""
    try:
        st = _assistant(container).get_status()
        return APIResponse.ok(
            data={"enabled": st["enabled"], "mode": st["mode"], "config": st["config"]},
            message="ok")
    except Exception as e:
        logging.error(f"读取做T配置失败: {e}")
        return APIResponse.fail(message=str(e))


@router.post("/config")
async def set_t_trade_config(request: TConfigRequest, container=Depends(get_container)):
    """设置做T开关/模式（写 system_config，重启不丢）。"""
    try:
        res = _assistant(container).set_config(enabled=request.enabled, mode=request.mode)
        if res.get("ok"):
            return APIResponse.ok(data=res, message=res.get("message", "已更新"))
        return APIResponse.fail(message=res.get("message", "更新失败"))
    except Exception as e:
        logging.error(f"设置做T配置失败: {e}")
        return APIResponse.fail(message=str(e))


@router.post("/confirm")
async def confirm_t_leg(request: TLegActionRequest, container=Depends(get_container)):
    """半自动确认某条做T腿（Phase 2 走 /api/trading/execute 真实下单）。"""
    try:
        res = _assistant(container).confirm_leg(request.leg_id)
        if res.get("ok"):
            return APIResponse.ok(data=res, message=res.get("message", "已确认"))
        return APIResponse.fail(message=res.get("message", "确认失败"))
    except Exception as e:
        logging.error(f"确认做T腿失败: {e}")
        return APIResponse.fail(message=str(e))


@router.post("/cancel")
async def cancel_t_leg(request: TLegActionRequest, container=Depends(get_container)):
    """取消某条做T腿（标记失效）。"""
    try:
        res = _assistant(container).cancel_leg(request.leg_id)
        if res.get("ok"):
            return APIResponse.ok(data=res, message=res.get("message", "已取消"))
        return APIResponse.fail(message=res.get("message", "取消失败"))
    except Exception as e:
        logging.error(f"取消做T腿失败: {e}")
        return APIResponse.fail(message=str(e))
