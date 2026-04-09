#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SignalEngine 属性测试

使用 hypothesis 验证突破做多和支撑低吸信号的条件完备性。

Feature: intraday-scalping-engine, Property 12: 突破做多信号条件完备性
Feature: intraday-scalping-engine, Property 13: 支撑低吸信号条件完备性
**Validates: Requirements 9.1, 10.1**
"""

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume, strategies as st

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

STOCK = "HK.00700"
TICK_SIZE = 0.01


# ── 辅助函数 ──────────────────────────────────────────────────────

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


def _cents_to_price(cents: int) -> float:
    """整数分转价格，避免浮点精度问题"""
    return cents / 100.0


def _make_engine(tick_size: float = TICK_SIZE) -> SignalEngine:
    """创建带 mock 依赖的 SignalEngine"""
    sm = _mock_sm()
    dc = DeltaCalculator(socket_manager=sm)
    tv = TapeVelocityMonitor(socket_manager=sm)
    sf = SpoofingFilter(socket_manager=sm, tick_size=tick_size)
    pc = POCCalculator(socket_manager=sm)
    vwap_mock = MagicMock()
    vwap_mock.get_deviation_level.return_value = "fair"
    vwap_mock.get_current_vwap.return_value = None
    return SignalEngine(
        socket_manager=sm, delta_calculator=dc, tape_velocity=tv,
        spoofing_filter=sf, poc_calculator=pc, vwap_guard=vwap_mock,
        tick_size=tick_size, stall_seconds=3.0,
        min_signal_score=0,
    )


def _setup_breakout_all_met(
    engine: SignalEngine,
    delta_mean: float,
    strong_delta: float,
):
    """配置突破追多信号的条件 2/3/4/5 满足的状态（条件 1 由调用者控制价格）"""
    # 条件 2：动能点火（冷却期内 = 刚触发过）
    tv_state = engine._tape_velocity._get_state(STOCK)
    tv_state.cooldown_until = time.time() + 100
    tv_state.tick_timestamps.append(time.time())

    # 条件 3：Delta 历史 + 最新极强正值
    dc_state = engine._delta_calculator._get_state(STOCK)
    for _ in range(19):
        dc_state.history.append(_delta(delta_mean))
    dc_state.history.append(_delta(strong_delta))

    # 条件 4：无阻力线
    engine._spoofing_filter._active_levels[STOCK] = []

    # 条件 5：大单成交量占比 > 30%
    dc_state.current_period.volume = 1000
    dc_state.current_period.big_order_volume = 400


def _setup_support_all_met(
    engine: SignalEngine,
    support_price: float,
    current_price: float,
    delta_value: float,
    use_poc: bool = True,
) -> float:
    """配置支撑低吸信号的三个条件全部满足的状态

    Returns:
        当前时间戳（用于 evaluate_support_bounce 的 now 参数）
    """
    if use_poc:
        poc_state = engine._poc_calculator._get_state(STOCK)
        poc_state.last_poc_price = support_price
    else:
        engine._spoofing_filter._active_levels[STOCK] = [
            _make_level(support_price, PriceLevelSide.SUPPORT)
        ]

    dc_state = engine._delta_calculator._get_state(STOCK)
    dc_state.history.append(_delta(delta_value))

    now = time.time()
    for i in range(25):
        engine.record_price(STOCK, current_price, now - 5.0 + i * 0.2)
    return now


# ── hypothesis 策略 ──────────────────────────────────────────────

# 使用整数分（cents）构造价格，避免浮点精度问题
price_cents_st = st.integers(min_value=500, max_value=100000)

# 正 Delta 均值
positive_delta_mean_st = st.floats(
    min_value=10.0, max_value=10000.0,
    allow_nan=False, allow_infinity=False,
)

# 负 Delta 值
negative_delta_st = st.floats(
    min_value=-50000.0, max_value=-0.01,
    allow_nan=False, allow_infinity=False,
)


# ── Property 12: 突破做多信号条件完备性 ──────────────────────────
# Feature: intraday-scalping-engine, Property 12: 突破做多信号条件完备性
# **Validates: Requirements 9.1**


class TestProperty12BreakoutSignalCompleteness:
    """Property 12: 对于任意市场状态，Signal_Engine 生成"动能突破，做多"信号
    当且仅当以下四个条件同时满足：
    1. 价格距日内高点 < 5 Tick
    2. 收到动能点火事件（is_in_cooldown=True）
    3. 当前 Delta 为极强正值（> 20 周期均值 × 2）
    4. 对应价位阻力线已被抹除
    """

    # ── 充分性：四个条件全部满足时必须生成信号 ────────────────────

    @given(
        high_cents=price_cents_st,
        tick_distance=st.integers(min_value=0, max_value=4),
        delta_mean=positive_delta_mean_st,
        delta_multiplier=st.floats(
            min_value=2.01, max_value=10.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200)
    def test_all_four_conditions_met_generates_signal(
        self, high_cents: int, tick_distance: int,
        delta_mean: float, delta_multiplier: float,
    ):
        """四个条件同时满足时，必须生成 BREAKOUT_LONG 信号"""
        day_high = _cents_to_price(high_cents)
        current_price = _cents_to_price(high_cents - tick_distance)

        engine = _make_engine()
        _setup_breakout_all_met(engine, delta_mean, abs(delta_mean) * delta_multiplier)

        result = asyncio.get_event_loop().run_until_complete(
            engine.evaluate_breakout(STOCK, current_price, day_high)
        )

        assert result is not None, (
            f"四个条件全部满足时应生成信号: "
            f"距离={tick_distance} Tick, delta_mean={delta_mean}"
        )
        assert result.signal_type == ScalpingSignalType.BREAKOUT_LONG
        assert result.trigger_price == current_price
        assert len(result.conditions) == 5

    # ── 必要性：条件 1 不满足（价格距高点 >= 5 Tick）→ 无信号 ────

    @given(
        high_cents=st.integers(min_value=600, max_value=100000),
        tick_distance=st.integers(min_value=5, max_value=100),
        delta_mean=positive_delta_mean_st,
    )
    @settings(max_examples=200)
    def test_price_far_from_high_no_signal(
        self, high_cents: int, tick_distance: int, delta_mean: float,
    ):
        """条件 1 不满足：价格距日内高点 >= 5 Tick 时不应生成信号"""
        day_high = _cents_to_price(high_cents)
        current_price = _cents_to_price(high_cents - tick_distance)
        assume(current_price > 0)

        engine = _make_engine()
        _setup_breakout_all_met(engine, delta_mean, abs(delta_mean) * 3.0)

        result = asyncio.get_event_loop().run_until_complete(
            engine.evaluate_breakout(STOCK, current_price, day_high)
        )
        assert result is None, "价格距高点 >= 5 Tick 时不应生成信号"

    # ── 必要性：条件 2 不满足（动能点火未触发）→ 无信号 ──────────

    @given(
        high_cents=price_cents_st,
        tick_distance=st.integers(min_value=0, max_value=4),
        delta_mean=positive_delta_mean_st,
    )
    @settings(max_examples=200)
    def test_no_momentum_ignition_no_signal(
        self, high_cents: int, tick_distance: int, delta_mean: float,
    ):
        """条件 2 不满足：动能点火未触发时不应生成信号"""
        day_high = _cents_to_price(high_cents)
        current_price = _cents_to_price(high_cents - tick_distance)

        engine = _make_engine()
        _setup_breakout_all_met(engine, delta_mean, abs(delta_mean) * 3.0)

        # 取消动能点火状态
        tv_state = engine._tape_velocity._get_state(STOCK)
        tv_state.cooldown_until = 0.0

        result = asyncio.get_event_loop().run_until_complete(
            engine.evaluate_breakout(STOCK, current_price, day_high)
        )
        assert result is None, "动能点火未触发时不应生成信号"

    # ── 必要性：条件 3 不满足（Delta 不够强）→ 无信号 ────────────

    @given(
        high_cents=price_cents_st,
        tick_distance=st.integers(min_value=0, max_value=4),
        delta_mean=positive_delta_mean_st,
        weak_ratio=st.floats(
            min_value=0.01, max_value=1.99,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200)
    def test_weak_delta_no_signal(
        self, high_cents: int, tick_distance: int,
        delta_mean: float, weak_ratio: float,
    ):
        """条件 3 不满足：Delta <= 20 周期均值 × 2 时不应生成信号"""
        day_high = _cents_to_price(high_cents)
        current_price = _cents_to_price(high_cents - tick_distance)
        weak_delta = abs(delta_mean) * weak_ratio

        engine = _make_engine()
        _setup_breakout_all_met(engine, delta_mean, weak_delta)

        result = asyncio.get_event_loop().run_until_complete(
            engine.evaluate_breakout(STOCK, current_price, day_high)
        )
        assert result is None, (
            f"Delta 不够强时不应生成信号: "
            f"weak_delta={weak_delta}, threshold={abs(delta_mean) * 2}"
        )

    # ── 必要性：条件 4 不满足（阻力线未被抹除）→ 无信号 ──────────

    @given(
        high_cents=price_cents_st,
        tick_distance=st.integers(min_value=0, max_value=4),
        delta_mean=positive_delta_mean_st,
        resistance_offset=st.integers(min_value=0, max_value=4),
    )
    @settings(max_examples=200)
    def test_resistance_not_cleared_no_signal(
        self, high_cents: int, tick_distance: int,
        delta_mean: float, resistance_offset: int,
    ):
        """条件 4 不满足：阻力线未被抹除时不应生成信号"""
        day_high = _cents_to_price(high_cents)
        current_price = _cents_to_price(high_cents - tick_distance)
        # 阻力线在 day_high 附近（offset 0~4 Tick，在 _has_resistance_near 的 5 Tick 范围内）
        resistance_price = _cents_to_price(high_cents + resistance_offset)

        engine = _make_engine()
        _setup_breakout_all_met(engine, delta_mean, abs(delta_mean) * 3.0)

        # 添加阻力线
        engine._spoofing_filter._active_levels[STOCK] = [
            _make_level(resistance_price, PriceLevelSide.RESISTANCE)
        ]

        result = asyncio.get_event_loop().run_until_complete(
            engine.evaluate_breakout(STOCK, current_price, day_high)
        )
        assert result is None, "阻力线未被抹除时不应生成信号"

    # ── 支撑线不影响突破信号 ──────────────────────────────────────

    @given(
        high_cents=price_cents_st,
        tick_distance=st.integers(min_value=0, max_value=4),
        delta_mean=positive_delta_mean_st,
    )
    @settings(max_examples=200)
    def test_support_line_does_not_block_breakout(
        self, high_cents: int, tick_distance: int, delta_mean: float,
    ):
        """附近存在支撑线（非阻力线）不应阻止突破信号生成"""
        day_high = _cents_to_price(high_cents)
        current_price = _cents_to_price(high_cents - tick_distance)

        engine = _make_engine()
        _setup_breakout_all_met(engine, delta_mean, abs(delta_mean) * 3.0)

        # 添加支撑线（不是阻力线）
        engine._spoofing_filter._active_levels[STOCK] = [
            _make_level(day_high, PriceLevelSide.SUPPORT)
        ]

        result = asyncio.get_event_loop().run_until_complete(
            engine.evaluate_breakout(STOCK, current_price, day_high)
        )
        assert result is not None, "支撑线不应阻止突破信号"


# ── Property 13: 支撑低吸信号条件完备性 ──────────────────────────
# Feature: intraday-scalping-engine, Property 13: 支撑低吸信号条件完备性
# **Validates: Requirements 10.1**


class TestProperty13SupportBounceSignalCompleteness:
    """Property 13: 对于任意市场状态，Signal_Engine 生成"支撑有效，试多"信号
    当且仅当以下三个条件同时满足：
    1. 价格距 POC 或绿色支撑线 < 3 Tick
    2. 当前 Delta 为负值
    3. 价格在支撑位附近停滞超过 3 秒（波动 < 2 Tick）
    """

    # ── 充分性：三个条件全部满足时必须生成信号（POC 作为支撑）────

    @given(
        support_cents=st.integers(min_value=500, max_value=100000),
        tick_distance=st.integers(min_value=0, max_value=2),
        delta_value=negative_delta_st,
    )
    @settings(max_examples=200)
    def test_all_conditions_met_with_poc_generates_signal(
        self, support_cents: int, tick_distance: int, delta_value: float,
    ):
        """三个条件全部满足（POC 作为支撑）时，必须生成 SUPPORT_LONG 信号"""
        support_price = _cents_to_price(support_cents)
        current_price = _cents_to_price(support_cents + tick_distance)

        engine = _make_engine()
        now = _setup_support_all_met(
            engine, support_price, current_price, delta_value, use_poc=True,
        )

        result = asyncio.get_event_loop().run_until_complete(
            engine.evaluate_support_bounce(STOCK, current_price, now=now)
        )

        assert result is not None, (
            f"三个条件全部满足时应生成信号: "
            f"距离={tick_distance} Tick, delta={delta_value}"
        )
        assert result.signal_type == ScalpingSignalType.SUPPORT_LONG
        assert result.support_price is not None
        assert len(result.conditions) == 3

    # ── 充分性：三个条件全部满足时必须生成信号（绿色支撑线）──────

    @given(
        support_cents=st.integers(min_value=500, max_value=100000),
        tick_distance=st.integers(min_value=0, max_value=2),
        delta_value=negative_delta_st,
    )
    @settings(max_examples=200)
    def test_all_conditions_met_with_support_line_generates_signal(
        self, support_cents: int, tick_distance: int, delta_value: float,
    ):
        """三个条件全部满足（绿色支撑线）时，必须生成 SUPPORT_LONG 信号"""
        support_price = _cents_to_price(support_cents)
        current_price = _cents_to_price(support_cents + tick_distance)

        engine = _make_engine()
        now = _setup_support_all_met(
            engine, support_price, current_price, delta_value, use_poc=False,
        )

        result = asyncio.get_event_loop().run_until_complete(
            engine.evaluate_support_bounce(STOCK, current_price, now=now)
        )

        assert result is not None, "绿色支撑线满足条件时应生成信号"
        assert result.signal_type == ScalpingSignalType.SUPPORT_LONG

    # ── 必要性：条件 1 不满足（价格距支撑位 >= 3 Tick）→ 无信号 ──

    @given(
        support_cents=st.integers(min_value=500, max_value=100000),
        tick_distance=st.integers(min_value=3, max_value=50),
        delta_value=negative_delta_st,
    )
    @settings(max_examples=200)
    def test_price_far_from_support_no_signal(
        self, support_cents: int, tick_distance: int, delta_value: float,
    ):
        """条件 1 不满足：价格距支撑位 >= 3 Tick 时不应生成信号
        （_find_nearest_support 使用严格 < 比较，距离 >= 3 Tick 时返回 None）"""
        support_price = _cents_to_price(support_cents)
        current_price = _cents_to_price(support_cents + tick_distance)

        engine = _make_engine()
        now = _setup_support_all_met(
            engine, support_price, current_price, delta_value, use_poc=True,
        )

        result = asyncio.get_event_loop().run_until_complete(
            engine.evaluate_support_bounce(STOCK, current_price, now=now)
        )
        assert result is None, (
            f"价格距支撑位 >= 3 Tick 时不应生成信号: 距离={tick_distance} Tick"
        )

    # ── 必要性：条件 2 不满足（Delta 非负值）→ 无信号 ────────────

    @given(
        support_cents=st.integers(min_value=500, max_value=100000),
        tick_distance=st.integers(min_value=0, max_value=2),
        positive_delta=st.floats(
            min_value=0.0, max_value=50000.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200)
    def test_non_negative_delta_no_signal(
        self, support_cents: int, tick_distance: int, positive_delta: float,
    ):
        """条件 2 不满足：Delta >= 0 时不应生成信号"""
        support_price = _cents_to_price(support_cents)
        current_price = _cents_to_price(support_cents + tick_distance)

        engine = _make_engine()

        # 条件 1：设置 POC
        poc_state = engine._poc_calculator._get_state(STOCK)
        poc_state.last_poc_price = support_price

        # 条件 2 不满足：Delta >= 0
        dc_state = engine._delta_calculator._get_state(STOCK)
        dc_state.history.append(_delta(positive_delta))

        # 条件 3：价格停滞
        now = time.time()
        for i in range(25):
            engine.record_price(STOCK, current_price, now - 5.0 + i * 0.2)

        result = asyncio.get_event_loop().run_until_complete(
            engine.evaluate_support_bounce(STOCK, current_price, now=now)
        )
        assert result is None, f"Delta >= 0 时不应生成信号: delta={positive_delta}"

    # ── 必要性：条件 3 不满足（价格未停滞 - 无记录）→ 无信号 ────

    @given(
        support_cents=st.integers(min_value=500, max_value=100000),
        tick_distance=st.integers(min_value=0, max_value=2),
        delta_value=negative_delta_st,
    )
    @settings(max_examples=200)
    def test_no_price_stall_no_signal(
        self, support_cents: int, tick_distance: int, delta_value: float,
    ):
        """条件 3 不满足：无价格记录时不应生成信号"""
        support_price = _cents_to_price(support_cents)
        current_price = _cents_to_price(support_cents + tick_distance)

        engine = _make_engine()

        poc_state = engine._poc_calculator._get_state(STOCK)
        poc_state.last_poc_price = support_price

        dc_state = engine._delta_calculator._get_state(STOCK)
        dc_state.history.append(_delta(delta_value))

        # 不记录价格 → 无停滞数据
        now = time.time()

        result = asyncio.get_event_loop().run_until_complete(
            engine.evaluate_support_bounce(STOCK, current_price, now=now)
        )
        assert result is None, "价格未停滞时不应生成信号"

    # ── 必要性：条件 3 不满足（价格波动过大）→ 无信号 ────────────

    @given(
        support_cents=st.integers(min_value=500, max_value=100000),
        tick_distance=st.integers(min_value=0, max_value=2),
        delta_value=negative_delta_st,
        volatility_ticks=st.integers(min_value=3, max_value=20),
    )
    @settings(max_examples=200)
    def test_volatile_price_no_signal(
        self, support_cents: int, tick_distance: int,
        delta_value: float, volatility_ticks: int,
    ):
        """条件 3 不满足：价格波动 >= 2 Tick 时不应生成信号"""
        support_price = _cents_to_price(support_cents)
        current_price = _cents_to_price(support_cents + tick_distance)

        engine = _make_engine()

        poc_state = engine._poc_calculator._get_state(STOCK)
        poc_state.last_poc_price = support_price

        dc_state = engine._delta_calculator._get_state(STOCK)
        dc_state.history.append(_delta(delta_value))

        # 价格大幅波动（swing >= 3 Tick > stall_max_ticks=2 Tick）
        now = time.time()
        swing = volatility_ticks * TICK_SIZE
        for i in range(25):
            price = current_price if i % 2 == 0 else current_price + swing
            engine.record_price(STOCK, price, now - 5.0 + i * 0.2)

        result = asyncio.get_event_loop().run_until_complete(
            engine.evaluate_support_bounce(STOCK, current_price, now=now)
        )
        assert result is None, (
            f"价格波动 >= 2 Tick 时不应生成信号: 波动={volatility_ticks} Tick"
        )
