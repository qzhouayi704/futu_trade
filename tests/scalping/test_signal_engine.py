#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SignalEngine 单元测试 - 突破追多/支撑低吸信号条件完备性"""

import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ),
)

from simple_trade.services.scalping.calculators.delta_calculator import DeltaCalculator
from simple_trade.services.scalping.models import (
    DeltaUpdateData,
    PriceLevelAction,
    PriceLevelData,
    PriceLevelSide,
    ScalpingSignalType,
)
from simple_trade.services.scalping.calculators.poc_calculator import POCCalculator
from simple_trade.services.scalping.signal_engine import SignalEngine
from simple_trade.services.scalping.detectors.spoofing_filter import SpoofingFilter
from simple_trade.services.scalping.calculators.tape_velocity import TapeVelocityMonitor
from simple_trade.websocket.events import SocketEvent

STOCK = "HK.00700"
TICK_SIZE = 0.01


# ── 辅助函数 ──────────────────────────────────────────────

def _mock_sm():
    sm = MagicMock()
    sm.emit_to_all = AsyncMock()
    return sm


def _delta(delta: float) -> DeltaUpdateData:
    return DeltaUpdateData(
        stock_code=STOCK, delta=delta, volume=1000,
        timestamp="2024-01-01T10:00:00", period_seconds=10,
    )


def _make_level(
    price: float, side: PriceLevelSide, volume: int = 5000,
) -> PriceLevelData:
    return PriceLevelData(
        stock_code=STOCK, price=price, volume=volume, side=side,
        action=PriceLevelAction.CREATE, timestamp="2024-01-01T10:00:00",
    )


def _make_engine(
    tick_size: float = TICK_SIZE, stall_seconds: float = 3.0,
) -> tuple[SignalEngine, MagicMock]:
    sm = _mock_sm()
    dc = DeltaCalculator(socket_manager=sm)
    tv = TapeVelocityMonitor(socket_manager=sm)
    sf = SpoofingFilter(socket_manager=sm, tick_size=tick_size)
    pc = POCCalculator(socket_manager=sm)
    vwap_mock = MagicMock()
    vwap_mock.get_deviation_level.return_value = "fair"
    vwap_mock.get_current_vwap.return_value = None
    engine = SignalEngine(
        socket_manager=sm, delta_calculator=dc, tape_velocity=tv,
        spoofing_filter=sf, poc_calculator=pc, vwap_guard=vwap_mock,
        tick_size=tick_size, stall_seconds=stall_seconds,
        min_signal_score=0,
    )
    return engine, sm


def _setup_breakout_conditions(
    engine: SignalEngine,
    delta_values: list[float] | None = None,
    cooldown: bool = True,
    resistance_levels: list[PriceLevelData] | None = None,
):
    """配置突破追多信号的所有前置条件"""
    if delta_values is None:
        delta_values = [100.0] * 19 + [300.0]
    state = engine._delta_calculator._get_state(STOCK)
    for dv in delta_values:
        state.history.append(_delta(dv))
    # 设置当前周期的大单占比 > 30%（条件 5）
    state.current_period.volume = 1000
    state.current_period.big_order_volume = 400
    tv_state = engine._tape_velocity._get_state(STOCK)
    if cooldown:
        tv_state.cooldown_until = time.time() + 100
        tv_state.tick_timestamps.append(time.time())
    else:
        tv_state.cooldown_until = 0.0
    if resistance_levels is not None:
        engine._spoofing_filter._active_levels[STOCK] = resistance_levels


def _setup_support_conditions(
    engine: SignalEngine,
    poc_price: float | None = None,
    support_levels: list[PriceLevelData] | None = None,
    delta_value: float = -500.0,
    stall: bool = True,
    current_price: float = 10.0,
) -> float | None:
    """配置支撑低吸信号的所有前置条件。stall=True 时返回基准时间戳。"""
    if poc_price is not None:
        poc_state = engine._poc_calculator._get_state(STOCK)
        poc_state.last_poc_price = poc_price
    if support_levels is not None:
        engine._spoofing_filter._active_levels[STOCK] = support_levels
    state = engine._delta_calculator._get_state(STOCK)
    state.history.append(_delta(delta_value))
    if stall:
        now = time.time()
        for i in range(25):
            engine.record_price(STOCK, current_price, now - 5.0 + i * 0.2)
        return now


# ── 突破追多信号测试 ──────────────────────────────────────

