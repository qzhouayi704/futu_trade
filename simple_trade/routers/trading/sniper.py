#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IntradaySniper API 路由"""

from fastapi import APIRouter
from ...dependencies import get_container

router = APIRouter(prefix="/sniper", tags=["盘中狙击手"])


@router.get("/signals")
async def get_signals():
    """获取今日所有狙击手信号"""
    container = get_container()
    sniper = getattr(container, 'intraday_sniper', None)
    if not sniper:
        return {"success": False, "message": "IntradaySniper 未初始化", "data": []}

    signals = sniper.get_today_signals()
    return {
        "success": True,
        "message": f"今日共 {len(signals)} 条信号",
        "data": signals,
    }


@router.get("/signals/recent")
async def get_recent_signals(minutes: int = 30):
    """获取最近N分钟的信号"""
    container = get_container()
    sniper = getattr(container, 'intraday_sniper', None)
    if not sniper:
        return {"success": False, "message": "IntradaySniper 未初始化", "data": []}

    signals = sniper.get_recent_signals(minutes)
    return {
        "success": True,
        "message": f"最近{minutes}分钟内 {len(signals)} 条信号",
        "data": signals,
    }


@router.get("/ranking")
async def get_ranking():
    """获取 TOP 3 机会/风险排行榜"""
    container = get_container()
    sniper = getattr(container, 'intraday_sniper', None)
    if not sniper:
        return {"success": False, "message": "IntradaySniper 未初始化", "data": {}}

    ranking = sniper.get_top_ranking()
    return {
        "success": True,
        "data": ranking,
    }
