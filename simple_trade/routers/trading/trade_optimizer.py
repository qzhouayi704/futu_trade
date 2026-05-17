#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易优化API路由

提供评分系统、交易阶段、频率管控的查询接口。
"""

import json
import os
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from ...dependencies import get_container

router = APIRouter(prefix="/trade-optimizer", tags=["交易优化"])
logger = logging.getLogger(__name__)


@router.get("/scoring/status")
async def get_scoring_status(container=Depends(get_container)):
    """获取评分系统状态和候选标的列表"""
    scorer = container.stock_scorer
    if not scorer:
        return {"success": False, "message": "评分引擎未初始化"}

    candidates = scorer.get_candidates()
    all_scores = list(scorer._scored_cache.values())

    return {
        "success": True,
        "data": {
            "total_scored": len(all_scores),
            "candidates": len(candidates),
            "candidate_list": [c.to_dict() for c in candidates],
            "all_scores": [s.to_dict() for s in sorted(
                all_scores, key=lambda x: x.total_score, reverse=True
            )],
        }
    }


@router.get("/scoring/stock/{stock_code}")
async def get_stock_score(stock_code: str, container=Depends(get_container)):
    """获取指定标的的评分详情"""
    scorer = container.stock_scorer
    if not scorer:
        return {"success": False, "message": "评分引擎未初始化"}

    result = scorer.get_score(stock_code)
    if not result:
        return {"success": False, "message": f"{stock_code} 未评分（需先运行盘前评分）"}

    return {"success": True, "data": result.to_dict()}


@router.get("/phase/current")
async def get_current_phase(container=Depends(get_container)):
    """获取当前交易阶段和操作指导"""
    phase_mgr = container.trading_phase_manager
    if not phase_mgr:
        return {"success": False, "message": "阶段管理器未初始化"}

    return {"success": True, "data": phase_mgr.get_status()}


@router.get("/guard/status")
async def get_guard_status(container=Depends(get_container)):
    """获取频率管控状态"""
    guard = container.trade_frequency_guard
    if not guard:
        return {"success": False, "message": "频率守卫未初始化"}

    return {"success": True, "data": guard.get_status()}


@router.get("/guard/can-buy/{stock_code}")
async def check_can_buy(stock_code: str, container=Depends(get_container)):
    """检查指定标的是否允许买入"""
    result = {"stock_code": stock_code, "checks": []}

    # 频率检查
    guard = container.trade_frequency_guard
    if guard:
        allowed, reason = guard.can_buy(stock_code)
        result["checks"].append({
            "name": "频率管控", "passed": allowed, "reason": reason
        })

    # 阶段检查
    phase_mgr = container.trading_phase_manager
    scorer = container.stock_scorer
    stock_score = 0
    if scorer:
        cached = scorer.get_score(stock_code)
        stock_score = cached.total_score if cached else 0

    if phase_mgr:
        allowed, reason = phase_mgr.should_buy(stock_score)
        result["checks"].append({
            "name": "阶段管理", "passed": allowed, "reason": reason
        })

    # 一票否决
    if scorer:
        veto = scorer.check_intraday_veto(stock_code)
        result["checks"].append({
            "name": "一票否决", "passed": not veto, "reason": veto or "通过"
        })

    result["all_passed"] = all(c["passed"] for c in result["checks"])
    result["score"] = stock_score

    return {"success": True, "data": result}


@router.get("/rotation/status")
async def get_rotation_status(container=Depends(get_container)):
    """获取资金流换票状态"""
    rotator = container.capital_flow_rotator
    if not rotator:
        return {"success": False, "message": "换票引擎未初始化"}

    return {"success": True, "data": rotator.get_status()}


@router.get("/position/status")
async def get_position_status(container=Depends(get_container)):
    """获取智能持仓管理状态"""
    mgr = container.smart_position_manager
    if not mgr:
        return {"success": False, "message": "持仓管理器未初始化"}

    positions = mgr.get_all_positions()
    return {
        "success": True,
        "data": {
            "active_positions": len(positions),
            "positions": {code: pos.to_dict() for code, pos in positions.items()},
        }
    }


@router.get("/overview")
async def get_optimizer_overview(container=Depends(get_container)):
    """获取交易优化系统的综合状态总览"""
    overview = {"timestamp": datetime.now().isoformat()}

    # 阶段
    phase_mgr = container.trading_phase_manager
    if phase_mgr:
        overview["phase"] = phase_mgr.get_status()

    # 频率
    guard = container.trade_frequency_guard
    if guard:
        overview["guard"] = guard.get_status()

    # 评分
    scorer = container.stock_scorer
    if scorer:
        candidates = scorer.get_candidates()
        overview["scoring"] = {
            "total_scored": len(scorer._scored_cache),
            "candidates": len(candidates),
            "top3": [
                {"code": c.stock_code, "name": c.stock_name, "score": c.total_score}
                for c in candidates[:3]
            ],
        }

    # 持仓
    mgr = container.smart_position_manager
    if mgr:
        overview["positions"] = {
            "active": len(mgr.get_all_positions()),
        }

    # 换票
    rotator = container.capital_flow_rotator
    if rotator:
        overview["rotation"] = {
            "count": rotator._rotation_count,
            "max": rotator._max_rotations,
        }

    return {"success": True, "data": overview}


@router.post("/scoring/run")
async def run_pre_market_scoring(container=Depends(get_container)):
    """手动触发盘前评分"""
    try:
        # 动态导入并运行盘前评分脚本
        import importlib.util
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))),
            'scripts', 'pre_market_scoring.py'
        )

        if not os.path.exists(script_path):
            return {"success": False, "message": f"评分脚本不存在: {script_path}"}

        spec = importlib.util.spec_from_file_location("pre_market_scoring", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        scorer_instance, results = module.run_scoring()

        # 将评分结果注入到容器的scorer中
        scorer = container.stock_scorer
        if scorer and scorer_instance:
            scorer._scored_cache = scorer_instance._scored_cache
            scorer._score_date = scorer_instance._score_date

        passed = [r for r in results if r.passed]
        return {
            "success": True,
            "message": f"评分完成: {len(results)}只标的, {len(passed)}只通过",
            "data": {
                "total": len(results),
                "passed": len(passed),
                "candidates": [r.to_dict() for r in passed],
            }
        }
    except Exception as e:
        logger.error(f"盘前评分失败: {e}")
        return {"success": False, "message": f"评分失败: {str(e)}"}


@router.post("/daily-reset")
async def daily_reset(container=Depends(get_container)):
    """每日重置所有交易优化模块（盘前调用）"""
    reset_results = []

    for name, attr in [
        ("评分引擎", "stock_scorer"),
        ("频率守卫", "trade_frequency_guard"),
        ("阶段管理", "trading_phase_manager"),
        ("换票引擎", "capital_flow_rotator"),
        ("持仓管理", "smart_position_manager"),
    ]:
        service = getattr(container, attr, None)
        if service and hasattr(service, 'reset_daily'):
            try:
                service.reset_daily()
                reset_results.append({"name": name, "success": True})
            except Exception as e:
                reset_results.append({"name": name, "success": False, "error": str(e)})

    return {
        "success": all(r["success"] for r in reset_results),
        "data": reset_results,
    }
