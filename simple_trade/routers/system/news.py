#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻管理路由 - FastAPI Router

迁移自 routes/news_routes.py
包含新闻查询、情感分析、热门股票/板块、投资建议等接口
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Path, Body
from pydantic import BaseModel, Field

from ...core.exceptions import BusinessError, ValidationError
from ...dependencies import get_container
from ...schemas.common import APIResponse


router = APIRouter(prefix="/api/news", tags=["新闻管理"])


# ==================== Pydantic Models ====================

class TriggerCrawlRequest(BaseModel):
    """触发抓取请求"""
    max_items: int = Field(50, ge=1, le=200, description="最大抓取数量")
    debug: bool = Field(False, description="调试模式：显示浏览器窗口")


# ==================== Helper Functions ====================

def _get_news_service(container):
    """获取新闻服务实例（懒加载）"""
    if not hasattr(container, 'news_service') or container.news_service is None:
        from ...services.news import NewsService
        from dataclasses import asdict
        # 传递配置给 NewsService（转换为字典）
        config = container.config if hasattr(container, 'config') else None
        config_dict = asdict(config) if config else {}
        container.news_service = NewsService(container.db_manager, config=config_dict)

    return container.news_service


# ==================== 新闻查询接口 ====================

@router.get("/latest", response_model=APIResponse)
async def get_latest_news(
    limit: int = Query(20, ge=1, le=200, description="返回数量限制"),
    hours: int = Query(0, ge=0, le=720, description="时间范围(小时)，0表示不过滤"),
    container=Depends(get_container)
):
    """获取最新新闻"""
    news_service = _get_news_service(container)
    news_list = news_service.get_latest_news(limit, hours)

    return APIResponse(
        success=True,
        data={
            'news': news_list,
            'total': len(news_list)
        },
        message=f"获取到 {len(news_list)} 条新闻"
    )


@router.get("/stock/{stock_code}", response_model=APIResponse)
async def get_news_by_stock(
    stock_code: str = Path(..., description="股票代码"),
    limit: int = Query(10, ge=1, le=200, description="返回数量限制"),
    container=Depends(get_container)
):
    """获取股票相关新闻"""
    news_service = _get_news_service(container)
    news_list = news_service.get_news_by_stock(stock_code, limit)

    return APIResponse(
        success=True,
        data={
            'news': news_list,
            'stock_code': stock_code
        },
        message=f"获取到 {len(news_list)} 条相关新闻"
    )


@router.get("/sentiment/{sentiment}", response_model=APIResponse)
async def get_news_by_sentiment(
    sentiment: str = Path(..., description="情感类型(positive/negative/neutral)"),
    limit: int = Query(20, ge=1, le=200, description="返回数量限制"),
    container=Depends(get_container)
):
    """按情感获取新闻"""
    # 验证情感类型
    if sentiment not in ['positive', 'negative', 'neutral']:
        raise ValidationError("无效的情感类型，可选: positive, negative, neutral")

    news_service = _get_news_service(container)
    news_list = news_service.get_news_by_sentiment(sentiment, limit)

    sentiment_names = {
        'positive': '利好',
        'negative': '利空',
        'neutral': '中性'
    }

    return APIResponse(
        success=True,
        data={
            'news': news_list,
            'sentiment': sentiment
        },
        message=f"获取到 {len(news_list)} 条{sentiment_names[sentiment]}新闻"
    )


# ==================== 热门分析接口 ====================

@router.get("/hot-stocks", response_model=APIResponse)
async def get_hot_stocks_from_news(
    hours: int = Query(24, ge=1, le=168, description="时间范围(小时)"),
    limit: int = Query(10, ge=1, le=100, description="返回数量限制"),
    container=Depends(get_container)
):
    """获取新闻热门股票"""
    news_service = _get_news_service(container)
    stocks = news_service.get_hot_stocks_from_news(hours, limit)

    return APIResponse(
        success=True,
        data={
            'stocks': stocks,
            'hours': hours
        },
        message=f"获取到 {len(stocks)} 只热门股票"
    )


@router.get("/hot-plates", response_model=APIResponse)
async def get_hot_plates_from_news(
    hours: int = Query(24, ge=1, le=168, description="时间范围(小时)"),
    limit: int = Query(10, ge=1, le=100, description="返回数量限制"),
    container=Depends(get_container)
):
    """获取新闻热门板块"""
    news_service = _get_news_service(container)
    plates = news_service.get_hot_plates_from_news(hours, limit)

    return APIResponse(
        success=True,
        data={
            'plates': plates,
            'hours': hours
        },
        message=f"获取到 {len(plates)} 个热门板块"
    )


@router.get("/suggestions", response_model=APIResponse)
async def get_investment_suggestions(
    limit: int = Query(5, ge=1, le=20, description="返回数量限制"),
    hours: int = Query(24, ge=1, le=720, description="时间范围(小时)"),
    container=Depends(get_container)
):
    """获取投资建议"""
    news_service = _get_news_service(container)
    suggestions = news_service.get_investment_suggestions(limit, hours)

    return APIResponse(
        success=True,
        data=suggestions,
        message="获取投资建议成功"
    )


# ==================== 新闻抓取接口 ====================

@router.post("/crawl", response_model=APIResponse)
async def trigger_crawl(
    request: TriggerCrawlRequest = Body(...),
    container=Depends(get_container)
):
    """手动触发新闻抓取"""
    # 如果是调试模式，临时创建调试版服务
    if request.debug:
        from ...services.news import NewsService
        from dataclasses import asdict
        config = asdict(container.config) if hasattr(container, 'config') else {}
        debug_service = NewsService(container.db_manager, config=config, debug=True)
        result = await debug_service.crawl_and_analyze(request.max_items)
    else:
        news_service = _get_news_service(container)
        result = await news_service.crawl_and_analyze(request.max_items)

    if not result.get('success', False):
        raise BusinessError(result.get('message', '抓取失败'))

    return APIResponse(
        success=True,
        data=result,
        message=f"抓取完成，新增 {result.get('new_count', 0)} 条新闻"
    )


@router.get("/status", response_model=APIResponse)
async def get_news_status(container=Depends(get_container)):
    """获取新闻服务状态"""
    news_service = _get_news_service(container)
    status = news_service.get_status()

    return APIResponse(
        success=True,
        data=status,
        message="获取状态成功"
    )


@router.post("/reanalyze", response_model=APIResponse)
async def reanalyze_news(
    limit: int = Query(50, ge=1, le=500, description="最大分析数量"),
    batch_size: int = Query(50, ge=1, le=50, description="每批发送给Gemini的新闻数量"),
    container=Depends(get_container)
):
    """重新分析缺少关联数据的新闻（支持批量Gemini请求）"""
    news_service = _get_news_service(container)
    result = await news_service.reanalyze_news(limit, batch_size)

    if not result.get('success', False):
        raise BusinessError(result.get('message', '重新分析失败'))

    return APIResponse(
        success=True,
        data=result,
        message=f"分析完成，处理了 {result.get('analyzed', 0)} 条新闻"
    )


logging.info("新闻管理路由已注册")
