#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成交分析路由 - 共享辅助函数

提供服务实例缓存、配置转换、报价查询等辅助功能
"""

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ==================== 配置转换 ====================


def get_config_dict(container) -> dict:
    """将 Config dataclass 转为字典"""
    config = container.config
    if config is None:
        return {}
    if hasattr(config, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(config)
    return {}


# ==================== 服务实例缓存 ====================

_instance_cache: dict = {}


def get_cached(container, key: str, factory):
    """从缓存获取或创建实例"""
    cache_key = (id(container), key)
    if cache_key not in _instance_cache:
        _instance_cache[cache_key] = factory()
    return _instance_cache[cache_key]


def get_ticker_service(container):
    """获取逐笔成交数据服务（缓存）

    仅在 subscription_manager 可用后才缓存实例，
    避免永久持有 subscription_manager=None 的实例。
    """
    sm = getattr(container, 'subscription_manager', None)

    def factory():
        from ....services.market_data.ticker_analysis.ticker_service import TickerService
        from ....core import get_state_manager
        return TickerService(
            futu_client=container.futu_client,
            state_manager=get_state_manager(),
            subscription_manager=sm,
            db_manager=getattr(container, 'db_manager', None),
        )

    if sm is None:
        # SM 尚未就绪，不缓存，每次重新创建（等待 SM 就绪后才固化）
        return factory()
    return get_cached(container, "ticker_service", factory)


def get_ticker_analyzer(container):
    """获取成交分析器（缓存）"""
    def factory():
        from ....services.market_data.ticker_analysis.ticker_analyzer import TickerAnalyzer
        cfg = get_config_dict(container)
        min_order_amount = cfg.get("min_order_amount", 100000)
        return TickerAnalyzer(
            ticker_service=get_ticker_service(container),
            min_order_amount=min_order_amount,
        )
    return get_cached(container, "ticker_analyzer", factory)


def get_order_book_service(container):
    """获取盘口数据服务（缓存）

    仅在 subscription_manager 可用后才缓存实例。
    """
    sm = getattr(container, 'subscription_manager', None)

    def factory():
        from ....services.market_data.order_book import OrderBookService
        return OrderBookService(
            futu_client=container.futu_client,
            subscription_manager=sm,
            market_event_sink=lambda code, data: (
                getattr(container, 'v2_runtime', None).ingest_order_book(code, data)
                if getattr(container, 'v2_runtime', None) is not None
                else None
            ),
        )

    if sm is None:
        return factory()
    return get_cached(container, "order_book_service", factory)


def get_order_book_analyzer(container):
    """获取盘口分析器（缓存）"""
    def factory():
        from ....services.market_data.order_book import OrderBookAnalyzer
        from ....services.market_data.vwap_service import VWAPService
        from ....services.analysis.flow.big_order_tracker import BigOrderTracker

        ob_svc = get_order_book_service(container)
        vwap_svc = VWAPService(futu_client=container.futu_client)
        big_order = BigOrderTracker(
            futu_client=container.futu_client,
            db_manager=container.db_manager,
            config=get_config_dict(container),
        )
        return OrderBookAnalyzer(
            order_book_service=ob_svc,
            vwap_service=vwap_svc,
            big_order_tracker=big_order,
        )
    return get_cached(container, "order_book_analyzer_for_ticker", factory)


def get_combined_analyzer(container):
    """获取综合分析器（缓存）"""
    def factory():
        from ....services.market_data.ticker_analysis.combined_analyzer import CombinedAnalyzer
        return CombinedAnalyzer(
            order_book_analyzer=get_order_book_analyzer(container),
            ticker_analyzer=get_ticker_analyzer(container),
        )
    return get_cached(container, "combined_analyzer", factory)


# ==================== 报价辅助 ====================


async def get_stock_quote(container, stock_code: str) -> dict:
    """获取单只股票的实时报价快照（带超时保护）"""
    try:
        loop = asyncio.get_event_loop()
        ret, data = await asyncio.wait_for(
            loop.run_in_executor(
                container.futu_client.executor,
                lambda: container.futu_client.get_stock_quote([stock_code]),
            ),
            timeout=8.0,
        )
        from futu import RET_OK
        if ret == RET_OK and data is not None and not data.empty:
            row = data.iloc[0]
            return {
                "last_price": float(row.get("last_price", 0) or 0),
                "cur_price": float(row.get("last_price", 0) or 0),
                "change_pct": float(row.get("change_rate", 0) or 0),
                "turnover": float(row.get("turnover", 0) or 0),
                "turnover_rate": float(row.get("turnover_rate", 0) or 0),
                "volume": int(row.get("volume", 0) or 0),
            }
    except asyncio.TimeoutError:
        logger.warning(f"获取报价超时 {stock_code}")
    except Exception as e:
        logger.warning(f"获取报价失败 {stock_code}: {e}")
    return {}


async def get_avg_daily_turnover(container, stock_code: str) -> float:
    """获取日均成交额（仅查DB缓存，不触发内联下载，带超时保护）"""
    try:
        loop = asyncio.get_event_loop()
        db = container.db_manager
        avg_turnover = await asyncio.wait_for(
            loop.run_in_executor(
                container.futu_client.executor, db.kline_queries.get_avg_daily_turnover, stock_code,
            ),
            timeout=5.0,
        )
        return avg_turnover
    except asyncio.TimeoutError:
        logger.warning(f"获取日均成交额超时 {stock_code}")
        return 0.0
    except Exception as e:
        logger.warning(f"获取日均成交额失败 {stock_code}: {e}")
        return 0.0
