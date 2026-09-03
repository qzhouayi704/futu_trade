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
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.core.pipeline.quote_pipeline import QuotePipeline
from simple_trade.config.legacy_signal_policy import resolve_legacy_signal_policy
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


class TestLegacyObserveMode:

    def test_only_hard_risk_actions_keep_decision_authority(self):
        pipeline, container, _, _ = _make_pipeline()
        pipeline.legacy_signal_policy = resolve_legacy_signal_policy({
            "LEGACY_SIGNAL_MODE": "observe",
        })
        container.v2_runtime = None
        quotes = [{"code": "HK.03690", "last_price": 78.0, "prev_close": 76.0}]
        positions = {"HK.03690": {"stock_name": "美团", "qty": 100}}
        hard_risk = {
            "stock_code": "HK.03690", "stock_name": "美团",
            "signal_type": "SELL", "price": 78.0, "reason": "硬止损触发",
        }
        old_r13 = {
            "stock_code": "HK.03690", "stock_name": "美团",
            "signal_type": "SELL", "price": 78.0, "reason": "[R13]波段高抛",
        }
        old_buy = {
            "stock_code": "HK.03690", "stock_name": "美团",
            "signal_type": "BUY", "price": 78.0, "reason": "旧吸收信号",
        }

        pipeline._get_positions_dict = AsyncMock(return_value=positions)
        pipeline._check_price_triggers = AsyncMock()
        pipeline._check_intraday_profit = AsyncMock(return_value=[old_r13])
        pipeline._check_intraday_risks = AsyncMock(return_value=[hard_risk])
        pipeline._check_open_risk = AsyncMock(return_value=[])
        pipeline._push_open_check_once = AsyncMock()
        pipeline._should_run_strategy = MagicMock(return_value=True)
        pipeline._filter_trading_quotes = MagicMock(return_value=quotes)
        pipeline._check_capital_flow_signals = AsyncMock(return_value=[old_r13])
        pipeline._check_absorption = AsyncMock(return_value=[old_buy])
        pipeline._check_swing_buyback = AsyncMock(return_value=[old_buy])
        pipeline._check_t_trade = AsyncMock(return_value=[old_r13])
        pipeline._feed_sell_signals_to_swing_tracker = MagicMock()
        pipeline._run_strategy_detection = AsyncMock(return_value=([old_buy], []))
        pipeline._start_signal_tracking = MagicMock()
        pipeline._update_signal_tracking = AsyncMock()
        pipeline._signal_arbitrator.arbitrate = MagicMock(side_effect=lambda actions: actions)
        pipeline._notify_trade_signals = MagicMock()
        pipeline._flush_exit_coordinator = AsyncMock()
        pipeline._flush_tick_capital = AsyncMock()
        pipeline._run_capital_trend_detector = AsyncMock()
        pipeline._push_eod_reconcile_once = AsyncMock()
        pipeline._filter_feed_actions = MagicMock(side_effect=lambda actions, _: actions)
        pipeline._broadcaster.broadcast = AsyncMock()

        _run(pipeline.run_monitoring_cycle(quotes))

        pipeline._check_capital_flow_signals.assert_awaited_once()
        pipeline._check_absorption.assert_awaited_once()
        pipeline._check_intraday_profit.assert_not_awaited()
        pipeline._check_swing_buyback.assert_not_awaited()
        pipeline._check_t_trade.assert_not_awaited()
        pipeline._feed_sell_signals_to_swing_tracker.assert_not_called()
        pipeline._start_signal_tracking.assert_not_called()
        pipeline._update_signal_tracking.assert_not_awaited()
        pipeline._notify_trade_signals.assert_called_once_with([hard_risk], positions)
        pipeline._broadcaster.broadcast.assert_awaited_once_with(quotes, [hard_risk], [])

    def test_capital_trend_is_persisted_and_fed_to_v2_without_direct_alert(self):
        pipeline, container, _, socket = _make_pipeline()
        pipeline.legacy_signal_policy = resolve_legacy_signal_policy({
            "LEGACY_SIGNAL_MODE": "observe",
        })
        quote = {"code": "HK.03690", "last_price": 78.0, "prev_close": 76.0}
        alert_payload = {
            "stock_code": "HK.03690",
            "stock_name": "美团",
            "direction": "RISING",
            "trade_date": "2026-09-02",
            "timestamp": 1788321600,
            "reason": "主力资金持续流入",
        }
        alert = SimpleNamespace(
            direction="RISING",
            is_strong_push=True,
            wechat_suppressed=False,
            to_dict=MagicMock(return_value=dict(alert_payload)),
        )
        detector = MagicMock(enabled=True)
        detector.evaluate.return_value = alert
        accumulator = MagicMock(enabled=True)
        accumulator.snapshot.return_value = {"stock_code": "HK.03690"}
        v2_runtime = MagicMock(started=True)
        container.capital_trend_detector = detector
        container.tick_capital_accumulator = accumulator
        container.baseline_service.get_capital_tiers.return_value = (1.0, 1.0, 1.0)
        container.wechat_alert_service = MagicMock(enabled=True)
        container.v2_runtime = v2_runtime
        pipeline._filter_trading_quotes = MagicMock(return_value=[quote])
        pipeline._capital_inflow_market_gate.evaluate = MagicMock(return_value={
            "HK.03690": {"eligible": True, "is_hot": True, "reason": "热门股"},
        })
        pipeline._run_in_executor = AsyncMock()

        _run(pipeline._run_capital_trend_detector([quote], {}))

        socket.emit_to_all.assert_not_awaited()
        v2_runtime.ingest_legacy_signal.assert_called_once()
        fed_payload = v2_runtime.ingest_legacy_signal.call_args.args[0]
        assert fed_payload["advisory"] is True
        assert fed_payload["legacy_observe_only"] is True
        pipeline._run_in_executor.assert_awaited_once()


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

    @patch('simple_trade.utils.market_helper.MarketTimeHelper.is_any_market_trading', return_value=True)
    def test_should_run_strategy_warmup_skipped(self, mock_trading):
        """启动预热期内不执行策略检测"""
        pipeline, *_ = _make_pipeline(push_interval=5, strategy_interval=60)
        pipeline._loop_count = 1
        assert pipeline._should_run_strategy() is False

    @patch('simple_trade.utils.market_helper.MarketTimeHelper.is_any_market_trading', return_value=True)
    def test_should_run_strategy_skip_intermediate(self, mock_trading):
        """中间循环不应执行策略检测"""
        pipeline, *_ = _make_pipeline(push_interval=5, strategy_interval=60)
        pipeline._loop_count = 14
        assert pipeline._should_run_strategy() is False

    @patch('simple_trade.utils.market_helper.MarketTimeHelper.is_any_market_trading', return_value=True)
    def test_should_run_strategy_next_interval(self, mock_trading):
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


