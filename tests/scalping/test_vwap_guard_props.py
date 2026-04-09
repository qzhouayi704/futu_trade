"""
VwapExtensionGuard 属性测试

Feature: intraday-scalping-engine
Property 21: VWAP 计算正确性（全天累计）
Property 22: VWAP 超限与恢复触发正确性

**Validates: Requirements 16.1, 16.3, 16.5**
"""

import math
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume, strategies as st

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ),
)

from simple_trade.services.scalping.detectors.vwap_guard import VwapExtensionGuard
from simple_trade.services.scalping.models import (
    TickData,
    TickDirection,
    VwapExtensionAlertData,
    VwapExtensionClearData,
)

STOCK = "HK.00700"
BASE_MS = 1_700_000_000_000.0  # 合理的 Unix 毫秒基准时间戳


# ── 辅助函数 ──────────────────────────────────────────────────────


def _mock_sm():
    sm = MagicMock()
    sm.emit_to_all = AsyncMock()
    return sm


def make_tick(
    price: float,
    volume: int,
    timestamp_ms: float,
    stock_code: str = STOCK,
) -> TickData:
    return TickData(
        stock_code=stock_code,
        price=price,
        volume=volume,
        direction=TickDirection.BUY,
        timestamp=timestamp_ms,
        ask_price=price + 0.01,
        bid_price=price - 0.01,
    )


def _make_guard(**kwargs) -> VwapExtensionGuard:
    """创建 VwapExtensionGuard 实例，使用 mock SocketManager"""
    sm = _mock_sm()
    defaults = dict(
        socket_manager=sm,
        atr_multiplier_low=1.5,
        atr_multiplier_high=2.0,
        recovery_ratio=0.8,
    )
    defaults.update(kwargs)
    return VwapExtensionGuard(**defaults)


# ── Hypothesis 策略 ───────────────────────────────────────────────

# 正数价格
st_price = st.floats(min_value=0.1, max_value=5000.0, allow_nan=False, allow_infinity=False)

# 正整数成交量
st_volume = st.integers(min_value=1, max_value=1_000_000)

# Tick 列表（至少 1 笔，价格和成交量均为正数）
st_tick_list = st.lists(
    st.tuples(st_price, st_volume),
    min_size=1,
    max_size=50,
)


# ══════════════════════════════════════════════════════════════════
# Property 21: VWAP 计算正确性（全天累计）
# **Validates: Requirements 16.1**
# ══════════════════════════════════════════════════════════════════


class TestProperty21VwapCalculation:
    """VWAP = sum(price_i * volume_i) / sum(volume_i)，全天累计"""

    @settings(max_examples=200)
    @given(ticks=st_tick_list)
    def test_vwap_matches_manual_calculation(self, ticks: list[tuple[float, int]]):
        """VWAP 应等于手动计算的 sum(price*volume)/sum(volume)"""
        guard = _make_guard()

        expected_spv = 0.0
        expected_sv = 0
        for i, (price, volume) in enumerate(ticks):
            ts = BASE_MS + i * 100  # 同一分钟内
            guard.on_tick(STOCK, make_tick(price, volume, ts))
            expected_spv += price * volume
            expected_sv += volume

        vwap = guard.calculate_vwap(STOCK)
        assert vwap is not None
        expected_vwap = expected_spv / expected_sv
        assert math.isclose(vwap, expected_vwap, rel_tol=1e-9), (
            f"VWAP={vwap}, 期望={expected_vwap}"
        )

    @settings(max_examples=200)
    @given(ticks=st_tick_list)
    def test_vwap_returns_none_after_reset(self, ticks: list[tuple[float, int]]):
        """reset 后 VWAP 应返回 None"""
        guard = _make_guard()

        for i, (price, volume) in enumerate(ticks):
            guard.on_tick(STOCK, make_tick(price, volume, BASE_MS + i * 100))

        # reset 前有值
        assert guard.calculate_vwap(STOCK) is not None

        guard.reset(STOCK)
        assert guard.calculate_vwap(STOCK) is None

    @settings(max_examples=200)
    @given(ticks=st_tick_list)
    def test_vwap_bounded_by_price_range(self, ticks: list[tuple[float, int]]):
        """VWAP 应始终在 [min(prices), max(prices)] 范围内（允许浮点误差）"""
        guard = _make_guard()

        prices = []
        for i, (price, volume) in enumerate(ticks):
            guard.on_tick(STOCK, make_tick(price, volume, BASE_MS + i * 100))
            prices.append(price)

        vwap = guard.calculate_vwap(STOCK)
        assert vwap is not None
        # 浮点运算可能产生微小误差，使用 rel_tol 容差
        lo, hi = min(prices), max(prices)
        assert (vwap >= lo or math.isclose(vwap, lo, rel_tol=1e-9)) and \
               (vwap <= hi or math.isclose(vwap, hi, rel_tol=1e-9)), (
            f"VWAP={vwap} 不在 [{lo}, {hi}] 范围内"
        )

    @settings(max_examples=200)
    @given(
        price=st_price,
        volume=st_volume,
    )
    def test_zero_volume_tick_does_not_change_vwap(self, price: float, volume: int):
        """volume=0 的 Tick 不应改变 VWAP"""
        guard = _make_guard()

        # 先喂一笔正常 Tick
        guard.on_tick(STOCK, make_tick(price, volume, BASE_MS))
        vwap_before = guard.calculate_vwap(STOCK)
        assert vwap_before is not None

        # 喂一笔 volume=0 的 Tick（不同价格）
        different_price = price + 100.0
        zero_tick = make_tick(different_price, 0, BASE_MS + 100)
        guard.on_tick(STOCK, zero_tick)

        vwap_after = guard.calculate_vwap(STOCK)
        assert vwap_after is not None
        assert math.isclose(vwap_before, vwap_after, rel_tol=1e-12), (
            f"volume=0 的 Tick 不应改变 VWAP: before={vwap_before}, after={vwap_after}"
        )


