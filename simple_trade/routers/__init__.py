#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 路由模块

按业务领域组织为子目录：
- market/: 行情相关（quote, kline, plate）
- trading/: 交易相关（trade, position_order, take_profit, strategy）
- data/: 数据管理（stock, analysis, hot_stock, enhanced_heat）
- system/: 系统管理（config, system, monitor, news）
"""

from fastapi import FastAPI
import logging

# system/ - 系统管理
from .system.system import router as system_router
from .system.monitor import router as monitor_router
from .system.config import router as config_router
from .system.news import router as news_router
from .system.monitoring_routes import router as monitoring_routes_router
from .system.global_monitoring import router as global_monitoring_router
from .system.monitoring import router as monitoring_unified_router

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
from .trading.trade_optimizer import router as trade_optimizer_router
from .trading.pre_trade_check import router as pre_trade_check_router
from .trading.entry_timing import router as entry_timing_router
from .trading.exit_plan import router as exit_plan_router
from .trading.t_trade import router as t_trade_router
from .trading.trade_pattern import router as trade_pattern_router
from .trading.ai_analysis import router as ai_analysis_router
from .trading.sniper import router as sniper_router
from .trading.signals import router as signals_router
from .trading.capital_board import router as capital_board_router

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
from .data.flow_signal import router as flow_signal_router
from .data.quick_scan import router as quick_scan_router
from .data.overnight import router as overnight_screen_router
from .data.stock_insight import router as stock_insight_router
from .data.resistance_breakout import router as resistance_breakout_router
from .data.stock_detail_composite import router as stock_detail_composite_router
from .data.momentum import router as momentum_router
from .data.watchlist import router as watchlist_router



def register_routers(app: FastAPI) -> None:
    """注册所有路由到 FastAPI 应用"""
    from ..config.config import ConfigManager
    config = ConfigManager.load_config()

    # 系统管理
    app.include_router(system_router)
    app.include_router(monitor_router)
    app.include_router(config_router)
    app.include_router(news_router)
    app.include_router(monitoring_routes_router)
    app.include_router(global_monitoring_router)
    app.include_router(monitoring_unified_router)  # 统一 /api/monitoring/*（旧前缀仍保留转发）

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
    app.include_router(trade_optimizer_router)
    app.include_router(pre_trade_check_router)
    app.include_router(entry_timing_router)
    app.include_router(exit_plan_router)
    app.include_router(t_trade_router)
    app.include_router(trade_pattern_router)
    app.include_router(ai_analysis_router)
    app.include_router(sniper_router)
    app.include_router(signals_router)
    app.include_router(capital_board_router)

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
    app.include_router(flow_signal_router)
    app.include_router(quick_scan_router)
    app.include_router(overnight_screen_router)
    app.include_router(stock_insight_router)
    app.include_router(resistance_breakout_router)
    app.include_router(stock_detail_composite_router)
    app.include_router(momentum_router)
    app.include_router(watchlist_router)
