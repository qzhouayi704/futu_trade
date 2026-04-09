#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""决策助理 API 路由"""

import asyncio
import logging
from fastapi import APIRouter, Depends

from ...dependencies import get_container
from ...schemas.common import APIResponse
from ...services.advisor.models import EvaluationContext

router = APIRouter(prefix="/api/advisor", tags=["决策助理"])
logger = logging.getLogger(__name__)


@router.get("/advices", response_model=APIResponse)
async def get_advices(container=Depends(get_container)):
    """获取当前决策建议列表"""
    advisor = container.decision_advisor
    if not advisor:
        return APIResponse(success=False, message="决策助理服务未初始化")

    advices = advisor.get_cached_advices()
    if advices:
        return APIResponse(
            success=True,
            data=[a.to_dict() for a in advices],
            message=f"获取到 {len(advices)} 条决策建议",
        )

    # 内存缓存为空时，从数据库加载最近一次评估
    db = container.db_manager
    if db:
        try:
            records = db.advisor_queries.get_latest_evaluation()
            if records:
                return APIResponse(
                    success=True,
                    data=records,
                    message=f"从数据库加载 {len(records)} 条决策建议",
                )
        except Exception as e:
            logger.warning(f"从数据库加载建议失败: {e}")

    return APIResponse(success=True, data=[], message="暂无决策建议")


@router.get("/history", response_model=APIResponse)
async def get_evaluation_history(limit: int = 10, container=Depends(get_container)):
    """获取历史评估记录"""
    advisor = container.decision_advisor
    if not advisor:
        return APIResponse(success=False, message="决策助理服务未初始化")

    history = advisor.get_evaluation_history(limit)
    return APIResponse(
        success=True,
        data=history,
        message=f"获取到 {len(history)} 条历史记录",
    )

@router.get("/health", response_model=APIResponse)
async def get_position_health(container=Depends(get_container)):
    """获取持仓健康度摘要"""
    advisor = container.decision_advisor
    if not advisor:
        return APIResponse(success=False, message="决策助理服务未初始化")

    health_list = advisor.get_health_cache()
    summary = advisor.get_summary()
    return APIResponse(
        success=True,
        data={
            "positions": [h.to_dict() for h in health_list],
            "summary": summary,
        },
        message=f"获取到 {len(health_list)} 条持仓健康度数据",
    )


@router.post("/dismiss/{advice_id}", response_model=APIResponse)
async def dismiss_advice(advice_id: str, container=Depends(get_container)):
    """忽略某条建议"""
    advisor = container.decision_advisor
    if not advisor:
        return APIResponse(success=False, message="决策助理服务未初始化")

    result = advisor.dismiss_advice(advice_id)
    return APIResponse(
        success=result,
        message="已忽略" if result else "建议不存在",
    )


async def _build_evaluation_context(container) -> EvaluationContext:
    """采集评估所需的全部数据，返回 EvaluationContext"""
    loop = asyncio.get_event_loop()

    # 获取持仓
    positions = []
    trade_svc = container.futu_trade_service
    if trade_svc:
        positions_result = await loop.run_in_executor(None, trade_svc.get_positions)
        if isinstance(positions_result, dict) and positions_result.get('success'):
            positions = positions_result.get('positions', [])
        elif isinstance(positions_result, list):
            positions = positions_result

    # 获取报价、信号
    from ...core import get_state_manager
    state = get_state_manager()
    quotes = state.get_cached_quotes() or [] if state else []
    signals = state.get_trade_signals() if state and hasattr(state, 'get_trade_signals') else []

    # 获取 K线数据（从数据库）
    kline_cache: dict = {}
    db = container.db_manager
    if db and positions:
        for pos in positions:
            code = pos.get('stock_code', pos.get('code', ''))
            if code:
                try:
                    klines = db.kline_queries.get_stock_kline(code, days=30)
                    if klines:
                        kline_cache[code] = klines
                except Exception as e:
                    logger.debug(f"获取 {code} K线数据失败: {e}")

    # 获取板块/行业信息（供 Gemini 分析）
    plate_data: dict = {}
    plate_mgr = getattr(container, 'plate_manager', None) or getattr(getattr(container, 'data', None), 'plate_manager', None)
    if plate_mgr and positions:
        for pos in positions:
            code = pos.get('stock_code', pos.get('code', ''))
            if code:
                try:
                    plates = plate_mgr.get_stock_plates(code) if hasattr(plate_mgr, 'get_stock_plates') else []
                    if plates:
                        plate_data[code] = [p.get('plate_name', p) if isinstance(p, dict) else str(p) for p in plates]
                except Exception:
                    pass

    return EvaluationContext(
        positions=positions,
        quotes=quotes,
        signals=signals,
        kline_cache=kline_cache,
        plate_data=plate_data,
    )


