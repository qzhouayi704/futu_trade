#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 路由模块

按业务领域组织为子目录：
- market/: 行情相关（quote, kline, plate）
- trading/: 交易相关（trade, position_order, take_profit, strategy）
- data/: 数据管理（stock, analysis, hot_stock, enhanced_heat）
- system/: 系统管理（config, system, monitor, news）
- compat/: 兼容路由接口
"""

from fastapi import FastAPI

# system/ - 系统管理
from .system.system import router as system_router
from .system.monitor import router as monitor_router
from .system.config import router as config_router
from .system.news import router as news_router
from .system.monitoring_routes import router as monitoring_routes_router

# market/ - 行情相关
from .market.quote import router as quote_router
from .market.kline import router as kline_router
from .market.plate import router as plate_router

# trading/ - 交易相关
from .trading.trade_execution import router as trade_execution_router
from .trading.trade_monitoring import router as trade_monitoring_router
from .trading.strategy_management import router as strategy_management_router
from .trading.strategy_screening import router as strategy_screening_router
from .trading.strategy_multi import router as strategy_multi_router
from .trading.take_profit import router as take_profit_router
from .trading.position_order import router as position_order_router
from .trading.advisor import router as advisor_router
from .trading.scalping import router as scalping_router

# data/ - 数据管理
from .data.stock import router as stock_router
from .data.analysis import router as analysis_router
from .data.hot_stock import router as hot_stock_router
from .data.enhanced_heat import router as enhanced_heat_router
from .data.enhanced_heat_summary import router as enhanced_heat_summary_router
from .data.capital_and_orders import router as capital_and_orders_router
from .data.activity_refilter import router as activity_refilter_router
from .data.high_turnover import router as high_turnover_router
from .data.ticker import router as ticker_analysis_router

# compat/ - 兼容路由
from .compat import router as compat_router


def register_routers(app: FastAPI) -> None:
    """注册所有路由到 FastAPI 应用"""
    # 系统管理
    app.include_router(system_router)
    app.include_router(monitor_router)
    app.include_router(config_router)
    app.include_router(news_router)
    app.include_router(monitoring_routes_router)

    # 行情相关
    app.include_router(quote_router)
    app.include_router(kline_router)
    app.include_router(plate_router)

    # 交易相关
    app.include_router(trade_execution_router)
    app.include_router(trade_monitoring_router)
    app.include_router(strategy_management_router)
    app.include_router(strategy_screening_router)
    app.include_router(strategy_multi_router)
    app.include_router(take_profit_router)
    app.include_router(position_order_router)
    app.include_router(advisor_router)
    app.include_router(scalping_router)

    # 数据管理
    app.include_router(stock_router)
    app.include_router(analysis_router)
    app.include_router(hot_stock_router)
    app.include_router(enhanced_heat_router)
    app.include_router(enhanced_heat_summary_router)
    app.include_router(capital_and_orders_router)
    app.include_router(activity_refilter_router)
    app.include_router(high_turnover_router)
    app.include_router(ticker_analysis_router)

    # 兼容路由
    app.include_router(compat_router)