# ══════════════════════════════════════════════════════════════════
# Property 22: VWAP 超限与恢复触发正确性
# **Validates: Requirements 16.3, 16.5**
# ══════════════════════════════════════════════════════════════════


def _build_guard_with_atr(
    atr_multiplier_high: float = 2.0,
    recovery_ratio: float = 0.8,
) -> VwapExtensionGuard:
    """创建一个已有足够 ATR 数据的 guard 实例。

    喂入跨越多个分钟的 Tick，使 completed_bars >= 2，
    从而 calculate_atr 能返回有效值。
    """
    guard = _make_guard(
        atr_multiplier_high=atr_multiplier_high,
        recovery_ratio=recovery_ratio,
    )

    # 构建 3 根 1 分钟 K 线（每根 K 线在不同分钟）
    # 分钟 0: high=100.5, low=99.5, close=100.0
    # 分钟 1: high=101.0, low=99.0, close=100.5
    # 分钟 2: high=100.8, low=99.2, close=100.0
    bar_data = [
        # (price, volume, minute_offset_sec)
        (99.5, 100, 0),
        (100.5, 100, 10),
        (100.0, 100, 50),
        # 分钟 1
        (99.0, 100, 60),
        (101.0, 100, 70),
        (100.5, 100, 110),
        # 分钟 2
        (99.2, 100, 120),
        (100.8, 100, 130),
        (100.0, 100, 170),
    ]
    for price, vol, offset_sec in bar_data:
        ts = BASE_MS + offset_sec * 1000
        guard.on_tick(STOCK, make_tick(price, vol, ts))

    return guard


