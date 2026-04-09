#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库架构定义 - 表结构和索引（协调器）

注意：此文件已重构为协调器，实际表定义已拆分到：
- base_tables.py: 基础表（股票、板块、K线）
- business_tables.py: 业务表（交易、新闻、止盈等）
"""

from .base_tables import BaseTables
from .business_tables import BusinessTables


class DatabaseSchema(BaseTables, BusinessTables):
    """数据库表结构定义（组合基础表和业务表）"""

    # 创建索引
    INDEXES = [
        # === 股票表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_stocks_code ON stocks(code)',
        'CREATE INDEX IF NOT EXISTS idx_stocks_market ON stocks(market)',
        'CREATE INDEX IF NOT EXISTS idx_stocks_priority ON stocks(stock_priority DESC)',
        'CREATE INDEX IF NOT EXISTS idx_stocks_heat_score ON stocks(heat_score DESC)',
        'CREATE INDEX IF NOT EXISTS idx_stocks_low_activity ON stocks(is_low_activity)',

        # === 板块表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_plates_code ON plates(plate_code)',
        'CREATE INDEX IF NOT EXISTS idx_plates_market ON plates(market)',
        'CREATE INDEX IF NOT EXISTS idx_plates_target ON plates(is_target)',
        'CREATE INDEX IF NOT EXISTS idx_plates_enabled ON plates(is_enabled)',
        'CREATE INDEX IF NOT EXISTS idx_plates_target_enabled ON plates(is_target, is_enabled)',
        'CREATE INDEX IF NOT EXISTS idx_plates_priority ON plates(priority DESC)',

        # === 股票-板块关联表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_stock_plates_stock ON stock_plates(stock_id)',
        'CREATE INDEX IF NOT EXISTS idx_stock_plates_plate ON stock_plates(plate_id)',

        # === K线数据表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_kline_code ON kline_data(stock_code)',
        'CREATE INDEX IF NOT EXISTS idx_kline_time ON kline_data(time_key)',
        'CREATE INDEX IF NOT EXISTS idx_kline_code_time ON kline_data(stock_code, time_key DESC)',

        # === 5分钟K线数据表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_kline_5min_code ON kline_5min_data(stock_code)',
        'CREATE INDEX IF NOT EXISTS idx_kline_5min_time ON kline_5min_data(time_key)',
        'CREATE INDEX IF NOT EXISTS idx_kline_5min_code_time ON kline_5min_data(stock_code, time_key DESC)',

        # === 交易信号表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_signals_created ON trade_signals(created_at DESC)',
        'CREATE INDEX IF NOT EXISTS idx_signals_stock_time ON trade_signals(stock_id, created_at DESC)',
        'CREATE INDEX IF NOT EXISTS idx_signals_type ON trade_signals(signal_type)',
        'CREATE INDEX IF NOT EXISTS idx_signals_strategy ON trade_signals(strategy_id)',

        # === 板块匹配日志索引 ===
        'CREATE INDEX IF NOT EXISTS idx_match_log_plate ON plate_match_log(plate_code)',
        'CREATE INDEX IF NOT EXISTS idx_match_log_matched ON plate_match_log(matched)',

        # === 交易记录表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_trading_records_code ON trading_records(stock_code)',
        'CREATE INDEX IF NOT EXISTS idx_trading_records_time ON trading_records(trade_time DESC)',
        'CREATE INDEX IF NOT EXISTS idx_trading_records_code_time ON trading_records(stock_code, trade_time DESC)',

        # === 每日活跃股票表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_daily_active_date_active ON daily_active_stocks(check_date, is_active)',
        'CREATE INDEX IF NOT EXISTS idx_daily_active_market ON daily_active_stocks(check_date, market, is_active)',

        # === 新闻表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_news_publish_time ON news(publish_time DESC)',
        'CREATE INDEX IF NOT EXISTS idx_news_sentiment ON news(sentiment)',
        'CREATE INDEX IF NOT EXISTS idx_news_created ON news(created_at DESC)',

        # === 新闻-股票关联表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_news_stocks_news ON news_stocks(news_id)',
        'CREATE INDEX IF NOT EXISTS idx_news_stocks_stock ON news_stocks(stock_code)',

        # === 新闻-板块关联表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_news_plates_news ON news_plates(news_id)',
        'CREATE INDEX IF NOT EXISTS idx_news_plates_plate ON news_plates(plate_code)',

        # === 分仓止盈任务表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_tp_tasks_stock ON take_profit_tasks(stock_code)',
        'CREATE INDEX IF NOT EXISTS idx_tp_tasks_status ON take_profit_tasks(status)',

        # === 止盈执行记录表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_tp_exec_task ON take_profit_executions(task_id)',
        'CREATE INDEX IF NOT EXISTS idx_tp_exec_status ON take_profit_executions(status)',
        'CREATE INDEX IF NOT EXISTS idx_tp_exec_stock ON take_profit_executions(stock_code)',
        'CREATE INDEX IF NOT EXISTS idx_tp_exec_deal ON take_profit_executions(deal_id)',

        # === 资金流向缓存表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_capital_flow_code ON capital_flow_cache(stock_code)',
        'CREATE INDEX IF NOT EXISTS idx_capital_flow_time ON capital_flow_cache(timestamp)',
        'CREATE INDEX IF NOT EXISTS idx_capital_flow_score ON capital_flow_cache(capital_score DESC)',

        # === 大单追踪表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_big_order_code ON big_order_tracking(stock_code)',
        'CREATE INDEX IF NOT EXISTS idx_big_order_time ON big_order_tracking(timestamp)',
        'CREATE INDEX IF NOT EXISTS idx_big_order_strength ON big_order_tracking(order_strength DESC)',

        # === 信号效果追踪表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_signal_perf_signal ON signal_performance(signal_id)',
        'CREATE INDEX IF NOT EXISTS idx_signal_perf_stock ON signal_performance(stock_code)',
        'CREATE INDEX IF NOT EXISTS idx_signal_perf_status ON signal_performance(tracking_status)',

        # === 决策助理评估记录索引 ===
        'CREATE INDEX IF NOT EXISTS idx_advisor_eval_created ON advisor_evaluations(created_at DESC)',
        'CREATE INDEX IF NOT EXISTS idx_advisor_eval_type ON advisor_evaluations(advice_type)',
        'CREATE INDEX IF NOT EXISTS idx_signal_perf_strategy ON signal_performance(strategy_id)',
        'CREATE INDEX IF NOT EXISTS idx_signal_perf_created ON signal_performance(created_at DESC)',

        # === Scalping 引擎数据表索引 ===
        'CREATE INDEX IF NOT EXISTS idx_scalping_signals_code_date ON scalping_signals(stock_code, trade_date)',
        'CREATE INDEX IF NOT EXISTS idx_scalping_delta_code_date ON scalping_delta_history(stock_code, trade_date)',
        'CREATE INDEX IF NOT EXISTS idx_scalping_poc_code_date ON scalping_poc_snapshot(stock_code, trade_date)',
        'CREATE INDEX IF NOT EXISTS idx_scalping_levels_code_date ON scalping_price_levels(stock_code, trade_date)',
    ]

    @classmethod
    def get_all_tables(cls) -> list:
        """获取所有表创建SQL"""
        return [
            cls.PLATES_TABLE,
            cls.STOCKS_TABLE,
            cls.STOCK_PLATES_TABLE,
            cls.KLINE_DATA_TABLE,
            cls.KLINE_5MIN_DATA_TABLE,
            cls.TRADE_SIGNALS_TABLE,
            cls.SYSTEM_CONFIG_TABLE,
            cls.PLATE_MATCH_LOG_TABLE,
            cls.TRADING_RECORDS_TABLE,
            cls.DAILY_ACTIVE_STOCKS_TABLE,
            cls.NEWS_TABLE,
            cls.NEWS_STOCKS_TABLE,
            cls.NEWS_PLATES_TABLE,
            cls.TAKE_PROFIT_TASKS_TABLE,
            cls.TAKE_PROFIT_EXECUTIONS_TABLE,
            cls.CAPITAL_FLOW_CACHE_TABLE,
            cls.BIG_ORDER_TRACKING_TABLE,
            cls.AUTO_TRADE_TASKS_TABLE,
            cls.SIGNAL_PERFORMANCE_TABLE,
            cls.ADVISOR_EVALUATIONS_TABLE,
            # === Scalping 引擎数据表 ===
            cls.SCALPING_SIGNALS_TABLE,
            cls.SCALPING_DELTA_HISTORY_TABLE,
            cls.SCALPING_POC_SNAPSHOT_TABLE,
            cls.SCALPING_PRICE_LEVELS_TABLE,
            cls.TICKER_DATA_TABLE,
            cls.SCALPING_EVENTS_TABLE,
        ]

    @classmethod
    def get_all_indexes(cls) -> list:
        """获取所有索引创建SQL"""
        indexes = cls.INDEXES.copy()
        # 添加逐笔数据索引
        if hasattr(cls, 'TICKER_DATA_INDEXES'):
            indexes.extend(cls.TICKER_DATA_INDEXES)
        # 添加 Scalping 事件索引
        if hasattr(cls, 'SCALPING_EVENTS_INDEXES'):
            indexes.extend(cls.SCALPING_EVENTS_INDEXES)
        return indexes


class TableNames:
    """表名常量"""
    PLATES = "plates"
    STOCKS = "stocks"
    STOCK_PLATES = "stock_plates"
    KLINE_DATA = "kline_data"
    KLINE_5MIN_DATA = "kline_5min_data"
    TRADE_SIGNALS = "trade_signals"
    SYSTEM_CONFIG = "system_config"
    PLATE_MATCH_LOG = "plate_match_log"
    TRADING_RECORDS = "trading_records"
    DAILY_ACTIVE_STOCKS = "daily_active_stocks"
    NEWS = "news"
    NEWS_STOCKS = "news_stocks"
    NEWS_PLATES = "news_plates"
    TAKE_PROFIT_TASKS = "take_profit_tasks"
    TAKE_PROFIT_EXECUTIONS = "take_profit_executions"
    CAPITAL_FLOW_CACHE = "capital_flow_cache"
    BIG_ORDER_TRACKING = "big_order_tracking"
    AUTO_TRADE_TASKS = "auto_trade_tasks"
    SIGNAL_PERFORMANCE = "signal_performance"
    ADVISOR_EVALUATIONS = "advisor_evaluations"
    # Scalping 引擎数据表
    SCALPING_SIGNALS = "scalping_signals"
    SCALPING_DELTA_HISTORY = "scalping_delta_history"
    SCALPING_POC_SNAPSHOT = "scalping_poc_snapshot"
    SCALPING_PRICE_LEVELS = "scalping_price_levels"
    SCALPING_EVENTS = "scalping_events"
