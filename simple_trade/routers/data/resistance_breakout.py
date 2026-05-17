#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阻力位突破扫描 API 路由"""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends

from ...dependencies import get_container
from ...core import get_state_manager
from ...schemas.common import APIResponse
from ...services.analysis.resistance_breakout_scanner import ResistanceBreakoutScanner

logger = logging.getLogger("resistance_breakout")
router = APIRouter(prefix="/api/resistance-breakout", tags=["突破扫描"])

# 全局任务状态
_task_status = {"running": False, "progress": "", "result": None, "error": None, "timestamp": None}


@router.post("", response_model=APIResponse)
async def trigger_scan(container=Depends(get_container)):
    """触发阻力位突破扫描"""
    global _task_status

    if _task_status["running"]:
        return APIResponse(success=False, message="扫描任务正在运行中，请等待完成")

    _task_status = {"running": True, "progress": "准备数据...", "result": None, "error": None,
                    "timestamp": datetime.now().isoformat()}

    asyncio.create_task(_run_scan(container))
    return APIResponse(success=True, message="突破扫描已启动", data={"status": "running"})


@router.get("/status", response_model=APIResponse)
async def get_status():
    """查询扫描任务状态"""
    return APIResponse(success=True, message="获取状态成功", data={
        "running": _task_status["running"],
        "progress": _task_status["progress"],
        "has_result": _task_status["result"] is not None,
        "error": _task_status["error"],
        "timestamp": _task_status["timestamp"],
    })


@router.get("/result", response_model=APIResponse)
async def get_result():
    """获取扫描结果"""
    if _task_status["running"]:
        return APIResponse(success=True, message="任务运行中", data={"running": True, "candidates": []})

    result = _task_status.get("result")
    if not result:
        return APIResponse(success=True, message="暂无结果，请先触发扫描", data={"candidates": [], "total": 0})

    return APIResponse(success=True, message=f"共 {len(result)} 只突破候选", data={
        "candidates": result,
        "timestamp": _task_status.get("timestamp"),
        "total": len(result),
    })


async def _run_scan(container):
    """后台执行扫描任务"""
    global _task_status
    try:
        _task_status["progress"] = "获取股票列表..."

        # 从市场扫描报价快照获取活跃股代码
        state = get_state_manager()
        stock_codes = []
        cached_quotes = state.quote_cache.get_last_quotes()
        if cached_quotes:
            stock_codes = [
                q.get('code', q.get('stock_code', ''))
                for q in cached_quotes
                if q.get('code', q.get('stock_code', ''))
            ]

        if not stock_codes:
            _task_status["error"] = "未获取到活跃股数据，请确保市场扫描已运行"
            _task_status["running"] = False
            return

        _task_status["progress"] = f"扫描 {len(stock_codes)} 只股票..."

        # 尝试获取日内阻力位服务（可选）
        intraday_levels = getattr(container, 'intraday_levels_service', None)

        scanner = ResistanceBreakoutScanner(
            db_manager=container.db_manager,
            intraday_levels_service=intraday_levels,
        )
        candidates = await scanner.scan(stock_codes)

        _task_status["result"] = [c.to_dict() for c in candidates]
        _task_status["timestamp"] = datetime.now().isoformat()
        _task_status["progress"] = "完成"

        logger.info(f"【突破扫描】完成，{len(candidates)} 只候选")

    except Exception as e:
        logger.error(f"【突破扫描】执行失败: {e}", exc_info=True)
        _task_status["error"] = str(e)
    finally:
        _task_status["running"] = False


logging.info("阻力位突破扫描路由已注册")