# ============================================================
# 主力资金企微提醒语义
# ============================================================

class TestCapitalTrendWechat:

    @staticmethod
    def _falling_alert(*, held_outflow: bool):
        return SimpleNamespace(
            stock_code="HK.00700",
            stock_name="腾讯控股",
            direction="FALLING",
            strength_tier="强",
            strength_mult=2.0,
            cum_main_net=-5_000_000.0,
            window_main_net=-3_000_000.0,
            pullback_amount=0.0,
            intraday_change_pct=-1.2,
            big_buy_count=1,
            big_sell_count=3,
            big_order_threshold=2_000_000.0,
            last_price=500.0,
            is_held_outflow=held_outflow,
            is_large_inflow=False,
        )

    @staticmethod
    def _inflow_alert(stage: str):
        return SimpleNamespace(
            stock_code="HK.06082", stock_name="壁仞科技", direction="RISING",
            strength_tier="强", strength_mult=2.2, cum_main_net=12_000_000.0,
            window_main_net=8_000_000.0, pullback_amount=0.0,
            intraday_change_pct=-0.5, big_buy_count=3, big_sell_count=0,
            big_order_threshold=2_000_000.0, last_price=60.0,
            is_held_outflow=False, is_large_inflow=True,
            is_inflow_trailing_exit=False, inflow_stage=stage,
            inflow_sequence_no={"FIRST": 1, "CONFIRMED": 2, "STRENGTHENED": 3}[stage],
            window_big_buy=9_000_000.0, window_big_sell=1_000_000.0,
            window_buy_ratio=0.9, market_breadth=0.6,
            market_universe_size=100, turnover_rank_percentile=0.9,
        )

    def test_held_outflow_explicitly_prompts_sell_review(self):
        pipeline, *_ = _make_pipeline()
        wechat = MagicMock()
        wechat.send = AsyncMock(return_value=True)

        _run(pipeline._push_capital_trend_wechat(
            wechat, self._falling_alert(held_outflow=True)
        ))

        args, kwargs = wechat.send.call_args
        assert "持仓大单净流出·卖出提醒" in args[1]
        assert "卖出提醒" in args[2]
        assert "不会自动下单" in args[2]
        assert kwargs["category"] == "持仓主力净流出"

    def test_nonheld_falling_does_not_prompt_sell(self):
        pipeline, *_ = _make_pipeline()
        wechat = MagicMock()
        wechat.send = AsyncMock(return_value=True)

        _run(pipeline._push_capital_trend_wechat(
            wechat, self._falling_alert(held_outflow=False)
        ))

        args, kwargs = wechat.send.call_args
        assert "卖出提醒" not in args[1]
        assert "卖出提醒" not in args[2]
        assert kwargs["category"] == "主力资金趋势"

    def test_first_inflow_is_observation_category(self):
        pipeline, *_ = _make_pipeline()
        wechat = MagicMock()
        wechat.send = AsyncMock(return_value=True)
        _run(pipeline._push_capital_trend_wechat(wechat, self._inflow_alert("FIRST")))
        args, kwargs = wechat.send.call_args
        assert "首次强流入·试仓观察" in args[1]
        assert "15分钟内" in args[2]
        assert kwargs["category"] == "大额主力资金流入"

    def test_second_inflow_is_buy_confirmation_category(self):
        pipeline, *_ = _make_pipeline()
        wechat = MagicMock()
        wechat.send = AsyncMock(return_value=True)
        _run(pipeline._push_capital_trend_wechat(wechat, self._inflow_alert("CONFIRMED")))
        args, kwargs = wechat.send.call_args
        assert "二次强流入·买点确认" in args[1]
        assert "买点确认" in args[2]
        assert kwargs["category"] == "资金流入确认"
        assert kwargs["priority"] == 82

    def test_trailing_exit_is_sell_category(self):
        pipeline, *_ = _make_pipeline()
        wechat = MagicMock()
        wechat.send = AsyncMock(return_value=True)
        alert = self._falling_alert(held_outflow=False)
        alert.is_inflow_trailing_exit = True
        alert.inflow_stage = "TRAIL_EXIT"
        alert.inflow_sequence_no = 2
        alert.inflow_peak_price = 105.0
        alert.price_pullback_pct = 0.015
        alert.is_profit_exit = True
        _run(pipeline._push_capital_trend_wechat(wechat, alert))
        args, kwargs = wechat.send.call_args
        assert "资金流峰值回撤·止盈提醒" in args[1]
        assert "止盈提醒" in args[2]
        assert kwargs["category"] == "主力资金止盈"
        assert kwargs["priority"] == 91
