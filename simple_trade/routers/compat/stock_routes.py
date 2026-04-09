#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票、K线、初始化、报价相关兼容路由

⚠️ 废弃警告 (Deprecated Warning)
================================
本文件中的所有路由已被标记为废弃，将在 2026年9月 后移除。

新接口路径：
- GET  /stocks                → GET  /api/stocks/pool
- POST /stocks                → POST /api/stocks/pool (添加股票)
- GET  /stocks/kline/{code}   → GET  /api/market/kline/{code}
- POST /stocks/init           → POST /api/stocks/init
- GET  /stocks/init/status    → GET  /api/stocks/init/status
- GET  /quotes/conditions     → GET  /api/market/quotes/conditions
- GET  /status                → GET  /api/system/status

请尽快迁移到新接口。
================================
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Path, Body

from ...core import get_state_manager
from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse, PaginatedResponse
from .schemas import AddStocksRequest, InitDataRequest
from .helpers import _add_manual_stocks, _get_stock_info, _get_kline_from_db, _fetch_kline_from_api, _get_trade_points


router = APIRouter()

logger = logging.getLogger(__name__)


def _log_deprecation_warning(endpoint: str, new_endpoint: str):
    """记录废弃警告"""
    logger.warning(
        f"⚠️ 废弃接口调用: {endpoint} | 请迁移到新接口: {new_endpoint} | "
        f"此接口将在 2026年9月 后移除"
    )


# ==================== 股票相关兼容路由 ====================

@router.get("/stocks", response_model=APIResponse)
async def get_stocks(
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=200, description="每页数量"),
    plate_id: Optional[int] = Query(None, description="板块ID过滤"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    container=Depends(get_container)
):
    """获取股票列表 - 兼容前端 GET /stocks

    ⚠️ 已废弃：请使用 GET /api/stocks/pool
    """
    _log_deprecation_warning("GET /stocks", "GET /api/stocks/pool")
    state = get_state_manager()

    pool_data = state.get_stock_pool()
    stocks_data = pool_data['stocks']

    filtered = []
    for stock in stocks_data:
        if plate_id:
            stock_plate_id = stock.get('plate_id')
            if stock_plate_id and str(stock_plate_id) != str(plate_id):
                continue
            elif not stock_plate_id:
                continue

        if search:
            search_lower = search.lower()
            code = str(stock.get('code', '')).lower()
            name = str(stock.get('name', '')).lower()
            if search_lower not in code and search_lower not in name:
                continue
        filtered.append(stock)

    total = len(filtered)
    start = (page - 1) * limit
    paginated = filtered[start:start + limit]

    stocks = [{
        'id': s.get('id', 0),
        'code': s.get('code', ''),
        'name': s.get('name', ''),
        'market': s.get('market', ''),
        'plate_name': s.get('plate_name', ''),
        'plate_names': s.get('plate_names', []),
        'is_manual': s.get('is_manual', False),
        'stock_priority': s.get('stock_priority', 0)
    } for s in paginated]

    return PaginatedResponse.create(
        data=stocks,
        page=page,
        page_size=limit,
        total=total,
        message="获取股票列表成功"
    )


@router.post("/stocks", response_model=APIResponse)
async def add_stocks(
    request: AddStocksRequest,
    container=Depends(get_container)
):
    """添加股票 - 兼容前端 POST /stocks

    ⚠️ 已废弃：请使用 POST /api/stocks/pool
    """
    _log_deprecation_warning("POST /stocks", "POST /api/stocks/pool")

    # 调用辅助函数添加股票
    result = _add_manual_stocks(
        request.stock_codes,
        request.plate_id,
        request.is_manual,
        100,
        container.db_manager,
        container.futu_client
    )

    # 刷新股票池
    from ...services.stock_pool import refresh_global_stock_pool_from_db
    refresh_global_stock_pool_from_db(container.db_manager)

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        data={
            'added_count': result.get('added_count', 0),
            'failed_codes': result.get('failed_codes', [])
        },
        message=result['message']
    )


# ==================== K线相关兼容路由 ====================

