#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入场择时（实验·只读）API

强势股低吸择时绿灯。纯展示，绝不参与下单/评分/门控。
依据 2026-06 生产逐笔回测：强势股买"刚回调"前向收益/胜率最高，追"刚冲高"最差。
"""

import logging

from fastapi import APIRouter, Depends

from ...dependencies import get_container
from ...schemas.common import APIResponse

router = APIRouter(prefix="/api/entry-timing", tags=["入场择时(实验)"])
logger = logging.getLogger("router.entry_timing")


@router.get("/watch", response_model=APIResponse)
async def get_entry_timing_watch(container=Depends(get_container)):
    """强势股观察池 + 每只的入场择时绿灯（🟢可低吸 / 🔴别追 / ⚪观望）。

    只读：从日线建近几日强势股池，读近 15min 逐笔算 mom5/主动买卖单流/日内价位。
    """
    db = getattr(container, "db_manager", None)
    if not db:
        return APIResponse(success=False, data=None, message="数据库不可用")
    try:
        from ...services.trading.entry_timing import EntryTimingService
        data = EntryTimingService(db).watch()
        greens = sum(1 for it in data["items"] if it["light"] == "green")
        return APIResponse(
            success=True, data=data,
            message=f"强势股 {data['pool_size']} 只，可低吸 {greens} 只（实验·仅展示不下单）")
    except Exception as e:  # noqa: BLE001
        logger.exception("entry-timing watch failed")
        return APIResponse(success=False, data=None, message=f"计算失败: {e}")
