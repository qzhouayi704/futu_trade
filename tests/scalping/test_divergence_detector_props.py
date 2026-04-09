"""
OrderFlowDivergenceDetector 属性测试

Feature: intraday-scalping-engine, Property 17 & 18: 订单流背离检测
**Validates: Requirements 13.1, 13.2, 13.5**
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from simple_trade.services.scalping.detectors.divergence_detector import (
    OrderFlowDivergenceDetector,
)
from simple_trade.services.scalping.models import (
    DeltaUpdateData,
    PriceLevelAction,
    PriceLevelData,
    PriceLevelSide,
    TickData,
    TickDirection,
    TrapAlertType,
)

STOCK = "HK.00700"


# ── 辅助函数 ──────────────────────────────────────────────────────

def _mock_sm():
    sm = MagicMock()
    sm.emit_to_all = AsyncMock()
    return sm


def _make_delta(delta: float) -> DeltaUpdateData:
    return DeltaUpdateData(
        stock_code=STOCK, delta=delta, volume=1000,
        timestamp="2024-01-01T10:00:00", period_seconds=10,
    )


def _make_tick(price: float, timestamp_ms: float) -> TickData:
    return TickData(
        stock_code=STOCK, price=price, volume=200,
        direction=TickDirection.BUY, timestamp=timestamp_ms,
        ask_price=price + 0.01, bid_price=price - 0.01,
    )


def _make_detector(
    cooldown_seconds: float = 15.0,
) -> tuple[OrderFlowDivergenceDetector, MagicMock, MagicMock]:
    """返回 (detector, mock_socket_manager, mock_delta_calculator)"""
    sm = _mock_sm()
    dc = MagicMock()
    dc.get_recent_deltas = MagicMock(return_value=[])
    detector = OrderFlowDivergenceDetector(
        socket_manager=sm, delta_calculator=dc,
        cooldown_seconds=cooldown_seconds,
    )
    return detector, sm, dc


def _setup_state(
    detector: OrderFlowDivergenceDetector,
    day_high: float,
    current_time_sec: float,
):
    """设置日内高点和当前时间"""
    state = detector._get_state(STOCK)
    state.day_high = day_high
    detector.on_tick(STOCK, _make_tick(day_high, current_time_sec * 1000.0))


def _setup_deltas(dc_mock: MagicMock, delta_values: list[float]):
    """配置 mock delta_calculator 返回指定的 Delta 值列表"""
    dc_mock.get_recent_deltas = MagicMock(
        return_value=[_make_delta(d) for d in delta_values]
    )


# ── hypothesis 策略 ──────────────────────────────────────────────

price_st = st.floats(
    min_value=1.0, max_value=5000.0,
    allow_nan=False, allow_infinity=False,
)
positive_delta_st = st.floats(
    min_value=10.0, max_value=50000.0,
    allow_nan=False, allow_infinity=False,
)
time_st = st.floats(
    min_value=1000.0, max_value=2000000000.0,
    allow_nan=False, allow_infinity=False,
)


# ── Property 17: 订单流背离检测 - 诱多条件 ────────────────────────
# Feature: intraday-scalping-engine, Property 17: 订单流背离检测 - 诱多条件
# **Validates: Requirements 13.1, 13.5**


class TestProperty17BullTrapDetection:
    """Property 17: 订单流背离检测 - 诱多条件

    验证诱多触发条件、不触发条件和冷却期行为。
    """

    # ── 子属性 1: 诱多触发 - Delta 为负值 ──
    @pytest.mark.asyncio
    @settings(max_examples=200)
    @given(
        day_high=price_st,
        delta_avg=positive_delta_st,
        current_time=time_st,
    )
    async def test_triggers_with_negative_delta(
        self, day_high, delta_avg, current_time,
    ):
        """价格创新高 + 当前 Delta 为负值 → 触发诱多"""
        detector, sm, dc = _make_detector()
        _setup_state(detector, day_high, current_time)

        neg_delta = -abs(delta_avg) * 0.5
        _setup_deltas(dc, [delta_avg] * 19 + [neg_delta])

        result = await detector.check_bull_trap(STOCK, day_high)

        assert result is not None
        assert result.trap_type == TrapAlertType.BULL_TRAP
        assert result.stock_code == STOCK
        assert result.current_price == day_high
        assert result.reference_price == day_high
        assert result.delta_value == neg_delta

    # ── 子属性 1b: 诱多触发 - Delta 低于均值 20% ──
    @pytest.mark.asyncio
    @settings(max_examples=200)
    @given(
        day_high=price_st,
        delta_avg=positive_delta_st,
        current_time=time_st,
    )
    async def test_triggers_with_low_delta(
        self, day_high, delta_avg, current_time,
    ):
        """价格创新高 + 当前 Delta 低于均值的 20% → 触发诱多"""
        detector, sm, dc = _make_detector()
        _setup_state(detector, day_high, current_time)

        low_delta = delta_avg * 0.1  # 确保低于 delta_avg * 0.2 阈值
        assume(low_delta >= 0)
        assume(low_delta < delta_avg * 0.2)

        _setup_deltas(dc, [delta_avg] * 19 + [low_delta])

        result = await detector.check_bull_trap(STOCK, day_high)

        assert result is not None
        assert result.trap_type == TrapAlertType.BULL_TRAP
        assert result.delta_value == low_delta

    # ── 子属性 1c: 诱多触发 - 价格高于日内高点 ──
    @pytest.mark.asyncio
    @settings(max_examples=200)
    @given(
        day_high=price_st,
        price_offset=st.floats(
            min_value=0.0, max_value=100.0,
            allow_nan=False, allow_infinity=False,
        ),
        current_time=time_st,
    )
    async def test_triggers_when_price_above_day_high(
        self, day_high, price_offset, current_time,
    ):
        """价格高于日内高点也算创新高 → 触发诱多"""
        detector, sm, dc = _make_detector()
        _setup_state(detector, day_high, current_time)

        current_price = day_high + price_offset
        assume(current_price >= day_high)
        _setup_deltas(dc, [1000.0] * 19 + [-500.0])

        result = await detector.check_bull_trap(STOCK, current_price)

        assert result is not None
        assert result.trap_type == TrapAlertType.BULL_TRAP
        assert result.current_price == current_price

    # ── 子属性 2: 诱多不触发 - 价格未创新高 ──
    @pytest.mark.asyncio
    @settings(max_examples=200)
    @given(
        day_high=st.floats(
            min_value=10.0, max_value=5000.0,
            allow_nan=False, allow_infinity=False,
        ),
        price_drop=st.floats(
            min_value=0.01, max_value=100.0,
            allow_nan=False, allow_infinity=False,
        ),
        current_time=time_st,
    )
    async def test_no_trigger_when_price_below_day_high(
        self, day_high, price_drop, current_time,
    ):
        """价格未创新高 → 不触发诱多"""
        detector, sm, dc = _make_detector()
        _setup_state(detector, day_high, current_time)
        _setup_deltas(dc, [1000.0] * 19 + [-500.0])

        current_price = day_high - price_drop
        assume(current_price > 0)
        assume(current_price < day_high)

        result = await detector.check_bull_trap(STOCK, current_price)
        assert result is None

    # ── 子属性 3: 诱多不触发 - Delta 正常 ──
    @pytest.mark.asyncio
    @settings(max_examples=200)
    @given(
        day_high=price_st,
        delta_avg=positive_delta_st,
        current_time=time_st,
    )
    async def test_no_trigger_when_delta_is_normal(
        self, day_high, delta_avg, current_time,
    ):
        """Delta >= 0 且 >= 均值 * 0.2 → 不触发诱多"""
        detector, sm, dc = _make_detector()
        _setup_state(detector, day_high, current_time)

        normal_delta = delta_avg * 0.5  # 50% > 20% 阈值
        assume(normal_delta >= 0)
        assume(normal_delta >= delta_avg * 0.2)

        _setup_deltas(dc, [delta_avg] * 19 + [normal_delta])

        result = await detector.check_bull_trap(STOCK, day_high)
        assert result is None

    # ── 子属性 4: 冷却期抑制 ──
    @pytest.mark.asyncio
    @settings(max_examples=200)
    @given(
        day_high=price_st,
        current_time=time_st,
        cooldown_offset=st.floats(
            min_value=0.1, max_value=14.9,
            allow_nan=False, allow_infinity=False,
        ),
    )
    async def test_cooldown_suppresses_second_alert(
        self, day_high, current_time, cooldown_offset,
    ):
        """诱多警报触发后 15 秒内再次调用返回 None"""
        detector, sm, dc = _make_detector(cooldown_seconds=15.0)
        _setup_state(detector, day_high, current_time)
        _setup_deltas(dc, [1000.0] * 19 + [-500.0])

        # 第一次触发
        result1 = await detector.check_bull_trap(STOCK, day_high)
        assert result1 is not None
        assert result1.trap_type == TrapAlertType.BULL_TRAP

        # 冷却期内更新时间
        new_time = current_time + cooldown_offset
        assume(new_time < current_time + 15.0)
        detector.on_tick(STOCK, _make_tick(day_high, new_time * 1000.0))

        # 第二次应被抑制
        result2 = await detector.check_bull_trap(STOCK, day_high)
        assert result2 is None

    # ── 子属性 4b: 冷却期过后可再次触发 ──
    @pytest.mark.asyncio
    @settings(max_examples=200)
    @given(
        day_high=price_st,
        current_time=st.floats(
            min_value=1000.0, max_value=1000000.0,
            allow_nan=False, allow_infinity=False,
        ),
        extra_time=st.floats(
            min_value=15.1, max_value=100.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    async def test_fires_again_after_cooldown_expires(
        self, day_high, current_time, extra_time,
    ):
        """冷却期过后可以再次触发诱多警报"""
        detector, sm, dc = _make_detector(cooldown_seconds=15.0)
        _setup_state(detector, day_high, current_time)
        _setup_deltas(dc, [1000.0] * 19 + [-500.0])

        result1 = await detector.check_bull_trap(STOCK, day_high)
        assert result1 is not None

        # 冷却期过后
        new_time = current_time + extra_time
        assume(new_time > current_time + 15.0)
        detector.on_tick(STOCK, _make_tick(day_high, new_time * 1000.0))

        result2 = await detector.check_bull_trap(STOCK, day_high)
        assert result2 is not None
        assert result2.trap_type == TrapAlertType.BULL_TRAP

    # ── 边界情况 ──
    @pytest.mark.asyncio
    async def test_no_trigger_when_no_deltas(self):
        """没有 Delta 数据时不触发诱多"""
        detector, sm, dc = _make_detector()
        _setup_state(detector, 100.0, 1000.0)
        dc.get_recent_deltas = MagicMock(return_value=[])

        result = await detector.check_bull_trap(STOCK, 100.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_trigger_when_day_high_not_set(self):
        """日内高点未设置（为 0）时不触发诱多"""
        detector, sm, dc = _make_detector()
        _setup_deltas(dc, [1000.0] * 19 + [-500.0])

        result = await detector.check_bull_trap(STOCK, 100.0)
        assert result is None

    @pytest.mark.asyncio
    @settings(max_examples=200)
    @given(day_high=price_st, current_time=time_st)
    async def test_trigger_emits_socket_event(self, day_high, current_time):
        """诱多触发时应通过 SocketManager 推送事件"""
        detector, sm, dc = _make_detector()
        _setup_state(detector, day_high, current_time)
        _setup_deltas(dc, [1000.0] * 19 + [-500.0])

        result = await detector.check_bull_trap(STOCK, day_high)
        assert result is not None
        sm.emit_to_all.assert_called()

# ── Property 18: 订单流背离检测 - 诱空条件 ────────────────────────
# Feature: intraday-scalping-engine, Property 18: 订单流背离检测 - 诱空条件
# **Validates: Requirements 13.2, 13.5**

def _make_support(price: float) -> PriceLevelData:
    """创建一条绿色支撑线"""
    return PriceLevelData(
        stock_code=STOCK, price=price, volume=5000,
        side=PriceLevelSide.SUPPORT, action=PriceLevelAction.CREATE,
        timestamp="2024-01-01T10:00:00")


def _feed_sell_ticks(detector, base_price: float, base_time_sec: float, count: int = 3):
    """注入卖方 Tick 构造 Absorption（同价格、卖方向、3 秒窗口内）"""
    for i in range(count):
        detector.on_tick(STOCK, TickData(
            stock_code=STOCK, price=base_price, volume=500,
            direction=TickDirection.SELL,
            timestamp=(base_time_sec + i * 0.5) * 1000.0,
            ask_price=base_price + 0.01, bid_price=base_price - 0.01))


class TestProperty18BearTrapDetection:
    """Property 18: 订单流背离检测 - 诱空条件

    验证诱空触发条件、不触发条件和冷却期行为。
    """

    # ── 子属性 1: 诱空触发 ──
    @pytest.mark.asyncio
    @settings(max_examples=200)
    @given(
        support_price=st.floats(min_value=10.0, max_value=5000.0, allow_nan=False, allow_infinity=False),
        drop_ticks=st.floats(min_value=0.01, max_value=2.99, allow_nan=False, allow_infinity=False),
        base_time=time_st,
    )
    async def test_triggers_when_conditions_met(self, support_price, drop_ticks, base_time):
        """价格跌破支撑线 < 3 Tick + Absorption → 触发诱空"""
        detector, sm, dc = _make_detector()
        current_price = support_price - drop_ticks * 0.01
        assume(current_price > 0)
        assume(0 < support_price - current_price <= 0.03)
        _feed_sell_ticks(detector, current_price, base_time, count=3)

        result = await detector.check_bear_trap(STOCK, current_price, [_make_support(support_price)])
        assert result is not None
        assert result.trap_type == TrapAlertType.BEAR_TRAP
        assert result.current_price == current_price
        assert result.reference_price == support_price
        assert result.sell_volume is not None and result.sell_volume > 0

    # ── 子属性 2: 无支撑线不触发 ──
    @pytest.mark.asyncio
    @settings(max_examples=100)
    @given(price=price_st, base_time=time_st)
    async def test_no_trigger_without_support(self, price, base_time):
        """无 SUPPORT 类型支撑线 → 返回 None"""
        detector, sm, dc = _make_detector()
        _feed_sell_ticks(detector, price, base_time)
        result = await detector.check_bear_trap(STOCK, price, [])
        assert result is None

    # ── 子属性 3: 价格未跌破支撑不触发 ──
    @pytest.mark.asyncio
    @settings(max_examples=200)
    @given(
        support_price=st.floats(min_value=10.0, max_value=5000.0, allow_nan=False, allow_infinity=False),
        above_offset=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        base_time=time_st,
    )
    async def test_no_trigger_when_price_above_support(self, support_price, above_offset, base_time):
        """价格 >= 支撑价 → 不触发诱空"""
        detector, sm, dc = _make_detector()
        _feed_sell_ticks(detector, support_price + above_offset, base_time)
        result = await detector.check_bear_trap(
            STOCK, support_price + above_offset, [_make_support(support_price)])
        assert result is None

    # ── 子属性 4: 无 Absorption 不触发 ──
    @pytest.mark.asyncio
    @settings(max_examples=200)
    @given(
        support_price=st.floats(min_value=50.0, max_value=5000.0, allow_nan=False, allow_infinity=False),
        base_time=time_st,
    )
    async def test_no_trigger_without_absorption(self, support_price, base_time):
        """价格跌破支撑但价格波动 >= 2 Tick → 不触发"""
        detector, sm, dc = _make_detector()
        cp = support_price - 0.02
        for i, p in enumerate([cp, cp + 0.03]):  # 波动 0.03 >= 2 Tick
            detector.on_tick(STOCK, TickData(
                stock_code=STOCK, price=p, volume=500, direction=TickDirection.SELL,
                timestamp=(base_time + i * 0.5) * 1000.0,
                ask_price=p + 0.01, bid_price=p - 0.01))
        result = await detector.check_bear_trap(STOCK, cp, [_make_support(support_price)])
        assert result is None

    # ── 子属性 5: 冷却期抑制与恢复 ──
    @pytest.mark.asyncio
    @settings(max_examples=200)
    @given(
        support_price=st.floats(min_value=10.0, max_value=5000.0, allow_nan=False, allow_infinity=False),
        base_time=st.floats(min_value=1000.0, max_value=1000000.0, allow_nan=False, allow_infinity=False),
    )
    async def test_cooldown_suppresses_second_alert(self, support_price, base_time):
        """诱空触发后 15 秒内返回 None，冷却期后可再次触发"""
        detector, sm, dc = _make_detector(cooldown_seconds=15.0)
        current_price = support_price - 0.02
        assume(current_price > 0)
        _feed_sell_ticks(detector, current_price, base_time, count=3)
        r1 = await detector.check_bear_trap(STOCK, current_price, [_make_support(support_price)])
        assert r1 is not None
        # 冷却期内（+5 秒）
        _feed_sell_ticks(detector, current_price, base_time + 5.0, count=3)
        r2 = await detector.check_bear_trap(STOCK, current_price, [_make_support(support_price)])
        assert r2 is None
        # 冷却期后（+16 秒）
        _feed_sell_ticks(detector, current_price, base_time + 16.0, count=3)
        r3 = await detector.check_bear_trap(STOCK, current_price, [_make_support(support_price)])
        assert r3 is not None
        assert r3.trap_type == TrapAlertType.BEAR_TRAP
