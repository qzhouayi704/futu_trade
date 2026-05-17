#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自选股路由 - 活跃个股页面的自选股管理

自选股享受与持仓股相同的待遇：
- 不被活跃度筛选过滤
- 始终显示在活跃个股列表中
- 订阅时不被清理
"""

import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List

from ...core import get_state_manager
from ...dependencies import get_container
from ...schemas.common import APIResponse

router = APIRouter(prefix="/api", tags=["自选股"])
logger = logging.getLogger(__name__)


class WatchlistAddRequest(BaseModel):
    """添加自选股请求"""
    codes: List[str]


# ==================== DB 持久化辅助 ====================

WATCHLIST_PLATE_CODE = "WATCHLIST"


def _ensure_watchlist_plate(db):
    """确保 WATCHLIST 板块存在"""
    try:
        rows = db.execute_query(
            "SELECT id FROM plates WHERE plate_code = ?",
            (WATCHLIST_PLATE_CODE,)
        )
        if rows:
            return rows[0][0]
        db.execute_update(
            "INSERT INTO plates (plate_code, plate_name, market, is_target, is_enabled, priority) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (WATCHLIST_PLATE_CODE, "自选股", "", 0, 1, 0)
        )
        rows = db.execute_query(
            "SELECT id FROM plates WHERE plate_code = ?",
            (WATCHLIST_PLATE_CODE,)
        )
        return rows[0][0] if rows else None
    except Exception as e:
        logger.error(f"确保 WATCHLIST 板块存在失败: {e}")
        return None


def _sync_watchlist_to_db(db, codes: set):
    """将自选股同步到 DB（全量替换）"""
    plate_id = _ensure_watchlist_plate(db)
    if plate_id is None:
        return

    try:
        # 清除旧的自选股板块关联
        db.execute_update(
            "DELETE FROM stock_plates WHERE plate_id = ?",
            (plate_id,)
        )

        # 添加新的关联
        for code in codes:
            rows = db.execute_query(
                "SELECT id FROM stocks WHERE code = ?", (code,)
            )
            if rows:
                stock_id = rows[0][0]
                db.execute_update(
                    "INSERT OR IGNORE INTO stock_plates (stock_id, plate_id) VALUES (?, ?)",
                    (stock_id, plate_id)
                )
    except Exception as e:
        logger.error(f"同步自选股到 DB 失败: {e}")


def _load_watchlist_from_db(db) -> set:
    """从 DB 加载自选股列表"""
    try:
        rows = db.execute_query('''
            SELECT DISTINCT s.code FROM stocks s
            INNER JOIN stock_plates sp ON s.id = sp.stock_id
            INNER JOIN plates p ON sp.plate_id = p.id
            WHERE p.plate_code = ?
        ''', (WATCHLIST_PLATE_CODE,))
        return {row[0] for row in rows} if rows else set()
    except Exception:
        return set()


# ==================== API 路由 ====================


@router.get("/watchlist", response_model=APIResponse)
async def get_watchlist(container=Depends(get_container)):
    """获取自选股列表"""
    state = get_state_manager()
    watchlist = state.get_watchlist()

    # 如果内存为空，尝试从 DB 加载
    if not watchlist:
        db_watchlist = _load_watchlist_from_db(container.db_manager)
        if db_watchlist:
            state.set_watchlist(db_watchlist)
            watchlist = db_watchlist

    return APIResponse(
        success=True,
        data={"codes": sorted(watchlist), "count": len(watchlist)},
        message=f"获取自选股成功，共{len(watchlist)}只",
    )


@router.post("/watchlist", response_model=APIResponse)
async def add_to_watchlist(req: WatchlistAddRequest, container=Depends(get_container)):
    """添加股票到自选股"""
    if not req.codes:
        return APIResponse(success=False, message="股票代码列表不能为空")

    state = get_state_manager()
    state.add_to_watchlist(req.codes)

    # 持久化到 DB
    _sync_watchlist_to_db(container.db_manager, state.get_watchlist())

    logger.info(f"【自选股】添加 {len(req.codes)} 只: {req.codes}")
    return APIResponse(
        success=True,
        data={"codes": sorted(state.get_watchlist())},
        message=f"成功添加 {len(req.codes)} 只股票到自选股",
    )


@router.delete("/watchlist/{code}", response_model=APIResponse)
async def remove_from_watchlist(code: str, container=Depends(get_container)):
    """从自选股移除"""
    state = get_state_manager()
    state.remove_from_watchlist(code)

    # 持久化到 DB
    _sync_watchlist_to_db(container.db_manager, state.get_watchlist())

    logger.info(f"【自选股】移除: {code}")
    return APIResponse(
        success=True,
        data={"codes": sorted(state.get_watchlist())},
        message=f"已从自选股移除 {code}",
    )
