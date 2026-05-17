#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金流向与大单追踪 API 路由

从 enhanced_heat.py 拆分出来，保持文件行数在 300 行以内。
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Path

from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse


router = APIRouter(prefix="/api/enhanced-heat", tags=["资金流向与大单追踪"])


# ==================== 资金流向接口 ====================

@router.get("/capital-flow/{stock_code}", response_model=APIResponse)
async def get_capital_flow(
    stock_code: str = Path(..., description="股票代码"),
    container=Depends(get_container)
):
    """获取单只股票资金流向"""
    try:
        analyzer = container.capital_analyzer
        loop = asyncio.get_event_loop()
        from ...services.analysis.flow.capital_flow_analyzer import CacheTTL
        data = await loop.run_in_executor(
            None, lambda: analyzer.fetch_capital_flow_data(
                [stock_code], use_cache=True, cache_ttl=CacheTTL.REALTIME
            )
        )

        if stock_code not in data:
            return APIResponse(
                success=True, data=None,
                message=f"{stock_code} 暂无资金流向数据"
            )

        capital = data[stock_code]
        if 'timestamp' in capital and hasattr(capital['timestamp'], 'isoformat'):
            capital['timestamp'] = capital['timestamp'].isoformat()

        return APIResponse(
            success=True, data=capital,
            message=f"获取 {stock_code} 资金流向成功"
        )
    except Exception as e:
        logging.error(f"获取资金流向失败: {stock_code}, {e}")
        raise BusinessError(f"获取资金流向失败: {str(e)}")


@router.get("/capital-flow-batch", response_model=APIResponse)
async def get_capital_flow_batch(
    codes: str = Query(..., description="股票代码列表，逗号分隔"),
    container=Depends(get_container)
):
    """批量获取资金流向"""
    try:
        stock_codes = [c.strip() for c in codes.split(",") if c.strip()]
        if not stock_codes:
            raise BusinessError("股票代码列表不能为空")
        if len(stock_codes) > 20:
            raise BusinessError("单次最多查询20只股票")

        analyzer = container.capital_analyzer
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, analyzer.fetch_capital_flow_data, stock_codes, True
        )

        for code, capital in data.items():
            if 'timestamp' in capital and hasattr(capital['timestamp'], 'isoformat'):
                capital['timestamp'] = capital['timestamp'].isoformat()

        return APIResponse(
            success=True,
            data={
                'capital_flows': data,
                'total': len(data),
                'requested': len(stock_codes)
            },
            message=f"获取 {len(data)}/{len(stock_codes)} 只股票资金流向"
        )
    except BusinessError:
        raise
    except Exception as e:
        logging.error(f"批量获取资金流向失败: {e}")
        raise BusinessError(f"批量获取资金流向失败: {str(e)}")


@router.get("/capital-flow-history/{stock_code}", response_model=APIResponse)
async def get_capital_flow_history(
    stock_code: str = Path(..., description="股票代码"),
    start: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    container=Depends(get_container)
):
    """获取历史每日资金流向"""
    try:
        analyzer = container.capital_analyzer
        loop = asyncio.get_event_loop()
        history = await loop.run_in_executor(
            None, lambda: analyzer.fetch_capital_flow_history(stock_code, start=start, end=end)
        )

        return APIResponse(
            success=True,
            data={'history': history, 'total': len(history)},
            message=f"获取 {stock_code} 历史资金流向 {len(history)} 条"
        )
    except Exception as e:
        logging.error(f"获取历史资金流向失败: {stock_code}, {e}")
        raise BusinessError(f"获取历史资金流向失败: {str(e)}")


# ==================== 大单追踪接口 ====================

@router.get("/big-orders/{stock_code}", response_model=APIResponse)
async def get_big_orders(
    stock_code: str = Path(..., description="股票代码"),
    container=Depends(get_container)
):
    """获取大单追踪数据"""
    try:
        tracker = container.big_order_tracker
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: tracker.track_rt_tickers([stock_code], top_n=1)
        )

        if stock_code not in data:
            cached = tracker.get_cached_big_order_data(stock_code)
            if cached:
                if 'timestamp' in cached and hasattr(cached['timestamp'], 'isoformat'):
                    cached['timestamp'] = cached['timestamp'].isoformat()
                return APIResponse(
                    success=True, data=cached,
                    message=f"获取 {stock_code} 大单数据成功（缓存）"
                )
            return APIResponse(
                success=True, data=None,
                message=f"{stock_code} 暂无大单数据"
            )

        big_order = data[stock_code]
        if 'timestamp' in big_order and hasattr(big_order['timestamp'], 'isoformat'):
            big_order['timestamp'] = big_order['timestamp'].isoformat()

        return APIResponse(
            success=True, data=big_order,
            message=f"获取 {stock_code} 大单数据成功"
        )
    except Exception as e:
        logging.error(f"获取大单数据失败: {stock_code}, {e}")
        raise BusinessError(f"获取大单数据失败: {str(e)}")


# ==================== 盘口深度分析接口 ====================


_order_book_analyzer_cache = None


