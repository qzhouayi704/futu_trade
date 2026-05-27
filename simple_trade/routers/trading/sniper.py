#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IntradaySniper API 路由"""

from fastapi import APIRouter
from ...dependencies import get_container

router = APIRouter(prefix="/api/sniper", tags=["盘中狙击手"])


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


@router.get("/simulated-trades")
async def get_simulated_trades(limit: int = 30):
    """获取模拟交易记录（数据库持久化 + 内存中的今日决策）"""
    container = get_container()

    records = []

    # 1. 从数据库获取持久化记录
    try:
        futu_svc = getattr(container, 'futu_trade_service', None)
        if futu_svc and hasattr(futu_svc, 'order_manager'):
            records = futu_svc.order_manager.get_simulated_records(limit)
    except Exception:
        pass

    # 2. 从决策引擎获取今日内存中的决策
    engine = getattr(container, 'trade_decision_engine', None)
    today_decisions = engine.get_today_decisions() if engine else []

    return {
        "success": True,
        "message": f"共 {len(records)} 条持久化记录, {len(today_decisions)} 条今日决策",
        "data": {
            "records": records,
            "today_decisions": today_decisions,
        },
    }
