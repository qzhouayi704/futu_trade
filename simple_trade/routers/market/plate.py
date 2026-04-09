#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块管理路由 - FastAPI Router

迁移自 routes/plate_routes.py
包含板块管理相关接口
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Path, Body
from pydantic import BaseModel, Field

from ...core import get_state_manager
from ...core.exceptions import BusinessError, ValidationError
from ...dependencies import get_container
from ...schemas.common import APIResponse
from .plate_helpers import fetch_available_plates


router = APIRouter(prefix="/api/plates", tags=["板块管理"])


# ==================== Pydantic Models ====================

class PlateInfo(BaseModel):
    """板块信息"""
    plate_code: str
    plate_name: str
    market: str
    is_added: bool
    status: str


class AddPlateRequest(BaseModel):
    """添加板块请求"""
    plate_code: str = Field(..., min_length=1, description="板块代码")


class BatchAddPlatesRequest(BaseModel):
    """批量添加板块请求"""
    plate_codes: List[str] = Field(..., min_items=1, description="板块代码列表")


class UpdatePriorityRequest(BaseModel):
    """更新优先级请求"""
    priority: int = Field(..., ge=0, le=100, description="优先级(0-100)")


class PlateStatusResponse(BaseModel):
    """板块状态响应"""
    plate_id: int
    is_enabled: bool
    is_target: bool


# ==================== API Endpoints ====================

@router.get("/available", response_model=APIResponse)
async def get_available_plates(
    search: Optional[str] = Query(None, description="搜索关键词"),
    market: Optional[str] = Query(None, description="市场(HK/US)"),
    status: Optional[str] = Query(None, description="状态过滤(added/not-added)"),
    container=Depends(get_container)
):
    """获取所有可用板块列表"""
    result_plates = fetch_available_plates(container, search, market, status)

    return APIResponse(
        success=True,
        data=result_plates,
        message="获取可用板块列表成功",
        meta={'total_count': len(result_plates)}
    )


@router.post("/add", response_model=APIResponse)
async def add_plate(
    request: AddPlateRequest,
    container=Depends(get_container)
):
    """添加板块"""
    result = container.stock_pool_service.add_plate(request.plate_code)

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        data={'plate_code': request.plate_code},
        message=result['message']
    )


@router.post("/batch-add", response_model=APIResponse)
async def batch_add_plates(
    request: BatchAddPlatesRequest,
    container=Depends(get_container)
):
    """批量添加板块"""
    success_count = 0
    failed_plates = []

    for plate_code in request.plate_codes:
        try:
            result = container.stock_pool_service.add_plate(plate_code)
            if result['success']:
                success_count += 1
            else:
                failed_plates.append({'plate_code': plate_code, 'error': result['message']})
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


@router.delete("/{plate_id}", response_model=APIResponse)
async def delete_plate(
    plate_id: int = Path(..., description="板块ID"),
    container=Depends(get_container)
):
    """删除板块"""
    result = container.stock_pool_service.remove_plate(plate_id)

    if not result['success']:
        raise BusinessError(result['message'])

    return APIResponse(
        success=True,
        data={'plate_id': plate_id},
        message=result['message']
    )


@router.put("/{plate_id}/priority", response_model=APIResponse)
async def update_plate_priority(
    plate_id: int = Path(..., description="板块ID"),
    request: UpdatePriorityRequest = Body(...),
    container=Depends(get_container)
):
    """更新板块优先级"""
    with container.db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE plates SET priority = ? WHERE id = ?", (request.priority, plate_id))

        if cursor.rowcount == 0:
            raise BusinessError("板块不存在")

        conn.commit()

        # 刷新状态
        from ...services.stock_pool import refresh_global_stock_pool_from_db
        refresh_global_stock_pool_from_db(container.db_manager)

        return APIResponse(
            success=True,
            data={'plate_id': plate_id, 'priority': request.priority},
            message=f"板块优先级已更新为 {request.priority}"
        )


