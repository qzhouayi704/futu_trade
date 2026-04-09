#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易执行路由

包含交易信号、交易执行、持仓查询等接口
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ...core.models import TradeSignal
from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse
from ...utils.cache_helper import get_cache
from .trade_helpers import ExecuteTradeRequest, ensure_trade_service


router = APIRouter(prefix="/api/trading", tags=["交易执行"])


@router.get("/signals", response_model=APIResponse)
async def get_trading_signals(
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    container=Depends(get_container)
):
    """获取交易信号股票列表（异步数据库查询）"""
    # 使用异步数据库查询获取今日交易信号
    query = '''
        SELECT ts.id, ts.stock_id, ts.signal_type, ts.signal_price,
               ts.target_price, ts.stop_loss_price, ts.condition_text,
               ts.is_executed, ts.executed_time, ts.created_at,
               s.code, s.name, ts.strategy_id, ts.strategy_name
        FROM trade_signals ts
        JOIN stocks s ON ts.stock_id = s.id
        WHERE DATE(ts.created_at) = DATE('now', 'localtime')
          AND ts.id IN (
              SELECT MAX(id)
              FROM trade_signals
              WHERE DATE(created_at) = DATE('now', 'localtime')
              GROUP BY stock_id, signal_type, COALESCE(strategy_id, '')
          )
        ORDER BY ts.created_at DESC
        LIMIT ?
    '''
    rows = await container.db_manager.async_execute_query(query, (limit,))
    db_signals = [TradeSignal.from_db_row_with_stock(row) for row in rows]

    # 使用 TradeSignal.to_dict() 序列化，并补充路由特有的格式转换
    signal_list = []
    for signal in db_signals:
        d = signal.to_dict()
        # 此路由使用 signal_price 而非 price，且 signal_type 转小写
        d['signal_price'] = d.pop('price')
        d['signal_type'] = d['signal_type'].lower()
        signal_list.append(d)

    logging.info(f"获取到 {len(signal_list)} 个交易信号")

    return APIResponse(
        success=True,
        data=signal_list,
        message=f"获取到 {len(signal_list)} 个交易信号",
        meta={'count': len(signal_list)}
    )


@router.post("/execute", response_model=APIResponse)
async def execute_trade(
    request: ExecuteTradeRequest,
    container=Depends(get_container)
):
    """执行交易"""
    # 验证数量
    request.validate_quantity()

    trade_service = ensure_trade_service(container)

    result = await asyncio.to_thread(
        trade_service.execute_trade,
        stock_code=request.stock_code,
        trade_type=request.trade_type,
        price=request.price,
        quantity=request.quantity,
        signal_id=request.signal_id
    )

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        data={
            'trade_record_id': result['trade_record_id'],
            'futu_order_id': result['futu_order_id'],
            'stock_code': request.stock_code,
            'trade_type': request.trade_type,
            'price': request.price,
            'quantity': request.quantity
        },
        message=result['message']
    )


@router.get("/kline", response_model=APIResponse)
async def get_kline_data(
    stock_code: str = Query(..., min_length=1, description="股票代码"),
    container=Depends(get_container)
):
    """获取K线数据（异步版本）"""
    # 使用异步数据库查询
    kline_data = await container.db_manager.async_execute_query('''
        SELECT time_key, open_price, close_price, high_price, low_price, volume
        FROM kline_data
        WHERE stock_code = ?
        ORDER BY time_key DESC
        LIMIT 100
    ''', (stock_code,))

    if not kline_data:
        return APIResponse(
            success=True,
            data=[],
            message="暂无K线数据"
        )

    formatted_data = []
    for record in reversed(kline_data):
        time_key, open_price, close_price, high_price, low_price, volume = record
        formatted_data.append({
            'date': time_key,
            'open': float(open_price) if open_price else 0,
            'close': float(close_price) if close_price else 0,
            'high': float(high_price) if high_price else 0,
            'low': float(low_price) if low_price else 0,
            'volume': int(volume) if volume else 0
        })

    return APIResponse(
        success=True,
        data=formatted_data,
        message=f"获取到 {len(formatted_data)} 条K线数据",
        meta={'count': len(formatted_data)}
    )


@router.get("/records", response_model=APIResponse)
async def get_trade_records(
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    status: Optional[str] = Query(None, description="状态过滤"),
    container=Depends(get_container)
):
    """获取交易记录"""
    trade_service = ensure_trade_service(container)

    records = await asyncio.to_thread(trade_service.get_trade_records, limit=limit, status=status)

    return APIResponse(
        success=True,
        data=records,
        message=f"获取到 {len(records)} 条交易记录",
        meta={'count': len(records)}
    )


