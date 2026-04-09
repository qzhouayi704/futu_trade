#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块相关兼容路由

⚠️ 废弃警告 (Deprecated Warning)
================================
本文件中的所有路由已被标记为废弃，将在 2026年9月 后移除。

新接口路径：
- GET  /stocks/plates              → GET  /api/plates/available
- POST /stocks/plates              → POST /api/plates/add
- POST /stocks/plates/batch        → POST /api/plates/batch-add
- DELETE /stocks/plates/{id}       → DELETE /api/plates/{id}
- GET  /stocks/plates/available    → GET  /api/plates/available
- GET  /stocks/plates/{code}       → GET  /api/plates/{code}/detail
- GET  /stocks/plates/{code}/stocks → GET  /api/plates/{code}/detail
- GET  /stocks/plates/{code}/detail → GET  /api/plates/{code}/detail

请尽快迁移到新接口。
================================
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Path

from ...core import get_state_manager
from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse, PaginatedResponse
from .schemas import AddPlateRequest, BatchAddPlatesRequest
from ..market.plate_helpers import fetch_available_plates
from ...utils.converters import get_last_price


router = APIRouter()

logger = logging.getLogger(__name__)


def _log_deprecation_warning(endpoint: str, new_endpoint: str):
    """记录废弃警告"""
    logger.warning(
        f"⚠️ 废弃接口调用: {endpoint} | 请迁移到新接口: {new_endpoint} | "
        f"此接口将在 2026年9月 后移除"
    )


@router.get("/stocks/plates", response_model=APIResponse)
async def get_plates(
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=200, description="每页数量"),
    container=Depends(get_container)
):
    """获取板块列表 - 兼容前端 GET /stocks/plates

    ⚠️ 已废弃：请使用 GET /api/plates/available
    """
    _log_deprecation_warning("GET /stocks/plates", "GET /api/plates/available")

    state = get_state_manager()

    pool_data = state.get_stock_pool()
    all_plates = pool_data['plates']
    target_plates = [p for p in all_plates if p.get('is_target', False)]
    target_plates.sort(key=lambda x: x.get('priority', 0), reverse=True)

    total = len(target_plates)
    start = (page - 1) * limit
    paginated = target_plates[start:start + limit]

    plates = [{
        'id': p['id'],
        'plate_code': p['code'],
        'plate_name': p['name'],
        'market': p['market'],
        'stock_count': p['stock_count'],
        'is_target': p['is_target'],
        'is_enabled': p.get('is_enabled', True),
        'priority': p.get('priority', 0)
    } for p in paginated]

    return PaginatedResponse.create(
        data=plates,
        page=page,
        page_size=limit,
        total=total,
        message="获取目标板块列表成功"
    )


@router.post("/stocks/plates", response_model=APIResponse)
async def add_plate(
    request: AddPlateRequest,
    container=Depends(get_container)
):
    """添加板块 - 兼容前端 POST /stocks/plates

    ⚠️ 已废弃：请使用 POST /api/plates/add
    """
    _log_deprecation_warning("POST /stocks/plates", "POST /api/plates/add")

    result = container.stock_pool_service.add_plate(request.plate_code)

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        data={'plate_code': request.plate_code},
        message=result['message']
    )


@router.post("/stocks/plates/batch", response_model=APIResponse)
async def batch_add_plates(
    request: BatchAddPlatesRequest,
    container=Depends(get_container)
):
    """批量添加板块 - 兼容前端 POST /stocks/plates/batch

    ⚠️ 已废弃：请使用 POST /api/plates/batch-add
    """
    _log_deprecation_warning("POST /stocks/plates/batch", "POST /api/plates/batch-add")

    success_count = 0
    failed_plates = []

    for plate_code in request.plate_codes:
        try:
            result = container.stock_pool_service.add_plate(plate_code)
            if result['success']:
                success_count += 1
            else:
                failed_plates.append({
                    'plate_code': plate_code,
                    'error': result['message']
                })
        except Exception as e:
            failed_plates.append({'plate_code': plate_code, 'error': str(e)})

    return APIResponse(
        success=True,
        data={
            'success_count': success_count,
            'failed_count': len(failed_plates),
            'failed_plates': failed_plates
        },
        message=f"批量添加完成，成功 {success_count} 个，失败 {len(failed_plates)} 个"
    )


