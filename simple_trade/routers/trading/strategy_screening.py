#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略筛选路由 - 信号查询、股票池、激进策略

包含信号历史查询、股票池管理、激进策略相关接口
"""

import logging
from typing import Optional
import asyncio

from fastapi import APIRouter, Depends, Query

from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse
from ...utils.cache_helper import get_cache
from .strategy_helpers import (
    transform_signal_to_dict,
    filter_signals_by_market,
    aggregate_stock_plates,
    transform_plate_data
)


router = APIRouter(prefix="/api", tags=["策略筛选"])


# ==================== 信号查询接口 ====================

@router.get("/strategy/signals", response_model=APIResponse)
async def get_signal_history(
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    type: str = Query('today', description="信号类型(today/history)"),
    market: Optional[str] = Query(None, description="市场过滤(HK/US)"),
    days: int = Query(30, ge=1, le=365, description="历史信号查询天数"),
    strategy_id: Optional[str] = Query(None, description="策略ID过滤(all表示所有策略)"),
    container=Depends(get_container)
):
    """获取信号 - 支持 type=today(今日实时信号) 或 type=history(历史信号)

    简化后的逻辑：
    - 实时信号 (type=today) = 今日数据（从数据库获取当天的信号）
    - 历史信号 (type=history) = 今日以前的数据（从数据库获取历史信号）
    - 信号去重：同一只股票同一天同一类型同一策略只返回最新一条
    - 策略过滤：默认按当前激活策略过滤，strategy_id=all 显示所有策略
    """
    from ...utils.market_helper import MarketTimeHelper

    # 如果没有指定策略ID，使用当前激活的策略
    if strategy_id is None:
        strategy_id = container.strategy_monitor_service.active_strategy_id

    # 获取当前活跃市场
    active_markets = MarketTimeHelper.get_current_active_markets()
    market_info = MarketTimeHelper.get_market_status_info()

    # 根据类型和策略获取信号
    if type == 'today':
        # 获取今日信号（已在数据库层面去重）
        rows = container.db_manager.trade_queries.get_today_signals(limit=limit * 2, strategy_id=strategy_id)
    else:
        # 获取历史信号（今日以前的）
        rows = container.db_manager.trade_history_queries.get_history_signals(days=days, limit=limit * 2, strategy_id=strategy_id)

    # 转换为前端需要的格式（TradeSignal 实例 → dict）
    signals = [transform_signal_to_dict(sig) for sig in rows]

    # 根据市场过滤信号（历史信号不过滤市场，显示所有）
    if type == 'today' and not market:
        filter_markets = active_markets
    elif market:
        filter_markets = [market]
    else:
        filter_markets = None  # 不过滤

    # 过滤信号
    filtered_signals = filter_signals_by_market(signals, filter_markets, limit, MarketTimeHelper)

    return APIResponse(
        success=True,
        data={
            'signals': filtered_signals,
            'count': len(filtered_signals),
            'type': type,
            'market_info': market_info,
            'active_markets': active_markets,
            'filtered_by': filter_markets,
            'strategy_id': strategy_id
        },
        message=f"获取信号成功，共{len(filtered_signals)}条"
    )


@router.delete("/strategy/signals", response_model=APIResponse)
async def clear_signal_history(container=Depends(get_container)):
    """清空信号历史"""
    container.strategy_monitor_service.clear_signal_history()
    return APIResponse(
        success=True,
        message='信号历史已清空'
    )


# ==================== 股票池接口 ====================

@router.get("/stocks/pool", response_model=APIResponse)
async def get_stock_pool(container=Depends(get_container)):
    """获取股票池"""
    # 从数据库获取股票池
    stock_rows = container.db_manager.stock_queries.get_stocks_with_plate_info()
    plate_rows = container.db_manager.plate_queries.get_plates_with_stock_count()

    # 股票去重：使用字典按code去重，同时聚合板块信息
    stocks = aggregate_stock_plates(stock_rows)

    # 转换板块数据格式
    plates = transform_plate_data(plate_rows)

    return APIResponse(
        success=True,
        data={
            'stocks': stocks,
            'plates': plates,
            'total_stocks': len(stocks),
            'total_plates': len(plates)
        },
        message="获取股票池成功"
    )


# ==================== 激进策略接口 ====================

@router.post("/strategy/aggressive/signals", response_model=APIResponse)
async def generate_aggressive_signals(container=Depends(get_container)):
    """生成激进策略交易信号"""
    # 检查服务是否可用
    if not container.aggressive_trade_service:
        raise BusinessError('激进策略服务未初始化')

    # 生成信号（异步调用）
    signals = await container.aggressive_trade_service.generate_signals()

    return APIResponse(
        success=True,
        data={
            'signals': signals,
            'count': len(signals)
        },
        message=f'成功生成 {len(signals)} 个交易信号'
    )


@router.post("/strategy/aggressive/risk-check", response_model=APIResponse)
async def check_aggressive_positions_risk(container=Depends(get_container)):
    """检查激进策略持仓风险"""
    # 检查服务是否可用
    if not container.aggressive_trade_service:
        raise BusinessError('激进策略服务未初始化')

    # 检查风险（异步调用）
    risk_results = await container.aggressive_trade_service.check_positions_risk()

    return APIResponse(
        success=True,
        data={
            'risk_results': risk_results,
            'count': len(risk_results)
        },
        message=f'检查完成，发现 {len(risk_results)} 个风险提示'
    )


@router.get("/strategy/aggressive/plate-strength", response_model=APIResponse)
async def get_plate_strength(container=Depends(get_container)):
    """获取板块强势度排名（带缓存优化）"""
    try:
        # 尝试从缓存获取
        cache = get_cache()
        cache_key = "plate_strength:data"
        cached_data = cache.get(cache_key, max_age=300)  # 缓存5分钟

        if cached_data:
            logging.info("板块强势度数据从缓存返回")
            return APIResponse(
                success=True,
                data=cached_data,
                message="获取板块强势度成功（缓存）"
            )

        # 检查服务是否可用
        if not container.aggressive_trade_service:
            raise BusinessError('激进策略服务未初始化')

        # 获取强势板块（异步调用）
        strong_plates = await container.aggressive_trade_service._get_strong_plates()

        # 如果没有数据，返回空列表
        if not strong_plates:
            return APIResponse(
                success=True,
                data={'plates': [], 'count': 0},
                message="暂无板块数据"
            )

        # 转换为前端需要的格式（不获取龙头股票，减少API调用）
        plates_data = []
        for plate in strong_plates:
            plates_data.append({
                'plate_code': plate.plate_code,
                'plate_name': plate.plate_name,
                'market': plate.market,
                'strength_score': plate.strength_score,
                'up_stock_ratio': plate.up_stock_ratio,
                'avg_change_pct': plate.avg_change_pct,
                'leader_count': plate.leader_count,
                'total_stocks': plate.total_stocks,
                'leader_stocks': []  # 暂时不获取龙头股票，提升性能
            })

        result_data = {
            'plates': plates_data,
            'count': len(plates_data)
        }

        # 存入缓存
        cache.set(cache_key, result_data)
        logging.info(f"板块强势度数据已缓存，共{len(plates_data)}个板块")

        return APIResponse(
            success=True,
            data=result_data,
            message="获取板块强势度成功"
        )

    except BusinessError:
        # 重新抛出业务错误
        raise
    except Exception as e:
        logging.error(f"获取板块强势度失败: {e}", exc_info=True)
        # 返回空数据而不是抛出错误，避免阻塞页面加载
        return APIResponse(
            success=True,
            data={'plates': [], 'count': 0},
            message=f"获取板块强势度失败: {str(e)}"
        )