def _get_order_book_analyzer(container):
    """获取盘口深度分析器（缓存）"""
    global _order_book_analyzer_cache
    if _order_book_analyzer_cache is None:
        from ...services.market_data.order_book import OrderBookAnalyzer
        from ...services.market_data.vwap_service import VWAPService
        from .ticker.helpers import get_order_book_service
        ob_svc = get_order_book_service(container)
        vwap_svc = VWAPService(container.futu_client)
        big_tracker = container.big_order_tracker
        _order_book_analyzer_cache = OrderBookAnalyzer(ob_svc, vwap_svc, big_tracker)
    return _order_book_analyzer_cache


def _get_market_avg_change(container) -> float:
    """从 state_manager 获取市场平均涨幅"""
    try:
        from ...core import get_state_manager
        state = get_state_manager()
        quotes = state.get_cached_quotes() or []
        if not quotes:
            return 0.0
        changes = [q.get('change_rate', 0) or q.get('change_pct', 0) or 0 for q in quotes]
        return sum(changes) / len(changes) if changes else 0.0
    except Exception:
        return 0.0


def _get_stock_quote(container, stock_code: str) -> dict:
    """从 state_manager 获取单只股票的实时报价，缓存为空时 fallback 到 API"""
    quote = {}
    try:
        from ...core import get_state_manager
        state = get_state_manager()
        quotes = state.get_cached_quotes() or []
        for q in quotes:
            code = q.get('code', '') or q.get('stock_code', '')
            if code == stock_code:
                quote = q
                break
    except Exception:
        pass

    # 缓存为空时，fallback 到 realtime_query API
    if not quote:
        try:
            rq = container.realtime_query
            result = rq.get_realtime_quotes([stock_code])
            if result.get('success') and result.get('quotes'):
                quote = result['quotes'][0]
        except Exception as e:
            logging.warning(f"fallback 获取报价失败 {stock_code}: {e}")

    # 确保 change_rate 字段存在（量价分析依赖此字段）
    if quote and 'change_rate' not in quote:
        quote['change_rate'] = (
            quote.get('change_percent', 0)
            or quote.get('change_pct', 0)
            or 0
        )

    return quote

async def _enrich_quote_with_kline(container, stock_code: str, quote: dict) -> dict:
    """用 K 线历史数据补充 volume_ratio 和 price_position 到 quote 中

    - volume_ratio: 当日成交量 / 近5日平均成交量
    - price_position: 当前价在近20日高低范围中的百分位 (0~100)
    """
    if not quote:
        return quote

    loop = asyncio.get_event_loop()
    db = container.db_manager

    try:
        klines = await loop.run_in_executor(
            None, db.kline_queries.get_stock_kline, stock_code, 20,
        )
    except Exception as e:
        logging.warning(f"获取K线数据失败 {stock_code}: {e}")
        return quote

    if not klines:
        return quote

    # 计算 volume_ratio（量比）: 当日成交量 / 近5日平均成交量
    recent_volumes = [k.get('volume', 0) for k in klines[-5:]]
    avg_vol = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
    current_vol = quote.get('volume', 0) or 0
    if avg_vol > 0 and current_vol > 0:
        quote['volume_ratio'] = round(current_vol / avg_vol, 2)
    else:
        quote['volume_ratio'] = 1.0

    # 计算 price_position: 当前价在近20日高低范围中的位置 (0~100)
    highs = [k.get('high', 0) or k.get('high_price', 0) for k in klines]
    lows = [k.get('low', 0) or k.get('low_price', 0) for k in klines]
    highs = [h for h in highs if h > 0]
    lows = [l for l in lows if l > 0]

    if highs and lows:
        period_high = max(highs)
        period_low = min(lows)
        current_price = quote.get('last_price', 0) or quote.get('cur_price', 0) or 0
        if period_high > period_low and current_price > 0:
            quote['price_position'] = round(
                (current_price - period_low) / (period_high - period_low) * 100, 1
            )

    return quote



@router.get("/order-book/{stock_code}", response_model=APIResponse)
async def get_order_book_analysis(
    stock_code: str = Path(..., description="股票代码"),
    container=Depends(get_container)
):
    """获取盘口深度分析（买卖十档 + 5维度涨跌动力分析）"""
    try:
        analyzer = _get_order_book_analyzer(container)
        quote = _get_stock_quote(container, stock_code)
        quote = await _enrich_quote_with_kline(container, stock_code, quote)
        market_avg = _get_market_avg_change(container)

        result = await analyzer.analyze(stock_code, quote, market_avg)

        if result is None:
            return APIResponse(
                success=True, data=None,
                message=f"{stock_code} 暂无盘口数据"
            )

        return APIResponse(
            success=True,
            data={
                'stock_code': result.stock_code,
                'order_book': result.order_book_raw,
                'dimensions': [
                    {
                        'name': d.name,
                        'signal': d.signal,
                        'score': d.score,
                        'description': d.description,
                        'details': d.details,
                    }
                    for d in result.dimensions
                ],
                'total_score': result.total_score,
                'signal': result.signal,
                'label': result.label,
                'summary': result.summary,
            },
            message=f"获取 {stock_code} 盘口深度分析成功"
        )
    except Exception as e:
        logging.error(f"获取盘口分析失败: {stock_code}, {e}")
        raise BusinessError(f"获取盘口分析失败: {str(e)}")