@router.delete("/stocks/plates/{plate_id}", response_model=APIResponse)
async def delete_plate(
    plate_id: int = Path(..., description="板块ID"),
    container=Depends(get_container)
):
    """删除板块 - 兼容前端 DELETE /stocks/plates/<id>

    ⚠️ 已废弃：请使用 DELETE /api/plates/{plate_id}
    """
    _log_deprecation_warning(f"DELETE /stocks/plates/{plate_id}", f"DELETE /api/plates/{plate_id}")

    result = container.stock_pool_service.remove_plate(plate_id)

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        data={'plate_id': plate_id},
        message=result['message']
    )


@router.get("/stocks/plates/available", response_model=APIResponse)
async def get_available_plates(
    search: Optional[str] = Query(None, description="搜索关键词"),
    market: Optional[str] = Query(None, description="市场过滤(HK/US)"),
    status: Optional[str] = Query(None, description="状态过滤(added/not-added)"),
    container=Depends(get_container)
):
    """获取可用板块列表 - 兼容前端 GET /stocks/plates/available

    ⚠️ 已废弃：请使用 GET /api/plates/available
    """
    _log_deprecation_warning("GET /stocks/plates/available", "GET /api/plates/available")

    result_plates = fetch_available_plates(container, search, market, status)

    return APIResponse(
        success=True,
        data=result_plates,
        message="获取可用板块列表成功",
        meta={'total_count': len(result_plates)}
    )


@router.get("/stocks/plates/{plate_code}", response_model=APIResponse)
async def get_plate_by_code(
    plate_code: str = Path(..., description="板块代码"),
    container=Depends(get_container)
):
    """获取板块信息 - 兼容前端 GET /stocks/plates/<code>

    ⚠️ 已废弃：请使用 GET /api/plates/{plate_code}/detail
    """
    _log_deprecation_warning(f"GET /stocks/plates/{plate_code}", f"GET /api/plates/{plate_code}/detail")
    plate_info = await container.db_manager.async_execute_query(
        "SELECT id, plate_code, plate_name, market FROM plates WHERE plate_code = ?",
        (plate_code,)
    )

    if not plate_info:
        raise BusinessError("板块不存在")

    row = plate_info[0]
    # 统计板块下的股票数量
    count_result = await container.db_manager.async_execute_query(
        "SELECT COUNT(*) FROM stock_plates WHERE plate_id = ?",
        (row[0],)
    )
    stock_count = count_result[0][0] if count_result else 0

    return APIResponse(
        success=True,
        data={
            'id': row[0],
            'plate_code': row[1],
            'plate_name': row[2],
            'market': row[3],
            'stock_count': stock_count
        },
        message="获取板块信息成功"
    )


