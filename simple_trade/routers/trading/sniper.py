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


@router.get("/simulated-trades/daily")
async def get_simulated_trades_daily(date: str = "", limit: int = 100):
    """按日期获取模拟交易记录 + 每日汇总统计

    Args:
        date: 日期筛选 (YYYY-MM-DD)，空则返回所有日期的汇总
        limit: 记录数量上限
    """
    container = get_container()

    try:
        futu_svc = getattr(container, 'futu_trade_service', None)
        if not futu_svc or not hasattr(futu_svc, 'order_manager'):
            return {"success": False, "message": "交易服务未初始化", "data": {}}

        db = futu_svc.order_manager.db_manager

        # 按日期分组统计
        daily_stats = db.execute_query('''
            SELECT
                DATE(created_at) as trade_date,
                COUNT(*) as total_trades,
                SUM(CASE WHEN direction = 'BUY' THEN 1 ELSE 0 END) as buy_count,
                SUM(CASE WHEN direction = 'SELL' THEN 1 ELSE 0 END) as sell_count,
                ROUND(SUM(amount), 2) as total_amount,
                COUNT(DISTINCT stock_code) as stock_count
            FROM simulated_trade_records
            GROUP BY DATE(created_at)
            ORDER BY trade_date DESC
            LIMIT 30
        ''', [])

        stats_list = [
            {
                'date': row[0], 'total_trades': row[1],
                'buy_count': row[2], 'sell_count': row[3],
                'total_amount': row[4], 'stock_count': row[5],
            }
            for row in daily_stats
        ]

        # 获取指定日期的详细记录
        records = []
        if date:
            rows = db.execute_query('''
                SELECT id, stock_code, stock_name, direction, price, quantity,
                       amount, resonance_type, reason, sources, created_at
                FROM simulated_trade_records
                WHERE DATE(created_at) = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', [date, limit])
            records = [
                {
                    'id': r[0], 'stock_code': r[1], 'stock_name': r[2],
                    'direction': r[3], 'price': r[4], 'quantity': r[5],
                    'amount': r[6], 'resonance_type': r[7], 'reason': r[8],
                    'sources': r[9], 'created_at': r[10],
                }
                for r in rows
            ]

        return {
            "success": True,
            "data": {
                "daily_stats": stats_list,
                "records": records,
                "selected_date": date,
            },
        }

    except Exception as e:
        return {"success": False, "message": str(e), "data": {}}