@router.get("/status", response_model=APIResponse)
async def get_trade_status(container=Depends(get_container)):
    """获取交易连接状态"""
    trade_service = ensure_trade_service(container)

    status = await asyncio.to_thread(trade_service.get_trade_status)

    return APIResponse(
        success=True,
        data=status,
        message="获取交易状态成功"
    )


@router.get("/positions", response_model=APIResponse)
async def get_positions(container=Depends(get_container)):
    """获取持仓信息（带缓存优化）"""
    # 尝试从缓存获取
    cache = get_cache()
    cache_key = "positions:data"
    cached_data = cache.get(cache_key, max_age=30)  # 缓存30秒

    if cached_data:
        logging.debug("持仓数据从缓存返回")
        return APIResponse(
            success=True,
            data=cached_data['positions'],
            message=f"获取到 {len(cached_data['positions'])} 个持仓（缓存）",
            meta={'count': len(cached_data['positions']), 'from_cache': True}
        )

    # 从API获取
    trade_service = ensure_trade_service(container)
    result = await asyncio.to_thread(trade_service.get_positions)

    if not result['success']:
        # 如果获取失败，返回空列表而不是抛出错误
        logging.warning(f"获取持仓失败: {result.get('message')}")
        return APIResponse(
            success=True,
            data=[],
            message=f"获取持仓失败: {result.get('message', '未知错误')}",
            meta={'count': 0, 'error': True}
        )

    # 存入缓存
    cache.set(cache_key, {'positions': result['positions']})

    return APIResponse(
        success=True,
        data=result['positions'],
        message=f"获取到 {len(result['positions'])} 个持仓",
        meta={'count': len(result['positions']), 'from_cache': False}
    )


@router.get("/positions/standalone", response_model=APIResponse)
async def get_positions_standalone(container=Depends(get_container)):
    """独立获取持仓信息（自动连接交易API，带缓存）

    此接口不依赖监控状态，会自动尝试连接交易API。
    适用于系统启动后、监控未启动时获取持仓数据。
    """
    # 尝试从缓存获取
    cache = get_cache()
    cache_key = "positions:standalone:data"
    cached_data = cache.get(cache_key, max_age=30)  # 缓存30秒

    if cached_data:
        logging.debug("独立持仓数据从缓存返回")
        return APIResponse(
            success=True,
            data=cached_data,
            message=f"获取到 {len(cached_data['positions'])} 个持仓（缓存）",
            meta={'count': len(cached_data['positions']), 'from_cache': True}
        )

    trade_service = ensure_trade_service(container)
    auto_connected = False

    # 检查交易API是否已连接，如未连接则尝试自动连接
    if not trade_service.is_trade_ready():
        logging.info("【独立持仓】交易API未连接，尝试自动连接...")
        connect_result = await asyncio.to_thread(trade_service.connect_trade_api)

        if not connect_result['success']:
            # 连接失败，返回空列表
            logging.warning(f"【独立持仓】交易API连接失败: {connect_result['message']}")
            return APIResponse(
                success=True,
                data={'positions': [], 'auto_connected': False, 'trade_api_status': {'is_connected': False, 'is_unlocked': False}},
                message=f"交易API连接失败: {connect_result['message']}",
                meta={'count': 0, 'error': True}
            )

        auto_connected = True
        logging.info("【独立持仓】交易API自动连接成功")

    # 获取持仓
    result = await asyncio.to_thread(trade_service.get_positions)

    if not result['success']:
        # 获取失败，返回空列表
        logging.warning(f"【独立持仓】获取持仓失败: {result['message']}")
        return APIResponse(
            success=True,
            data={'positions': [], 'auto_connected': auto_connected, 'trade_api_status': {'is_connected': trade_service.is_trade_ready(), 'is_unlocked': False}},
            message=result['message'],
            meta={'count': 0, 'error': True}
        )

    result_data = {
        'positions': result['positions'],
        'auto_connected': auto_connected,
        'trade_api_status': {
            'is_connected': trade_service.is_trade_ready(),
            'is_unlocked': getattr(trade_service, 'is_unlocked', False)
        }
    }

    # 存入缓存
    cache.set(cache_key, result_data)

    return APIResponse(
        success=True,
        data=result_data,
        message=f"获取到 {len(result['positions'])} 个持仓",
        meta={'count': len(result['positions']), 'from_cache': False}
    )


@router.post("/connect", response_model=APIResponse)
async def connect_trade_api(container=Depends(get_container)):
    """连接富途交易API"""
    trade_service = ensure_trade_service(container)

    result = await asyncio.to_thread(trade_service.connect_trade_api)

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        data={
            'is_connected': result['is_connected'],
            'is_unlocked': result['is_unlocked']
        },
        message=result['message']
    )