class TestBreakoutSignal:
    """突破追多信号条件完备性"""

    @pytest.mark.asyncio
    async def test_all_conditions_met_generates_signal(self):
        """四个条件全部满足时应生成信号"""
        engine, sm = _make_engine()
        _setup_breakout_conditions(engine)
        result = await engine.evaluate_breakout(
            STOCK, current_price=10.04, day_high=10.05
        )
        assert result is not None
        assert result.signal_type == ScalpingSignalType.BREAKOUT_LONG
        assert result.trigger_price == 10.04
        assert len(result.conditions) == 5
        sm.emit_to_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_price_too_far_from_high_no_signal(self):
        """条件 1 不满足：价格距日内高点 >= 5 Tick"""
        engine, sm = _make_engine()
        _setup_breakout_conditions(engine)
        result = await engine.evaluate_breakout(
            STOCK, current_price=9.95, day_high=10.05
        )
        assert result is None
        sm.emit_to_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_momentum_ignition_no_signal(self):
        """条件 2 不满足：动能点火未触发"""
        engine, sm = _make_engine()
        _setup_breakout_conditions(engine, cooldown=False)
        result = await engine.evaluate_breakout(
            STOCK, current_price=10.04, day_high=10.05
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_weak_delta_no_signal(self):
        """条件 3 不满足：Delta 不够强"""
        engine, sm = _make_engine()
        _setup_breakout_conditions(
            engine, delta_values=[100.0] * 19 + [150.0]
        )
        result = await engine.evaluate_breakout(
            STOCK, current_price=10.04, day_high=10.05
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_resistance_not_cleared_no_signal(self):
        """条件 4 不满足：阻力线未被抹除"""
        engine, sm = _make_engine()
        _setup_breakout_conditions(
            engine,
            resistance_levels=[_make_level(10.05, PriceLevelSide.RESISTANCE)],
        )
        result = await engine.evaluate_breakout(
            STOCK, current_price=10.04, day_high=10.05
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_delta_data_no_signal(self):
        """无 Delta 数据时不生成信号"""
        engine, sm = _make_engine()
        tv_state = engine._tape_velocity._get_state(STOCK)
        tv_state.cooldown_until = time.time() + 100
        tv_state.tick_timestamps.append(time.time())
        result = await engine.evaluate_breakout(
            STOCK, current_price=10.04, day_high=10.05
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_price_exactly_at_high_generates_signal(self):
        """价格恰好等于日内高点（距离 0 Tick < 5 Tick）"""
        engine, sm = _make_engine()
        _setup_breakout_conditions(engine)
        result = await engine.evaluate_breakout(
            STOCK, current_price=10.05, day_high=10.05
        )
        assert result is not None
        assert result.signal_type == ScalpingSignalType.BREAKOUT_LONG


# ── 支撑低吸信号测试 ──────────────────────────────────────

class TestSupportBounceSignal:
    """支撑低吸信号条件完备性"""

    @pytest.mark.asyncio
    async def test_all_conditions_met_generates_signal(self):
        """三个条件全部满足时应生成信号"""
        engine, sm = _make_engine()
        base_time = _setup_support_conditions(
            engine, poc_price=10.01, current_price=10.0
        )
        result = await engine.evaluate_support_bounce(
            STOCK, current_price=10.0, now=base_time
        )
        assert result is not None
        assert result.signal_type == ScalpingSignalType.SUPPORT_LONG
        assert result.support_price is not None
        assert len(result.conditions) == 3
        sm.emit_to_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_nearby_support_no_signal(self):
        """条件 1 不满足：附近无支撑位"""
        engine, sm = _make_engine()
        _setup_support_conditions(engine, poc_price=11.0, current_price=10.0)
        result = await engine.evaluate_support_bounce(STOCK, current_price=10.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_positive_delta_no_signal(self):
        """条件 2 不满足：Delta 为正值"""
        engine, sm = _make_engine()
        _setup_support_conditions(
            engine, poc_price=10.01, delta_value=500.0, current_price=10.0,
        )
        result = await engine.evaluate_support_bounce(STOCK, current_price=10.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_stall_no_signal(self):
        """条件 3 不满足：价格未停滞"""
        engine, sm = _make_engine()
        _setup_support_conditions(
            engine, poc_price=10.01, stall=False, current_price=10.0,
        )
        result = await engine.evaluate_support_bounce(STOCK, current_price=10.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_support_from_green_line(self):
        """支撑来自绿色支撑线（非 POC）"""
        engine, sm = _make_engine()
        base_time = _setup_support_conditions(
            engine, poc_price=None,
            support_levels=[_make_level(10.01, PriceLevelSide.SUPPORT, 8000)],
            current_price=10.0,
        )
        result = await engine.evaluate_support_bounce(
            STOCK, current_price=10.0, now=base_time
        )
        assert result is not None
        assert result.support_price == 10.01

    @pytest.mark.asyncio
    async def test_zero_delta_no_signal(self):
        """Delta 恰好为 0 时不生成信号（需要负值）"""
        engine, sm = _make_engine()
        _setup_support_conditions(
            engine, poc_price=10.01, delta_value=0.0, current_price=10.0,
        )
        result = await engine.evaluate_support_bounce(STOCK, current_price=10.0)
        assert result is None


# ── 价格停滞检测与辅助方法测试 ────────────────────────────

class TestPriceStall:
    """价格停滞检测逻辑"""

    def test_stall_detected_when_price_stable(self):
        """价格在 3 秒内波动 < 2 Tick 应判定为停滞"""
        engine, _ = _make_engine(stall_seconds=3.0)
        now = time.time()
        for i in range(20):
            engine.record_price(STOCK, 10.0, now - 4.0 + i * 0.2)
        assert engine._check_price_stall(STOCK, 10.0, now) is True

    def test_no_stall_when_price_volatile(self):
        """价格波动 >= 2 Tick 不应判定为停滞"""
        engine, _ = _make_engine(stall_seconds=3.0)
        now = time.time()
        for i in range(20):
            price = 10.0 if i % 2 == 0 else 10.05
            engine.record_price(STOCK, price, now - 4.0 + i * 0.2)
        assert engine._check_price_stall(STOCK, 10.0, now) is False

    def test_no_stall_when_insufficient_time(self):
        """记录时间不足 3 秒不应判定为停滞"""
        engine, _ = _make_engine(stall_seconds=3.0)
        now = time.time()
        for i in range(5):
            engine.record_price(STOCK, 10.0, now - 1.0 + i * 0.2)
        assert engine._check_price_stall(STOCK, 10.0, now) is False

    def test_no_stall_when_no_records(self):
        """无价格记录时不应判定为停滞"""
        engine, _ = _make_engine()
        assert engine._check_price_stall(STOCK, 10.0, time.time()) is False


class TestHelperAndReset:
    """辅助方法和重置测试"""

    def test_get_latest_delta_empty_returns_none(self):
        engine, _ = _make_engine()
        assert engine._get_latest_delta(STOCK) is None

    def test_find_nearest_support_from_poc(self):
        engine, _ = _make_engine()
        engine._poc_calculator._get_state(STOCK).last_poc_price = 10.01
        assert engine._find_nearest_support(STOCK, 10.0, 3) == 10.01

    def test_find_nearest_support_none_when_far(self):
        engine, _ = _make_engine()
        engine._poc_calculator._get_state(STOCK).last_poc_price = 11.0
        assert engine._find_nearest_support(STOCK, 10.0, 3) is None

    def test_has_resistance_ignores_support(self):
        engine, _ = _make_engine()
        engine._spoofing_filter._active_levels[STOCK] = [
            _make_level(10.03, PriceLevelSide.SUPPORT)
        ]
        assert engine._has_resistance_near(STOCK, 10.05, ticks=5) is False

    def test_reset_clears_stall_tracker(self):
        engine, _ = _make_engine()
        engine.record_price(STOCK, 10.0, time.time())
        assert STOCK in engine._stall_trackers
        engine.reset(STOCK)
        assert STOCK not in engine._stall_trackers

    @pytest.mark.asyncio
    async def test_emit_signal_calls_socket_manager(self):
        engine, sm = _make_engine()
        _setup_breakout_conditions(engine)
        await engine.evaluate_breakout(STOCK, current_price=10.04, day_high=10.05)
        sm.emit_to_all.assert_called_once()
        assert sm.emit_to_all.call_args[0][0] == SocketEvent.SCALPING_SIGNAL

    @pytest.mark.asyncio
    async def test_emit_failure_does_not_raise(self):
        engine, sm = _make_engine()
        sm.emit_to_all = AsyncMock(side_effect=Exception("push failed"))
        _setup_breakout_conditions(engine)
        result = await engine.evaluate_breakout(
            STOCK, current_price=10.04, day_high=10.05
        )
        assert result is not None