class TestProperty22AlertTrigger:
    """当 deviation > ATR * atr_multiplier_high 且未处于超限状态时，
    应返回 VwapExtensionAlertData"""

    @settings(max_examples=200)
    @given(
        extra_deviation=st.floats(
            min_value=0.01, max_value=50.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_alert_when_deviation_exceeds_threshold(self, extra_deviation: float):
        """偏离超过阈值时应触发 ALERT"""
        guard = _build_guard_with_atr(atr_multiplier_high=2.0)

        vwap = guard.calculate_vwap(STOCK)
        atr = guard.calculate_atr(STOCK)
        assert vwap is not None and atr is not None and atr > 0

        threshold = atr * 2.0
        # 构造一个偏离超过阈值的价格
        extreme_price = vwap + threshold + extra_deviation

        result = guard.check_extension(STOCK, extreme_price)
        assert isinstance(result, VwapExtensionAlertData), (
            f"偏离={abs(extreme_price - vwap):.4f} > 阈值={threshold:.4f}，"
            f"应返回 ALERT，实际返回 {type(result)}"
        )
        assert result.stock_code == STOCK
        assert result.vwap_value == vwap


class TestProperty22ClearTrigger:
    """当 deviation < ATR * atr_multiplier_high * recovery_ratio
    且处于超限状态时，应返回 VwapExtensionClearData"""

    @settings(max_examples=200)
    @given(
        recovery_offset=st.floats(
            min_value=0.001, max_value=10.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_clear_when_deviation_below_recovery_threshold(self, recovery_offset: float):
        """偏离回落至阈值 * recovery_ratio 以下时应触发 CLEAR"""
        guard = _build_guard_with_atr(atr_multiplier_high=2.0, recovery_ratio=0.8)

        vwap = guard.calculate_vwap(STOCK)
        atr = guard.calculate_atr(STOCK)
        assert vwap is not None and atr is not None and atr > 0

        threshold = atr * 2.0
        recovery_threshold = threshold * 0.8

        # 先触发 ALERT
        extreme_price = vwap + threshold + 1.0
        alert = guard.check_extension(STOCK, extreme_price)
        assert isinstance(alert, VwapExtensionAlertData)

        # 价格回落至 recovery_threshold 以下
        close_price = vwap + max(recovery_threshold - recovery_offset, 0.0)
        actual_deviation = abs(close_price - vwap)
        assume(actual_deviation < recovery_threshold)

        result = guard.check_extension(STOCK, close_price)
        assert isinstance(result, VwapExtensionClearData), (
            f"偏离={actual_deviation:.4f} < 恢复阈值={recovery_threshold:.4f}，"
            f"应返回 CLEAR，实际返回 {type(result)}"
        )
        assert result.stock_code == STOCK


class TestProperty22NoDuplicateAlert:
    """已处于超限状态时，后续检查偏离仍超阈值应返回 None（不重复报警）"""

    @settings(max_examples=200)
    @given(
        extra1=st.floats(
            min_value=0.01, max_value=20.0,
            allow_nan=False, allow_infinity=False,
        ),
        extra2=st.floats(
            min_value=0.01, max_value=20.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_no_duplicate_alert_when_already_extended(
        self, extra1: float, extra2: float,
    ):
        """已超限后再次检查仍超限，应返回 None"""
        guard = _build_guard_with_atr(atr_multiplier_high=2.0)

        vwap = guard.calculate_vwap(STOCK)
        atr = guard.calculate_atr(STOCK)
        assert vwap is not None and atr is not None and atr > 0

        threshold = atr * 2.0

        # 第一次超限 → ALERT
        price1 = vwap + threshold + extra1
        result1 = guard.check_extension(STOCK, price1)
        assert isinstance(result1, VwapExtensionAlertData)

        # 第二次仍超限 → None（不重复）
        price2 = vwap + threshold + extra2
        result2 = guard.check_extension(STOCK, price2)
        assert result2 is None, (
            "已处于超限状态时，后续超限检查应返回 None"
        )


class TestProperty22ReAlertAfterClear:
    """CLEAR 后如果偏离再次超过阈值，应触发新的 ALERT"""

    @settings(max_examples=200)
    @given(
        extra=st.floats(
            min_value=0.01, max_value=20.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_new_alert_after_clear(self, extra: float):
        """CLEAR 后再次超限应触发新 ALERT"""
        guard = _build_guard_with_atr(atr_multiplier_high=2.0, recovery_ratio=0.8)

        vwap = guard.calculate_vwap(STOCK)
        atr = guard.calculate_atr(STOCK)
        assert vwap is not None and atr is not None and atr > 0

        threshold = atr * 2.0

        # 第一次超限 → ALERT
        alert1 = guard.check_extension(STOCK, vwap + threshold + 1.0)
        assert isinstance(alert1, VwapExtensionAlertData)

        # 回落 → CLEAR
        clear = guard.check_extension(STOCK, vwap)
        assert isinstance(clear, VwapExtensionClearData)

        # 再次超限 → 新 ALERT
        alert2 = guard.check_extension(STOCK, vwap + threshold + extra)
        assert isinstance(alert2, VwapExtensionAlertData), (
            "CLEAR 后再次超限应触发新的 ALERT"
        )
