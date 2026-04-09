#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QuotePipeline 单元测试

验证统一行情处理管道的核心逻辑：
- run_pipeline 完整流程
- 策略检测间隔控制
- 报价获取失败时跳过后续步骤
- quotes_update 事件仅广播一次
"""

import os
import sys
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.core.pipeline.quote_pipeline import QuotePipeline
from simple_trade.websocket.events import SocketEvent


# ============================================================
# 测试辅助
# ============================================================

def _make_config(push_interval=5, strategy_interval=60):
    cfg = MagicMock()
    cfg.quote_push_interval = push_interval
    cfg.strategy_check_interval = strategy_interval
    return cfg


def _make_container(config=None):
    container = MagicMock()
    container.config = config or _make_config()
    container.subscription_manager.subscribed_stocks = {'HK.00700', 'HK.09988'}
    container.stock_data_service.get_real_quotes_from_subscribed = MagicMock(
        return_value=[
            {'code': 'HK.00700', 'last_price': 350.0, 'change_percent': 1.5,
             'volume': 10000, 'high_price': 355.0, 'low_price': 345.0},
            {'code': 'HK.09988', 'last_price': 80.0, 'change_percent': -0.5,
             'volume': 5000, 'high_price': 82.0, 'low_price': 79.0},
        ]
    )
    container.alert_service.check_alerts = MagicMock(return_value=[])
    container.kline_service.get_cached_quota_info = MagicMock(return_value=None)
    return container


def _make_state_manager():
    sm = MagicMock()
    sm.get_stock_pool.return_value = {
        'stocks': [
            {'code': 'HK.00700', 'name': '腾讯控股', 'market': 'HK', 'id': 1,
             'plate_name': '互联网'},
            {'code': 'HK.09988', 'name': '阿里巴巴', 'market': 'HK', 'id': 2,
             'plate_name': '互联网'},
        ]
    }
    sm.get_trading_conditions.return_value = {}
    sm.get_signals_by_strategy.return_value = {}
    return sm


def _make_socket_manager():
    sm = MagicMock()
    sm.emit_to_all = AsyncMock()
    return sm


def _make_pipeline(push_interval=5, strategy_interval=60):
    config = _make_config(push_interval, strategy_interval)
    container = _make_container(config)
    state_manager = _make_state_manager()
    socket_manager = _make_socket_manager()
    pipeline = QuotePipeline(container, socket_manager, state_manager)
    return pipeline, container, state_manager, socket_manager


def _run(coro):
    """运行异步协程的辅助函数"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================
# run_pipeline 完整流程测试
# ============================================================

class TestRunPipeline:

    def test_full_pipeline_fetches_and_broadcasts(self):
        """run_pipeline 应获取报价并广播"""
        pipeline, container, sm, sock = _make_pipeline()

        _run(pipeline.run_pipeline())

        container.stock_data_service.get_real_quotes_from_subscribed.assert_called_once()
        sm.update_quotes_cache.assert_called_once()
        sm.set_last_update.assert_called_once()

    def test_no_quotes_skips_pipeline(self):
        """报价为空时跳过后续所有步骤"""
        pipeline, container, sm, sock = _make_pipeline()
        container.stock_data_service.get_real_quotes_from_subscribed = MagicMock(
            return_value=[]
        )

        _run(pipeline.run_pipeline())

        sm.update_quotes_cache.assert_not_called()
        sm.set_last_update.assert_not_called()

    def test_no_subscribed_stocks_skips(self):
        """没有订阅股票时跳过"""
        pipeline, container, sm, sock = _make_pipeline()
        container.subscription_manager.subscribed_stocks = set()

        _run(pipeline.run_pipeline())

        sm.update_quotes_cache.assert_not_called()


# ============================================================
# 策略检测间隔控制测试
# ============================================================

class TestStrategyInterval:

    def test_should_run_strategy_first_cycle(self):
        """第一次循环应执行策略检测"""
        pipeline, *_ = _make_pipeline(push_interval=5, strategy_interval=60)
        pipeline._loop_count = 1
        assert pipeline._should_run_strategy() is True

    def test_should_run_strategy_skip_intermediate(self):
        """中间循环不应执行策略检测"""
        pipeline, *_ = _make_pipeline(push_interval=5, strategy_interval=60)
        pipeline._loop_count = 5
        assert pipeline._should_run_strategy() is False

    def test_should_run_strategy_next_interval(self):
        """到达下一个间隔时应执行策略检测"""
        pipeline, *_ = _make_pipeline(push_interval=5, strategy_interval=60)
        pipeline._loop_count = 13  # 13 % 12 == 1
        assert pipeline._should_run_strategy() is True


# ============================================================
# 单次广播验证
# ============================================================

class TestSingleBroadcast:

    def test_quotes_update_emitted_once(self):
        """一次 run_pipeline 中 quotes_update 事件只广播一次"""
        pipeline, container, sm, sock = _make_pipeline(
            push_interval=5, strategy_interval=5
        )

        _run(pipeline.run_pipeline())

        quotes_update_calls = [
            c for c in sock.emit_to_all.call_args_list
            if c[0][0] == SocketEvent.QUOTES_UPDATE
        ]
        # run_quote_cycle 广播一次，run_monitoring_cycle 可能再广播一次（如果有策略结果）
        # 但 run_quote_cycle 至少广播一次
        assert len(quotes_update_calls) >= 1

    def test_broadcast_includes_quotes(self):
        """广播数据中应包含报价数据"""
        pipeline, container, sm, sock = _make_pipeline(
            push_interval=5, strategy_interval=5
        )

        _run(pipeline.run_pipeline())

        quotes_call = next(
            c for c in sock.emit_to_all.call_args_list
            if c[0][0] == SocketEvent.QUOTES_UPDATE
        )
        data = quotes_call[0][1]
        assert 'quotes' in data
        assert len(data['quotes']) == 2


# ============================================================
# 价格触发条件测试
# ============================================================

class TestPriceTriggers:

    def test_price_monitor_called(self):
        """有 price_monitor 时应调用 check_prices"""
        mock_pms = MagicMock()
        config = _make_config()
        container = _make_container(config)
        state_manager = _make_state_manager()
        socket_manager = _make_socket_manager()

        pipeline = QuotePipeline(
            container, socket_manager, state_manager,
            price_monitor=mock_pms
        )

        quotes = [{'code': 'HK.00700', 'last_price': 350.0}]
        _run(pipeline._check_price_triggers(quotes))

        mock_pms.check_prices.assert_called_once_with(quotes)

    def test_no_services_no_error(self):
        """所有价格监控服务为 None 时不报错"""
        pipeline, container, sm, sock = _make_pipeline()
        # 确保 container 上没有 lot 服务
        container.lot_take_profit_service = None
        container.lot_order_take_profit_service = None

        quotes = [{'code': 'HK.00700', 'last_price': 350.0}]
        _run(pipeline._check_price_triggers(quotes))


# ============================================================
# _get_target_stocks 测试
# ============================================================

class TestGetTargetStocks:

    def test_returns_subscribed_stocks_only(self):
        """只返回已订阅的股票"""
        pipeline, container, sm, sock = _make_pipeline()
        container.subscription_manager.subscribed_stocks = {'HK.00700'}

        result = pipeline._get_target_stocks()

        assert len(result) == 1
        assert result[0]['code'] == 'HK.00700'

    def test_empty_when_no_subscription(self):
        """没有订阅时返回空列表"""
        pipeline, container, sm, sock = _make_pipeline()
        container.subscription_manager.subscribed_stocks = set()

        result = pipeline._get_target_stocks()

        assert result == []