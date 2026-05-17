#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘口分析路由

提供综合多空分析（挂单+成交）和盘口深度数据接口
"""

import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends

from ....core.exceptions import BusinessError
from ....dependencies import get_container
from ....schemas.common import APIResponse
from .helpers import (
    get_combined_analyzer,
    get_order_book_service,
    get_stock_quote,
    get_avg_daily_turnover,
    get_ticker_service,
)

router = APIRouter(prefix="/api/enhanced-heat", tags=["盘口分析"])
logger = logging.getLogger(__name__)


@router.get("/combined-analysis/{stock_code}", response_model=APIResponse)
async def get_combined_analysis(
    stock_code: str,
    container=Depends(get_container),
):
    """获取综合多空分析结果（挂单 + 成交，支持临时订阅）"""
    try:
        # 临时订阅股票（如果未订阅）
        subscription_helper = container.subscription_helper
        sub_result = subscription_helper.subscribe_for_analysis(stock_code)

        if not sub_result['success']:
            return APIResponse(
                success=False,
                data=None,
                message=f"订阅失败: {sub_result['message']}",
            )

        analyzer = get_combined_analyzer(container)
        quote = await get_stock_quote(container, stock_code)
        avg_turnover = await get_avg_daily_turnover(container, stock_code)
        result = await analyzer.analyze(
            stock_code, quote=quote, avg_daily_turnover=avg_turnover,
        )

        if result is None:
            return APIResponse(
                success=True,
                data=None,
                message="盘口数据不可用，无法进行综合分析",
            )

        msg = f"获取 {stock_code} 综合分析成功"
        if not result.ticker_available:
            msg = f"获取 {stock_code} 综合分析成功（成交数据暂不可用，已降级为仅挂单分析）"

        # 添加订阅信息到响应
        response_data = asdict(result)
        response_data['subscription_info'] = {
            'replaced': sub_result.get('replaced'),
            'is_temporary': sub_result.get('replaced') is not None
        }

        return APIResponse(
            success=True,
            data=response_data,
            message=msg,
        )
    except Exception as e:
        logger.error(f"获取综合分析失败 {stock_code}: {e}")
        raise BusinessError(f"获取综合分析失败: {str(e)}")


@router.get("/order-book/{stock_code}", response_model=APIResponse)
async def get_order_book(
    stock_code: str,
    container=Depends(get_container),
):
    """获取盘口10档深度数据"""
    try:
        ob_service = get_order_book_service(container)
        order_book = await ob_service.get_order_book(stock_code)

        if order_book is None:
            return APIResponse(
                success=True,
                data=None,
                message="盘口数据暂不可用",
            )

        # 获取支撑阻力位
        sr = ob_service.get_support_resistance(order_book)

        data = {
            "stock_code": order_book.stock_code,
            "bid_levels": [
                {"price": l.price, "volume": l.volume, "order_count": l.order_count}
                for l in order_book.bid_levels
            ],
            "ask_levels": [
                {"price": l.price, "volume": l.volume, "order_count": l.order_count}
                for l in order_book.ask_levels
            ],
            "bid_total_volume": order_book.bid_total_volume,
            "ask_total_volume": order_book.ask_total_volume,
            "imbalance": order_book.imbalance,
            "spread": order_book.spread,
            "spread_pct": order_book.spread_pct,
            "support": sr.get("support"),
            "resistance": sr.get("resistance"),
        }

        return APIResponse(
            success=True,
            data=data,
            message=f"获取 {stock_code} 盘口数据成功",
        )
    except Exception as e:
        logger.error(f"获取盘口数据失败 {stock_code}: {e}")
        raise BusinessError(f"获取盘口数据失败: {str(e)}")


@router.get("/intraday-levels/{stock_code}", response_model=APIResponse)
async def get_intraday_levels(
    stock_code: str,
    container=Depends(get_container),
):
    """获取日内资金支撑/阻力位（融合成交量聚集+大单+盘口）"""
    try:
        # 临时订阅（如果未订阅）
        subscription_helper = container.subscription_helper
        sub_result = subscription_helper.subscribe_for_analysis(stock_code)

        if not sub_result['success']:
            return APIResponse(
                success=False,
                data=None,
                message=f"订阅失败: {sub_result['message']}",
            )

        from ....services.analysis.intraday_levels_service import IntradayLevelsService

        ticker_svc = get_ticker_service(container)
        ob_svc = get_order_book_service(container)
        service = IntradayLevelsService(
            ticker_service=ticker_svc,
            order_book_service=ob_svc,
        )

        result = await service.get_levels(stock_code)
        data = result.to_dict()

        # === 附加经纪商席位分析 ===
        try:
            futu_client = getattr(container, 'futu_client', None)
            if futu_client and result.current_price > 0:
                from ....services.analysis.flow.broker_consistency_filter import BrokerConsistencyFilter
                # 获取实际涨跌幅
                change_pct = 0.0
                try:
                    quote_cache = getattr(container, 'quote_cache', None)
                    if quote_cache:
                        quotes_map = quote_cache.get_quotes_for_codes([stock_code])
                        cached = quotes_map.get(stock_code)
                        if cached:
                            change_pct = abs(float(cached.get('change_rate', 0)))
                except Exception:
                    pass
                bf = BrokerConsistencyFilter(futu_client)
                broker_result = bf.check_distribution_trap(stock_code, change_pct=change_pct)
                data['broker_analysis'] = {
                    'is_trap': broker_result.is_trap,
                    'trap_confidence': broker_result.trap_confidence,
                    'reason': broker_result.reason,
                    'top_buyers': broker_result.top_buyers[:5],
                    'top_sellers': broker_result.top_sellers[:5],
                    'buyer_details': broker_result.buyer_details,
                    'seller_details': broker_result.seller_details,
                    'institutional_sell_count': broker_result.institutional_sell_count,
                    'retail_buy_count': broker_result.retail_buy_count,
                }
        except Exception as e:
            logger.debug(f"经纪商分析附加失败: {e}")

        return APIResponse(
            success=True,
            data=data,
            message=f"获取 {stock_code} 日内支撑/阻力位成功",
        )
    except Exception as e:
        logger.error(f"获取日内支撑/阻力位失败 {stock_code}: {e}")
        raise BusinessError(f"获取日内支撑/阻力位失败: {str(e)}")


logger.info("盘口分析路由已注册")