@router.get("/stocks/plates/{plate_code}/stocks", response_model=APIResponse)
async def get_stocks_by_plate(
    plate_code: str = Path(..., description="板块代码"),
    container=Depends(get_container)
):
    """获取板块下的股票列表（含报价数据） - 兼容前端 GET /stocks/plates/<code>/stocks

    ⚠️ 已废弃：请使用 GET /api/plates/{plate_code}/detail
    """
    _log_deprecation_warning(f"GET /stocks/plates/{plate_code}/stocks", f"GET /api/plates/{plate_code}/detail")
    plate_info = await container.db_manager.async_execute_query(
        "SELECT id FROM plates WHERE plate_code = ?",
        (plate_code,)
    )

    if not plate_info:
        raise BusinessError("板块不存在")

    plate_id = plate_info[0][0]
    stocks = await container.db_manager.async_execute_query(
        '''SELECT s.id, s.code, s.name, s.market
           FROM stocks s
           JOIN stock_plates sp ON s.id = sp.stock_id
           WHERE sp.plate_id = ?
           ORDER BY s.code''',
        (plate_id,)
    )

    # 从报价缓存获取实时数据
    state = get_state_manager()
    cached_quotes = state.get_cached_quotes() or []
    quotes_map = {q.get('code'): q for q in cached_quotes if isinstance(q, dict)}

    # 收集没有实时报价的股票代码，用K线数据补充
    missing_codes = []
    stock_info_map = {}

    stock_list = []
    for s in stocks:
        code = s[1]
        stock_data = {
            'id': s[0],
            'code': code,
            'name': s[2],
            'market': s[3]
        }

        quote = quotes_map.get(code)
        if quote:
            stock_data.update({
                'last_price': get_last_price(quote),
                'change_percent': quote.get('change_percent', 0),
                'volume': quote.get('volume', 0),
                'turnover_rate': quote.get('turnover_rate', 0),
                'is_realtime': True
            })
        else:
            missing_codes.append(code)
            stock_info_map[code] = stock_data

        stock_list.append(stock_data)

    # 用K线数据补充缺失的报价
    if missing_codes and container.db_manager:
        for code in missing_codes:
            try:
                kline = container.db_manager.kline_queries.get_stock_kline(code, 2)
                if kline and len(kline) > 0:
                    latest = kline[0]
                    close_price = float(latest.get('close', latest.get('close_price', 0)))
                    prev_close = close_price
                    if len(kline) >= 2:
                        prev_close = float(kline[1].get('close', kline[1].get('close_price', close_price)))
                    change_pct = ((close_price - prev_close) / prev_close * 100) if prev_close > 0 else 0

                    stock_info_map[code].update({
                        'last_price': close_price,
                        'change_percent': round(change_pct, 2),
                        'volume': int(latest.get('volume', 0)),
                        'turnover_rate': float(latest.get('turnover_rate', 0) or 0),
                        'is_realtime': False
                    })
            except Exception:
                pass

    return APIResponse(
        success=True,
        data=stock_list,
        message=f"获取板块股票列表成功，共 {len(stock_list)} 只"
    )


@router.get("/stocks/plates/{plate_code}/detail", response_model=APIResponse)
async def get_plate_detail(
    plate_code: str = Path(..., description="板块代码"),
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=200, description="每页数量"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    container=Depends(get_container)
):
    """获取板块详情 - 兼容前端 GET /stocks/plates/<code>/detail（异步版本）

    ⚠️ 已废弃：请使用 GET /api/plates/{plate_code}/detail
    """
    _log_deprecation_warning(f"GET /stocks/plates/{plate_code}/detail", f"GET /api/plates/{plate_code}/detail")
    # 使用异步数据库查询获取板块信息
    plate_info = await container.db_manager.async_execute_query(
        "SELECT id, plate_code, plate_name, market FROM plates WHERE plate_code = ?",
        (plate_code,)
    )

    if not plate_info:
        raise BusinessError("板块不存在")

    plate = {
        'id': plate_info[0][0],
        'plate_code': plate_info[0][1],
        'plate_name': plate_info[0][2],
        'market': plate_info[0][3]
    }

    # 获取板块下的股票
    stocks_query = '''
        SELECT s.id, s.code, s.name, s.market
        FROM stocks s
        JOIN stock_plates sp ON s.id = sp.stock_id
        WHERE sp.plate_id = ?
    '''
    params = [plate['id']]

    if search:
        stocks_query += " AND (s.code LIKE ? OR s.name LIKE ?)"
        params.extend([f'%{search}%', f'%{search}%'])

    stocks_query += " ORDER BY s.code"

    # 使用异步数据库查询获取股票列表
    all_stocks = await container.db_manager.async_execute_query(stocks_query, tuple(params))

    total = len(all_stocks)
    start = (page - 1) * limit
    paginated = all_stocks[start:start + limit]

    stocks = [{
        'id': s[0],
        'stock_code': s[1],
        'stock_name': s[2],
        'market': s[3]
    } for s in paginated]

    return APIResponse(
        success=True,
        data={
            'plate': plate,
            'stocks': stocks,
            'pagination': {
                'page': page,
                'page_size': limit,
                'total': total,
                'total_pages': (total + limit - 1) // limit if limit > 0 else 0
            }
        },
        message="获取板块详情成功"
    )


logging.info("板块兼容路由已注册")

