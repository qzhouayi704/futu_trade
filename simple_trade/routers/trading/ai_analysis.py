#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 股票分析 API 路由

提供独立的 AI 分析 endpoint，供选股工作台和交易决策中心使用。
"""

import asyncio
import logging
from fastapi import APIRouter, Depends, Query

from ...dependencies import get_container
from ...schemas.common import APIResponse

router = APIRouter(prefix="/api/ai-analysis", tags=["AI分析"])
logger = logging.getLogger(__name__)


@router.post("/analyze", response_model=APIResponse)
async def analyze_stock(
    stock_code: str = Query(..., description="股票代码"),
    container=Depends(get_container),
):
    """对单只股票执行 AI 分析

    从系统获取该股票的实时行情、K线数据、评分等信息，
    连同规则知识库发送给 Gemini 进行分析。
    """
    analyzer = container.stock_ai_analyzer
    if not analyzer or not analyzer.is_available():
        return APIResponse(
            success=False,
            message="AI 分析服务不可用���请检查 Gemini API Key 配置）",
        )

    try:
        # 1. 获取实时行情
        logger.info(f"[AI分析API] 收到分析请求: {stock_code}")
        quote = _get_stock_quote(container, stock_code)
        if not quote:
            return APIResponse(
                success=False,
                message=f"无法获取 {stock_code} 的实时行情",
            )

        stock_name = quote.get('name', quote.get('stock_name', stock_code))

        # 2. 获取 K线数据
        klines = _get_kline_data(container, stock_code)

        # 3. 获取评分结果（如果有缓存）
        score_result = _get_score_result(container, stock_code, quote, klines)

        # 4. 获取板块信息
        plate_info = _get_plate_info(container, stock_code)

        # 5. 获取持仓信息（如果是持仓股票）
        position_info = _get_position_info(container, stock_code)

        logger.info(
            f"[AI分析API] {stock_code} 数据聚合完成 | "
            f"行情: {'\u2713' if quote else '\u2717'} | "
            f"K线: {len(klines) if klines else 0}条 | "
            f"板块: {'\u2713' if plate_info else '\u2717'} | "
            f"持仓: {'\u2713' if position_info else '\u2717'}"
        )

        # 6. 执行 AI 分析
        result = await analyzer.analyze_stock(
            stock_code=stock_code,
            stock_name=stock_name,
            quote=quote,
            klines=klines,
            score_result=score_result,
            plate_info=plate_info,
            position_info=position_info,
        )

        if result.get('success'):
            return APIResponse(
                success=True,
                data=result.get('data'),
                message=f"AI 分析完成{'（缓存）' if result.get('from_cache') else ''}",
            )
        else:
            return APIResponse(
                success=False,
                message=result.get('error', 'AI 分析失败'),
            )

    except Exception as e:
        logger.error(f"AI 分析接口异常 {stock_code}: {e}", exc_info=True)
        return APIResponse(success=False, message=f"分析异常: {str(e)}")


@router.delete("/cache", response_model=APIResponse)
async def clear_cache(
    stock_code: str = Query(None, description="股票代码（空则清除全部）"),
    container=Depends(get_container),
):
    """\u6e05\u9664 AI \u5206\u6790\u7f13\u5b58"""
    analyzer = container.stock_ai_analyzer
    if analyzer:
        analyzer.clear_cache(stock_code)
    target = stock_code or "\u5168\u90e8"
    logger.info(f"[AI\u5206\u6790API] \u7f13\u5b58\u5df2\u6e05\u9664: {target}")
    return APIResponse(success=True, message="\u7f13\u5b58\u5df2\u6e05\u9664")


# ==================== 辅助函数 ====================

def _get_stock_quote(container, stock_code: str) -> dict:
    """从缓存或实时查询获取股票行情"""
    # 优先从缓存获取
    from ...core import get_state_manager
    state = get_state_manager()
    if state:
        quotes = state.get_cached_quotes() or []
        for q in quotes:
            if q.get('code', '') == stock_code:
                return q

    # 缓存没有，尝试实时查询
    realtime = getattr(container, 'realtime_query', None) or \
               getattr(getattr(container, 'data', None), 'realtime_query', None)
    if realtime:
        try:
            result = realtime.get_realtime_quotes([stock_code])
            if result.get('success') and result.get('quotes'):
                return result['quotes'][0]
        except Exception as e:
            logger.warning(f"实时查询 {stock_code} 行情失败: {e}")

    return {}


def _get_kline_data(container, stock_code: str) -> list:
    """从数据库获取K线数据"""
    db = container.db_manager
    if not db:
        return []
    try:
        klines = db.kline_queries.get_stock_kline(stock_code, days=30)
        return klines or []
    except Exception as e:
        logger.debug(f"获取 {stock_code} K线数据失败: {e}")
        return []


def _get_score_result(container, stock_code: str, quote: dict, klines: list) -> dict:
    """使用 StockScorer 计算评分结果"""
    scorer = getattr(container, 'stock_scorer', None)
    if not scorer or not quote:
        return {}
    try:
        indicators = _compute_scoring_indicators(quote, klines)
        if not indicators:
            return {}
        stock_name = quote.get('name', quote.get('stock_name', stock_code))
        result = scorer.score_stock(stock_code, stock_name, indicators)
        return result.to_dict()
    except Exception as e:
        logger.debug(f"计算 {stock_code} 评分失败: {e}")
        return {}


def _compute_scoring_indicators(quote: dict, klines: list) -> dict:
    """从行情和K线数据计算评分所需指标

    对齐 TrendReversalStrategy 的6个买入条件：
    - 条件②距高点跌幅 → kline_pos_20d
    - 条件③距低点反弹 → rise_from_low (新增)
    - 条件④今日阳线   → today_change (新增)
    - 条件⑤反弹放量   → vol_ratio
    """
    indicators = {}

    # 日振幅
    high = quote.get('high_price', 0)
    low = quote.get('low_price', 0)
    prev_close = quote.get('prev_close_price', quote.get('last_close_price', 0))
    if prev_close > 0 and high > 0 and low > 0:
        indicators['day_amplitude'] = (high - low) / prev_close * 100

    # 量比
    indicators['vol_ratio'] = quote.get('volume_ratio', None)

    # 资金流净比率
    indicators['flow_ratio'] = quote.get('net_inflow_ratio', None)

    # 今日涨跌幅 (对齐TrendReversal条件④: 今日阳线反转)
    last_price = quote.get('last_price', 0)
    if prev_close > 0 and last_price > 0:
        indicators['today_change'] = (last_price - prev_close) / prev_close * 100

    # 从 K 线计算趋势指标
    if klines and len(klines) >= 2:
        closes = [k.get('close', 0) for k in klines if k.get('close', 0) > 0]

        # 前日涨幅
        if len(closes) >= 2:
            indicators['prev_day_change'] = (closes[-1] - closes[-2]) / closes[-2] * 100

        # 5日累计涨幅
        if len(closes) >= 6:
            indicators['change_5d'] = (closes[-1] - closes[-6]) / closes[-6] * 100

        # K线20日位置
        if len(klines) >= 10:
            recent = klines[-20:] if len(klines) >= 20 else klines
            highs = [k.get('high', 0) for k in recent]
            lows = [k.get('low', 0) for k in recent]
            max_h = max(highs) if highs else 0
            min_l = min(lows) if lows else 0
            price = last_price or (closes[-1] if closes else 0)
            if max_h > min_l and price > 0:
                indicators['kline_pos_20d'] = (price - min_l) / (max_h - min_l)

        # 距近10日最低点反弹幅度 (对齐TrendReversal条件③: rise_from_low≥2%)
        if len(klines) >= 3:
            lookback = klines[-10:] if len(klines) >= 10 else klines
            recent_lows = [k.get('low', 0) for k in lookback if k.get('low', 0) > 0]
            if recent_lows:
                period_low = min(recent_lows)
                price = last_price or (closes[-1] if closes else 0)
                if period_low > 0 and price > 0:
                    indicators['rise_from_low'] = (price - period_low) / period_low * 100

    return indicators


def _get_plate_info(container, stock_code: str) -> str:
    """获取板块信息"""
    plate_mgr = getattr(container, 'plate_manager', None) or \
                getattr(getattr(container, 'data', None), 'plate_manager', None)
    if not plate_mgr:
        return ""
    try:
        if hasattr(plate_mgr, 'get_stock_plates'):
            plates = plate_mgr.get_stock_plates(stock_code)
            if plates:
                names = [
                    p.get('plate_name', p) if isinstance(p, dict) else str(p)
                    for p in plates
                ]
                return f"所属板块: {', '.join(names)}"
    except Exception:
        pass
    return ""


def _get_position_info(container, stock_code: str) -> dict:
    """获取持仓信息（如果是持仓股票）"""
    trade_svc = container.futu_trade_service
    if not trade_svc:
        return {}
    try:
        positions_result = trade_svc.get_positions()
        positions = []
        if isinstance(positions_result, dict) and positions_result.get('success'):
            positions = positions_result.get('positions', [])
        elif isinstance(positions_result, list):
            positions = positions_result

        for pos in positions:
            code = pos.get('stock_code', pos.get('code', ''))
            if code == stock_code:
                return pos
    except Exception as e:
        logger.debug(f"获取 {stock_code} 持仓信息失败: {e}")
    return {}
