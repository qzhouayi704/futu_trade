#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StopLossMonitor 属性测试

使用 hypothesis 验证止损提示触发条件的正确性。

Feature: intraday-scalping-engine, Property 25: 止损提示触发条件
**Validates: Requirements 18.1, 18.2, 18.3, 18.4, 18.7**
"""

import os
import sys
from unittest.mock import MagicMock, AsyncMock

import pytest
from hypothesis import given, settings, assume, strategies as st

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ),
)

from simple_trade.services.scalping.detectors.stop_loss_monitor import StopLossMonitor
from simple_trade.services.scalping.models import (
    ScalpingSignalData,
    ScalpingSignalType,
    TickData,
    TickDirection,
)


# ── 常量 ──────────────────────────────────────────────────────────

STOCK = "HK.00700"
BASE_MS = 1705282260000.0  # 开盘后 1 分钟的时间戳（毫秒）


# ── hypothesis 策略 ──────────────────────────────────────────────

# 价格策略：正浮点数，避免极端值
price_st = st.floats(
    min_value=1.0, max_value=10000.0,
    allow_nan=False, allow_infinity=False,
)

# 成交量策略
volume_st = st.integers(min_value=100, max_value=100_000)

# 时间戳策略（毫秒）
timestamp_st = st.floats(
    min_value=BASE_MS,
    max_value=BASE_MS + 3_600_000,  # 1 小时内
    allow_nan=False, allow_infinity=False,
)


# ── 辅助函数 ──────────────────────────────────────────────────────

def _mock_sm():
    """创建 mock socket_manager"""
    sm = MagicMock()
    sm.emit_to_all = AsyncMock()
    return sm


def make_signal(
    signal_type: ScalpingSignalType,
    trigger_price: float,
    support_price: float | None = None,
) -> ScalpingSignalData:
    """创建测试用入场信号"""
    return ScalpingSignalData(
        stock_code=STOCK,
        signal_type=signal_type,
        trigger_price=trigger_price,
        support_price=support_price,
        conditions=["test"],
        timestamp="2026-01-01T00:00:00",
    )


def make_tick(
    price: float,
    volume: int = 100,
    timestamp_ms: float = BASE_MS,
) -> TickData:
    """创建测试用 TickData"""
    return TickData(
        stock_code=STOCK,
        price=price,
        volume=volume,
        direction=TickDirection.BUY,
        timestamp=timestamp_ms,
        ask_price=price + 0.01,
        bid_price=price - 0.01,
    )


# ══════════════════════════════════════════════════════════════════
# Property 25: 止损提示触发条件
# **Validates: Requirements 18.1, 18.2, 18.3, 18.4, 18.7**
# ══════════════════════════════════════════════════════════════════


class TestProperty25_BreakoutLongStop:
    """子属性 1: 突破做多止损触发
    breakout_long 信号后，价格回落到 trigger_price 以下 → 触发止损，
    持仓被移除。
    **Validates: Requirements 18.1, 18.2**
    """

    @given(
        trigger_price=price_st,
        drop_ratio=st.floats(
            min_value=0.001, max_value=0.5,
            allow_nan=False, allow_infinity=False,
        ),
        volume=volume_st,
    )
    @settings(max_examples=200)
    def test_breakout_long_stop_triggered(
        self, trigger_price: float, drop_ratio: float, volume: int
    ):
        """价格跌破突破价 → 持仓移除，止损触发"""
        monitor = StopLossMonitor(socket_manager=_mock_sm())

        signal = make_signal(
            ScalpingSignalType.BREAKOUT_LONG, trigger_price
        )
        monitor.on_signal(STOCK, signal)

        # 确认持仓已记录
        positions_before = monitor.get_active_positions(STOCK)
        assert len(positions_before) == 1, "信号后应有 1 个活跃持仓"
        assert positions_before[0]["stop_price"] == trigger_price

        # 价格跌破突破价
        drop_price = trigger_price * (1 - drop_ratio)
        assume(drop_price < trigger_price)
        tick = make_tick(price=drop_price, volume=volume)
        monitor.on_tick(STOCK, tick)

        # 持仓应被移除
        positions_after = monitor.get_active_positions(STOCK)
        assert len(positions_after) == 0, (
            "止损触发后持仓应被移除"
        )


class TestProperty25_SupportLongStop:
    """子属性 2: 支撑低吸止损触发
    support_long 信号后（带 support_price），价格跌破 support_price → 触发止损，
    持仓被移除。
    **Validates: Requirements 18.3, 18.4**
    """

    @given(
        trigger_price=price_st,
        support_offset=st.floats(
            min_value=0.01, max_value=100.0,
            allow_nan=False, allow_infinity=False,
        ),
        drop_ratio=st.floats(
            min_value=0.001, max_value=0.5,
            allow_nan=False, allow_infinity=False,
        ),
        volume=volume_st,
    )
    @settings(max_examples=200)
    def test_support_long_stop_triggered(
        self,
        trigger_price: float,
        support_offset: float,
        drop_ratio: float,
        volume: int,
    ):
        """价格跌破支撑位 → 持仓移除，止损触发"""
        # support_price 低于 trigger_price
        support_price = trigger_price - support_offset
        assume(support_price > 0)

        monitor = StopLossMonitor(socket_manager=_mock_sm())

        signal = make_signal(
            ScalpingSignalType.SUPPORT_LONG,
            trigger_price,
            support_price=support_price,
        )
        monitor.on_signal(STOCK, signal)

        positions_before = monitor.get_active_positions(STOCK)
        assert len(positions_before) == 1
        assert positions_before[0]["stop_price"] == support_price

        # 价格跌破支撑位
        drop_price = support_price * (1 - drop_ratio)
        assume(drop_price < support_price)
        tick = make_tick(price=drop_price, volume=volume)
        monitor.on_tick(STOCK, tick)

        positions_after = monitor.get_active_positions(STOCK)
        assert len(positions_after) == 0, (
            "支撑位被破后持仓应被移除"
        )


class TestProperty25_NoStopAbovePrice:
    """子属性 3: 价格高于止损价时不触发
    价格始终高于 stop_price → 持仓保持活跃，不触发止损。
    **Validates: Requirements 18.1, 18.2, 18.3, 18.4**
    """

    @given(
        trigger_price=price_st,
        above_ratio=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
        n_ticks=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=200)
    def test_no_stop_when_price_above(
        self, trigger_price: float, above_ratio: float, n_ticks: int
    ):
        """价格 >= stop_price 时持仓保持活跃"""
        monitor = StopLossMonitor(socket_manager=_mock_sm())

        signal = make_signal(
            ScalpingSignalType.BREAKOUT_LONG, trigger_price
        )
        monitor.on_signal(STOCK, signal)

        # 发送多笔价格 >= trigger_price 的 Tick
        safe_price = trigger_price + (trigger_price * above_ratio)
        assume(safe_price >= trigger_price)

        ts = BASE_MS
        for _ in range(n_ticks):
            tick = make_tick(price=safe_price, timestamp_ms=ts)
            monitor.on_tick(STOCK, tick)
            ts += 1000

        positions = monitor.get_active_positions(STOCK)
        assert len(positions) == 1, (
            "价格未跌破止损价时持仓应保持活跃"
        )


class TestProperty25_SingleAlertPerSignal:
    """子属性 4: 同一信号仅触发一次止损
    止损触发后持仓被移除，后续低于止损价的 Tick 不再触发。
    **Validates: Requirements 18.7**
    """

    @given(
        trigger_price=price_st,
        drop_ratio=st.floats(
            min_value=0.001, max_value=0.5,
            allow_nan=False, allow_infinity=False,
        ),
        n_extra_ticks=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=200)
    def test_single_alert_per_signal(
        self, trigger_price: float, drop_ratio: float, n_extra_ticks: int
    ):
        """止损触发后，后续 Tick 不再触发同一信号的止损"""
        sm = _mock_sm()
        monitor = StopLossMonitor(socket_manager=sm)

        signal = make_signal(
            ScalpingSignalType.BREAKOUT_LONG, trigger_price
        )
        monitor.on_signal(STOCK, signal)

        # 第一笔跌破 → 触发止损
        drop_price = trigger_price * (1 - drop_ratio)
        assume(drop_price < trigger_price)
        tick = make_tick(price=drop_price)
        monitor.on_tick(STOCK, tick)

        # 持仓已移除
        assert len(monitor.get_active_positions(STOCK)) == 0

        # 后续多笔低价 Tick → 不应再有持仓变化
        ts = BASE_MS + 1000
        for _ in range(n_extra_ticks):
            tick = make_tick(
                price=drop_price * 0.9, timestamp_ms=ts
            )
            monitor.on_tick(STOCK, tick)
            ts += 1000

        # 仍然没有活跃持仓
        assert len(monitor.get_active_positions(STOCK)) == 0, (
            "止损触发后不应再有活跃持仓"
        )


class TestProperty25_ResetClearsPositions:
    """子属性 5: reset 清除所有持仓
    调用 reset 后，该股票的所有活跃持仓应被清除。
    **Validates: Requirements 18.7**
    """

    @given(
        n_signals=st.integers(min_value=1, max_value=10),
        trigger_price=price_st,
    )
    @settings(max_examples=200)
    def test_reset_clears_positions(
        self, n_signals: int, trigger_price: float
    ):
        """reset 后活跃持仓列表为空"""
        monitor = StopLossMonitor(socket_manager=_mock_sm())

        # 添加多个信号
        for i in range(n_signals):
            price = trigger_price + i * 0.1
            signal = make_signal(
                ScalpingSignalType.BREAKOUT_LONG, price
            )
            monitor.on_signal(STOCK, signal)

        assert len(monitor.get_active_positions(STOCK)) == n_signals

        monitor.reset(STOCK)

        assert len(monitor.get_active_positions(STOCK)) == 0, (
            "reset 后应无活跃持仓"
        )
