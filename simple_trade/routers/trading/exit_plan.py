#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预设离场计划路由

盘前为持仓定"开盘若X则卖/减/持有"，开盘检查(open_check/exit_timing)读取后判定命中。
专治"开盘想卖却干等信号"——把被动等信号变成执行计划。

响应统一 {success, data, message}（APIResponse）。内部 stock_id，外部 stock_code。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...dependencies import get_container
from ...schemas.common import APIResponse


router = APIRouter(prefix="/api/trading/exit-plans", tags=["离场计划"])


# ==================== Pydantic Models ====================

class ExitPlanRequest(BaseModel):
    """创建/更新离场计划请求"""
    stock_code: str = Field(..., min_length=1, description="股票代码")
    planned_action: str = Field(..., pattern="^(sell|hold|trim)$", description="计划动作")
    trigger_type: str = Field(
        ..., pattern="^(gap_down_pct|below_prev_close|at_open_unconditional)$",
        description="触发类型")
    trigger_value: Optional[float] = Field(None, description="触发阈值（如 gap_down_pct 用 -0.03）")
    note: Optional[str] = Field(None, description="备注")
    valid_for_date: Optional[str] = Field(None, description="生效日期 YYYY-MM-DD(HK)，默认今天")


# ==================== Helper ====================

def _db(container):
    db = getattr(container, 'db_manager', None)
    if not db:
        raise RuntimeError("数据库未初始化")
    return db


def _hk_today() -> str:
    from ...utils.market_helper import MarketTimeHelper
    return MarketTimeHelper.get_market_today('HK')


def _norm_code(code: str) -> str:
    return code if "." in code else f"HK.{code}"


# ==================== API Endpoints ====================

@router.post("")
async def create_exit_plan(request: ExitPlanRequest, container=Depends(get_container)):
    """创建/更新某只持仓的离场计划（按 股票代码+生效日 upsert）。"""
    try:
        db = _db(container)
        from ...database.queries.exit_plan_queries import ExitPlanQueries
        code = _norm_code(request.stock_code)
        date = request.valid_for_date or _hk_today()
        ExitPlanQueries(db).upsert(
            code, request.planned_action, request.trigger_type,
            request.trigger_value, request.note, date)
        return APIResponse.ok(
            data={"stock_code": code, "valid_for_date": date,
                  "planned_action": request.planned_action,
                  "trigger_type": request.trigger_type},
            message="离场计划已保存")
    except Exception as e:
        logging.error(f"保存离场计划失败: {e}")
        return APIResponse.fail(message=str(e))


@router.get("")
async def list_exit_plans(date: Optional[str] = None, container=Depends(get_container)):
    """列出某日生效的离场计划（默认今天）。"""
    try:
        db = _db(container)
        from ...database.queries.exit_plan_queries import ExitPlanQueries
        d = date or _hk_today()
        plans = ExitPlanQueries(db).list_plans(d)
        return APIResponse.ok(data=plans, message=f"{len(plans)} 条离场计划")
    except Exception as e:
        logging.error(f"查询离场计划失败: {e}")
        return APIResponse.fail(message=str(e))


@router.delete("/{plan_id}")
async def delete_exit_plan(plan_id: int, container=Depends(get_container)):
    """软删除某条离场计划。"""
    try:
        db = _db(container)
        from ...database.queries.exit_plan_queries import ExitPlanQueries
        ExitPlanQueries(db).soft_delete(plan_id)
        return APIResponse.ok(data={"id": plan_id}, message="离场计划已删除")
    except Exception as e:
        logging.error(f"删除离场计划失败: {e}")
        return APIResponse.fail(message=str(e))