@router.post("/evaluate", response_model=APIResponse)
async def trigger_evaluation(container=Depends(get_container)):
    """手动触发一次决策评估"""
    try:
        advisor = container.decision_advisor
        if not advisor:
            return APIResponse(success=False, message="决策助理服务未初始化")

        ctx = await _build_evaluation_context(container)
        if not ctx.positions:
            return APIResponse(success=True, data=[], message="当前无持仓")

        loop = asyncio.get_event_loop()
        advices = await loop.run_in_executor(None, advisor.evaluate, ctx)

        # AI 增强（如果启用）
        if advisor._ai_enhanced and advices:
            try:
                advices = await advisor.enhance_with_ai(advices, ctx)
            except Exception as ai_err:
                logger.warning(f"AI 增强失败（不影响规则引擎）: {ai_err}")

        # 持久化到数据库
        advice_dicts = [a.to_dict() for a in advices]
        db = container.db_manager
        if db and advice_dicts:
            try:
                db.advisor_queries.save_evaluation(advice_dicts)
            except Exception as db_err:
                logger.warning(f"保存评估结果到数据库失败: {db_err}")

        return APIResponse(
            success=True,
            data={
                "advices": advice_dicts,
                "summary": advisor.get_summary(),
                "health": [h.to_dict() for h in advisor.get_health_cache()],
            },
            message=f"评估完成，生成 {len(advices)} 条建议",
        )
    except Exception as e:
        logger.error(f"评估失败: {e}", exc_info=True)
        return APIResponse(success=False, message=f"评估失败: {str(e)}")


@router.post("/execute/{advice_id}", response_model=APIResponse)
async def execute_advice(advice_id: str, container=Depends(get_container)):
    """一键执行某条建议"""
    advisor = container.decision_advisor
    if not advisor:
        return APIResponse(success=False, message="决策助理服务未初始化")

    advice = advisor.get_advice_by_id(advice_id)
    if not advice:
        return APIResponse(success=False, message="建议不存在或已过期")

    trade_svc = container.futu_trade_service
    if not trade_svc:
        return APIResponse(success=False, message="交易服务未初始化")

    loop = asyncio.get_event_loop()

    try:
        result = await _execute_by_type(advice, trade_svc, loop)
        # 执行后标记为已处理
        advisor.dismiss_advice(advice_id)
        return APIResponse(success=True, data=result, message="执行成功")
    except Exception as e:
        logger.error(f"执行建议失败 {advice_id}: {e}", exc_info=True)
        return APIResponse(success=False, message=f"执行失败: {str(e)}")


async def _execute_by_type(advice, trade_svc, loop) -> dict:
    """根据建议类型执行对应的交易操作"""
    from ...services.advisor.models import AdviceType

    results = {}

    # 卖出操作
    if advice.sell_stock_code and advice.advice_type in (
        AdviceType.STOP_LOSS, AdviceType.CLEAR, AdviceType.REDUCE,
        AdviceType.TAKE_PROFIT, AdviceType.SWAP,
    ):
        sell_result = await loop.run_in_executor(
            None,
            trade_svc.execute_trade,
            advice.sell_stock_code,
            "SELL",
            advice.sell_price or 0,
            0,  # 数量由 sell_ratio 决定
        )
        results['sell'] = sell_result

    # 买入操作
    if advice.buy_stock_code and advice.advice_type in (
        AdviceType.SWAP, AdviceType.ADD_POSITION,
    ):
        buy_result = await loop.run_in_executor(
            None,
            trade_svc.execute_trade,
            advice.buy_stock_code,
            "BUY",
            advice.buy_price or 0,
            advice.quantity or 0,
        )
        results['buy'] = buy_result

    return results