@router.get("/stocks/kline/{stock_code}", response_model=APIResponse)
async def get_kline_data(
    stock_code: str = Path(..., description="股票代码"),
    days: int = Query(60, ge=10, le=365, description="获取天数"),
    container=Depends(get_container)
):
    """获取K线数据 - 兼容前端 GET /stocks/kline/<code>

    ⚠️ 已废弃：请使用 GET /api/market/kline/{stock_code}
    """
    _log_deprecation_warning(f"GET /stocks/kline/{stock_code}", f"GET /api/market/kline/{stock_code}")

    # 1. 获取股票基本信息
    stock_info = _get_stock_info(stock_code, container)

    # 2. 从数据库获取K线数据
    kline_data = _get_kline_from_db(stock_code, days, container.db_manager)

    # 3. 如果数据库没有数据，尝试从API获取
    if not kline_data:
        logging.info(f"数据库无K线数据，尝试从API获取: {stock_code}")
        kline_data = _fetch_kline_from_api(stock_code, days, container)

    # 4. 获取交易记录（买卖点）
    trade_points = _get_trade_points(stock_code, days, container.db_manager)

    # 5. 格式化K线数据
    formatted_kline = []
    for row in kline_data:
        formatted_kline.append([
            row['date'],
            row['open'],
            row['close'],
            row['low'],
            row['high'],
            row['volume']
        ])

    return APIResponse(
        success=True,
        data={
            'stock_info': stock_info,
            'kline_data': formatted_kline,
            'trade_points': trade_points
        },
        message=f"获取K线数据成功，共{len(formatted_kline)}条"
    )


# ==================== 初始化相关兼容路由 ====================

@router.post("/stocks/init", response_model=APIResponse)
async def init_data(
    request: InitDataRequest = Body(...),
    container=Depends(get_container)
):
    """数据初始化 - 兼容前端 POST /stocks/init

    ⚠️ 已废弃：请使用 POST /api/stocks/init
    """
    _log_deprecation_warning("POST /stocks/init", "POST /api/stocks/init")

    result = container.stock_pool_service.init_stock_pool(
        force_refresh=request.force_refresh
    )

    if not result.get('success', False):
        raise BusinessError(result.get('message', '数据初始化失败'))

    return APIResponse(
        success=True,
        data={
            'plates_count': result.get('plates_count', 0),
            'stocks_count': result.get('stocks_count', 0)
        },
        message=result.get('message', '数据初始化成功')
    )


@router.get("/stocks/init/status", response_model=APIResponse)
async def get_init_status():
    """获取初始化状态 - 兼容前端 GET /stocks/init/status

    ⚠️ 已废弃：请使用 GET /api/stocks/init/status
    """
    _log_deprecation_warning("GET /stocks/init/status", "GET /api/stocks/init/status")

    state = get_state_manager()
    progress = state.get_init_progress()
    pool_data = state.get_stock_pool()

    return APIResponse(
        success=True,
        data={
            'initialized': pool_data['initialized'],
            'plates_count': len(pool_data['plates']),
            'stocks_count': len(pool_data['stocks']),
            'last_update': pool_data['last_update'],
            'progress': progress
        },
        message="获取初始化状态成功"
    )


# ==================== 报价相关兼容路由 ====================

@router.get("/quotes/conditions", response_model=APIResponse)
async def get_trading_conditions_compat():
    """获取交易条件 - 兼容前端 GET /quotes/conditions

    ⚠️ 已废弃：请使用 GET /api/market/quotes/conditions
    """
    _log_deprecation_warning("GET /quotes/conditions", "GET /api/market/quotes/conditions")

    state = get_state_manager()
    conditions_data = state.get_trading_conditions()
    conditions_list = list(conditions_data.values())

    logging.info(f"从状态管理器获取交易条件数据: {len(conditions_list)} 条记录")

    return APIResponse(
        success=True,
        data=conditions_list,
        message="获取交易条件成功"
    )


# ==================== 系统状态兼容路由 ====================

@router.get("/status", response_model=APIResponse)
async def get_system_status_compat(container=Depends(get_container)):
    """获取系统状态 - 兼容前端 GET /status

    ⚠️ 已废弃：请使用 GET /api/system/status
    """
    _log_deprecation_warning("GET /status", "GET /api/system/status")

    state = get_state_manager()

    subscription_status = container.realtime_query.check_subscription_status()
    last_update = state.get_last_update()

    status_data = {
        'is_running': state.is_running(),
        'last_update': last_update.isoformat() if last_update else None,
        'futu_connected': container.futu_client.is_available(),
        'subscription_status': subscription_status,
        'config': {
            'auto_trade': container.config.auto_trade,
            'update_interval': container.config.update_interval,
            'max_stocks': container.config.max_stocks_monitor
        }
    }

    return APIResponse(
        success=True,
        data=status_data,
        message="获取系统状态成功"
    )


logging.info("股票兼容路由已注册")