@router.put("/{plate_id}/toggle", response_model=APIResponse)
async def toggle_plate_status(
    plate_id: int = Path(..., description="板块ID"),
    container=Depends(get_container)
):
    """切换板块启用/禁用状态

    注意: 这里切换的是 is_enabled 字段（控制是否参与监控），
    而不是 is_target 字段（是否为目标板块）
    """
    with container.db_manager.get_connection() as conn:
        cursor = conn.cursor()

        # 获取当前状态
        cursor.execute("SELECT is_enabled, plate_name, is_target FROM plates WHERE id = ?", (plate_id,))
        result = cursor.fetchone()

        if not result:
            raise BusinessError("板块不存在")

        current_enabled = result[0] if result[0] is not None else 1
        plate_name = result[1]
        is_target = result[2]
        new_enabled = 0 if current_enabled else 1

        # 更新启用状态（不改变is_target）
        cursor.execute("UPDATE plates SET is_enabled = ? WHERE id = ?", (new_enabled, plate_id))
        conn.commit()

        # 刷新状态
        from ...services.stock_pool import refresh_global_stock_pool_from_db
        refresh_global_stock_pool_from_db(container.db_manager)

        status_text = "启用" if new_enabled else "禁用"
        return APIResponse(
            success=True,
            data={
                'plate_id': plate_id,
                'is_enabled': bool(new_enabled),
                'is_target': bool(is_target)
            },
            message=f"板块 {plate_name} 已{status_text}"
        )


@router.get("/overview", response_model=APIResponse)
async def get_plate_overview(container=Depends(get_container)):
    """获取板块概览（含股票数量和热门股数量）

    合并自 plate_routes.py
    """
    hot_service = container.hot_stock_service
    overview = hot_service.get_plate_overview()
    heat_status = hot_service.get_heat_status()

    return APIResponse(
        success=True,
        data={
            'plates': overview,
            'heat_status': heat_status
        },
        message="获取板块概览成功"
    )


@router.get("/{plate_code}/detail", response_model=APIResponse)
async def get_plate_detail(
    plate_code: str = Path(..., description="板块代码"),
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=200, description="每页数量"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    container=Depends(get_container)
):
    """获取板块详情和股票列表

    合并自 plate_routes.py
    """
    import asyncio
    from ..data.helpers.route_helpers import get_position_codes

    state = get_state_manager()
    search_lower = search.strip().lower() if search else ""

    # 获取板块信息
    plate_info = await container.db_manager.async_execute_query('''
        SELECT id, plate_code, plate_name, market, category, stock_count,
               is_target, is_enabled, priority
        FROM plates WHERE plate_code = ?
    ''', (plate_code,))

    if not plate_info:
        raise BusinessError(f"板块 {plate_code} 不存在")

    row = plate_info[0]
    plate = {
        'id': row[0],
        'plate_code': row[1],
        'plate_name': row[2],
        'market': row[3],
        'category': row[4] or '',
        'stock_count': row[5] or 0,
        'is_target': bool(row[6]),
        'is_enabled': bool(row[7]) if row[7] is not None else True,
        'priority': row[8] or 0
    }

    # 获取板块下的股票
    stocks_query = '''
        SELECT DISTINCT s.id, s.code, s.name, s.market, s.heat_score, s.is_manual
        FROM stocks s
        INNER JOIN stock_plates sp ON s.id = sp.stock_id
        INNER JOIN plates p ON sp.plate_id = p.id
        WHERE p.plate_code = ?
    '''
    params = [plate_code]

    if search_lower:
        stocks_query += ' AND (LOWER(s.code) LIKE ? OR LOWER(s.name) LIKE ?)'
        params.extend([f'%{search_lower}%', f'%{search_lower}%'])

    stocks_query += ' ORDER BY s.heat_score DESC, s.code'

    all_stocks_result = await container.db_manager.async_execute_query(stocks_query, tuple(params))

    # 获取持仓股票代码
    position_codes = await asyncio.to_thread(get_position_codes, container)

    # 获取监控任务
    monitor_tasks = state.get_monitor_tasks()
    monitored_codes = {task['stock_code'] for task in monitor_tasks}

    # 构建股票列表
    all_stocks = []
    for row in all_stocks_result:
        stock_code = row[1]
        all_stocks.append({
            'id': row[0],
            'code': stock_code,
            'name': row[2],
            'market': row[3],
            'heat_score': row[4] or 0,
            'is_manual': bool(row[5]),
            'is_position': stock_code in position_codes,
            'is_monitored': stock_code in monitored_codes
        })

    # 持仓股置顶，其余按 heat_score 降序
    all_stocks.sort(key=lambda s: (not s["is_position"], -s["heat_score"]))

    # 分页
    total = len(all_stocks)
    start = (page - 1) * limit
    end = start + limit
    stocks = all_stocks[start:end]

    return APIResponse(
        success=True,
        data={
            'plate': plate,
            'stocks': stocks,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        },
        message="获取板块详情成功"
    )


logging.info("板块管理路由已注册")
