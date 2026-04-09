#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeltaCalculator 属性测试

使用 hypothesis 验证 Lee-Ready 简化版算法的方向分类正确性。

Feature: intraday-scalping-engine, Property 2: Delta 方向分类正确性（Lee-Ready 简化版）
**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
"""

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

from simple_trade.services.scalping.calculators.delta_calculator import DeltaCalculator
from simple_trade.services.scalping.models import TickData, TickDirection


# ── hypothesis 策略 ──────────────────────────────────────────────

# 正浮点数（用于价格），避免极端值导致浮点精度问题
price_st = st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False)

# 有效成交量（>= 100）
valid_volume_st = st.integers(min_value=100, max_value=10**7)

# 无效成交量（< 100）
invalid_volume_st = st.integers(min_value=0, max_value=99)

# 股票代码
stock_code_st = st.just("HK.00700")


# ── 辅助函数 ──────────────────────────────────────────────────────

def make_calculator(min_volume: int = 100) -> DeltaCalculator:
    """创建带 mock socket_manager 的 DeltaCalculator"""
    mock_sm = MagicMock()
    mock_sm.emit_to_all = AsyncMock()
    return DeltaCalculator(socket_manager=mock_sm, min_volume=min_volume)


def make_tick(
    price: float,
    volume: int,
    ask_price: float,
    bid_price: float,
    stock_code: str = "HK.00700",
) -> TickData:
    """创建测试用 TickData"""
    return TickData(
        stock_code=stock_code,
        price=price,
        volume=volume,
        direction=TickDirection.NEUTRAL,
        timestamp=1700000000000.0,
        ask_price=ask_price,
        bid_price=bid_price,
    )


# ── Property 2: Delta 方向分类正确性（Lee-Ready 简化版） ─────────
# Feature: intraday-scalping-engine, Property 2: Delta 方向分类正确性（Lee-Ready 简化版）
# **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**


class TestProperty2DeltaDirectionClassification:
    """Property 2: 对于任意成交量 >= 100 的 Tick 数据，
    Lee-Ready 简化版算法应正确分类成交方向。"""

    # ── 需求 2.2: 成交价 == Ask → 买入（正值） ──────────────────

    @given(
        bid=price_st,
        spread=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
        volume=valid_volume_st,
    )
    @settings(max_examples=200)
    def test_price_at_ask_classified_as_buy(self, bid: float, spread: float, volume: int):
        """成交价等于 Ask 时，应被记为正值（主动买入）"""
        ask = bid + spread
        assume(ask <= 10000.0)

        calc = make_calculator()
        tick = make_tick(price=ask, volume=volume, ask_price=ask, bid_price=bid)
        calc.on_tick("HK.00700", tick)

        state = calc._get_state("HK.00700")
        assert state.current_period.delta == volume, (
            f"成交价 == Ask 时 delta 应为 +{volume}，实际为 {state.current_period.delta}"
        )

    # ── 需求 2.3: 成交价 == Bid → 卖出（负值） ──────────────────

    @given(
        bid=price_st,
        spread=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
        volume=valid_volume_st,
    )
    @settings(max_examples=200)
    def test_price_at_bid_classified_as_sell(self, bid: float, spread: float, volume: int):
        """成交价等于 Bid 时，应被记为负值（主动卖出）"""
        ask = bid + spread
        assume(ask <= 10000.0)

        calc = make_calculator()
        tick = make_tick(price=bid, volume=volume, ask_price=ask, bid_price=bid)
        calc.on_tick("HK.00700", tick)

        state = calc._get_state("HK.00700")
        assert state.current_period.delta == -volume, (
            f"成交价 == Bid 时 delta 应为 -{volume}，实际为 {state.current_period.delta}"
        )

    # ── 需求 2.4: 成交价在 Bid/Ask 之间，更接近 Ask → 买入 ─────

    @given(
        bid=price_st,
        spread=st.floats(min_value=0.10, max_value=100.0, allow_nan=False, allow_infinity=False),
        ratio=st.floats(min_value=0.51, max_value=0.99, allow_nan=False, allow_infinity=False),
        volume=valid_volume_st,
    )
    @settings(max_examples=200)
    def test_price_closer_to_ask_classified_as_buy(
        self, bid: float, spread: float, ratio: float, volume: int
    ):
        """成交价在 Bid/Ask 之间且更接近 Ask 时，应被记为正值（买入）"""
        ask = bid + spread
        assume(ask <= 10000.0)
        # ratio > 0.5 表示更接近 Ask
        price = bid + spread * ratio

        calc = make_calculator()
        tick = make_tick(price=price, volume=volume, ask_price=ask, bid_price=bid)
        calc.on_tick("HK.00700", tick)

        state = calc._get_state("HK.00700")
        assert state.current_period.delta == volume, (
            f"更接近 Ask 时 delta 应为 +{volume}，实际为 {state.current_period.delta}"
        )

    # ── 需求 2.4: 成交价在 Bid/Ask 之间，更接近 Bid → 卖出 ─────

    @given(
        bid=price_st,
        spread=st.floats(min_value=0.10, max_value=100.0, allow_nan=False, allow_infinity=False),
        ratio=st.floats(min_value=0.01, max_value=0.49, allow_nan=False, allow_infinity=False),
        volume=valid_volume_st,
    )
    @settings(max_examples=200)
    def test_price_closer_to_bid_classified_as_sell(
        self, bid: float, spread: float, ratio: float, volume: int
    ):
        """成交价在 Bid/Ask 之间且更接近 Bid 时，应被记为负值（卖出）"""
        ask = bid + spread
        assume(ask <= 10000.0)
        # ratio < 0.5 表示更接近 Bid
        price = bid + spread * ratio

        calc = make_calculator()
        tick = make_tick(price=price, volume=volume, ask_price=ask, bid_price=bid)
        calc.on_tick("HK.00700", tick)

        state = calc._get_state("HK.00700")
        assert state.current_period.delta == -volume, (
            f"更接近 Bid 时 delta 应为 -{volume}，实际为 {state.current_period.delta}"
        )

    # ── 需求 2.4: 正好在中间 → Tick Test 回退（有 last_direction）

    @given(
        bid_cents=st.integers(min_value=100, max_value=500000),
        spread_cents=st.integers(min_value=2, max_value=10000).filter(lambda x: x % 2 == 0),
        volume=valid_volume_st,
        last_dir=st.sampled_from([TickDirection.BUY, TickDirection.SELL]),
    )
    @settings(max_examples=200)
    def test_midpoint_with_last_direction_follows_tick_test(
        self, bid_cents: int, spread_cents: int, volume: int, last_dir: TickDirection
    ):
        """成交价正好在 Bid/Ask 中间且有 last_direction 时，
        应参考上一笔方向（Tick Test 回退）。
        使用整数分（cents）构造价格，确保 mid 精确等距于 bid 和 ask。"""
        bid = bid_cents / 100.0
        spread = spread_cents / 100.0
        ask = bid + spread
        # 偶数 spread_cents 保证 mid 精确
        mid = bid + spread / 2.0

        # 验证 mid 确实精确等距
        assume(abs(ask - mid) - abs(mid - bid) == 0.0)

        calc = make_calculator()
        # 预设 last_direction
        calc._last_direction["HK.00700"] = last_dir

        tick = make_tick(price=mid, volume=volume, ask_price=ask, bid_price=bid)
        calc.on_tick("HK.00700", tick)

        state = calc._get_state("HK.00700")
        if last_dir == TickDirection.BUY:
            assert state.current_period.delta == volume, (
                f"Tick Test 回退 BUY 时 delta 应为 +{volume}，实际为 {state.current_period.delta}"
            )
        else:
            assert state.current_period.delta == -volume, (
                f"Tick Test 回退 SELL 时 delta 应为 -{volume}，实际为 {state.current_period.delta}"
            )

    # ── 需求 2.5: 无 last_direction → NEUTRAL，不计入 ──────────

    @given(
        bid_cents=st.integers(min_value=100, max_value=500000),
        spread_cents=st.integers(min_value=2, max_value=10000).filter(lambda x: x % 2 == 0),
        volume=valid_volume_st,
    )
    @settings(max_examples=200)
    def test_midpoint_no_last_direction_is_neutral(
        self, bid_cents: int, spread_cents: int, volume: int
    ):
        """成交价正好在 Bid/Ask 中间且无 last_direction 时，
        应标记为 NEUTRAL 且不计入净动量。
        使用整数分（cents）构造价格，确保 mid 精确等距于 bid 和 ask。"""
        bid = bid_cents / 100.0
        spread = spread_cents / 100.0
        ask = bid + spread
        mid = bid + spread / 2.0

        # 验证 mid 确实精确等距
        assume(abs(ask - mid) - abs(mid - bid) == 0.0)

        calc = make_calculator()
        # 确保无 last_direction
        assert "HK.00700" not in calc._last_direction

        tick = make_tick(price=mid, volume=volume, ask_price=ask, bid_price=bid)
        calc.on_tick("HK.00700", tick)

        state = calc._get_state("HK.00700")
        assert state.current_period.delta == 0.0, (
            f"NEUTRAL 时 delta 应为 0，实际为 {state.current_period.delta}"
        )
        assert state.current_period.volume == 0, (
            f"NEUTRAL 时 volume 应为 0，实际为 {state.current_period.volume}"
        )

    # ── 需求 2.1: 成交量 < 100 的 Tick 被忽略 ──────────────────

    @given(
        bid=price_st,
        spread=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
        volume=invalid_volume_st,
    )
    @settings(max_examples=200)
    def test_small_volume_tick_ignored(
        self, bid: float, spread: float, volume: int
    ):
        """成交量 < 100 的 Tick 不应影响 Delta 值"""
        ask = bid + spread
        assume(ask <= 10000.0)

        calc = make_calculator()
        # 即使成交价 == Ask（本应是买入），小成交量也应被忽略
        tick = make_tick(price=ask, volume=volume, ask_price=ask, bid_price=bid)
        calc.on_tick("HK.00700", tick)

        state = calc._get_state("HK.00700")
        assert state.current_period.delta == 0.0, (
            f"小成交量 Tick 不应影响 delta，实际为 {state.current_period.delta}"
        )
        assert state.current_period.volume == 0, (
            f"小成交量 Tick 不应影响 volume，实际为 {state.current_period.volume}"
        )

    # ── 综合属性: last_direction 更新正确性 ──────────────────────

    @given(
        bid=price_st,
        spread=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
        volume=valid_volume_st,
    )
    @settings(max_examples=200)
    def test_last_direction_updated_after_buy(
        self, bid: float, spread: float, volume: int
    ):
        """成交价 == Ask（买入）后，last_direction 应更新为 BUY"""
        ask = bid + spread
        assume(ask <= 10000.0)

        calc = make_calculator()
        tick = make_tick(price=ask, volume=volume, ask_price=ask, bid_price=bid)
        calc.on_tick("HK.00700", tick)

        assert calc._last_direction.get("HK.00700") == TickDirection.BUY

    @given(
        bid=price_st,
        spread=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
        volume=valid_volume_st,
    )
    @settings(max_examples=200)
    def test_last_direction_updated_after_sell(
        self, bid: float, spread: float, volume: int
    ):
        """成交价 == Bid（卖出）后，last_direction 应更新为 SELL"""
        ask = bid + spread
        assume(ask <= 10000.0)

        calc = make_calculator()
        tick = make_tick(price=bid, volume=volume, ask_price=ask, bid_price=bid)
        calc.on_tick("HK.00700", tick)

        assert calc._last_direction.get("HK.00700") == TickDirection.SELL

    @given(
        bid_cents=st.integers(min_value=100, max_value=500000),
        spread_cents=st.integers(min_value=2, max_value=10000).filter(lambda x: x % 2 == 0),
        volume=valid_volume_st,
    )
    @settings(max_examples=200)
    def test_neutral_does_not_overwrite_last_direction(
        self, bid_cents: int, spread_cents: int, volume: int
    ):
        """NEUTRAL 判定不应覆盖已有的 last_direction。
        使用整数分（cents）构造价格，确保 mid 精确等距于 bid 和 ask。"""
        bid = bid_cents / 100.0
        spread = spread_cents / 100.0
        ask = bid + spread
        mid = bid + spread / 2.0

        # 验证 mid 确实精确等距
        assume(abs(ask - mid) - abs(mid - bid) == 0.0)

        calc = make_calculator()
        # 先设置一个有效的 last_direction
        calc._last_direction["HK.00700"] = TickDirection.BUY

        # 发送一个中间价 Tick（会触发 Tick Test，方向为 BUY）
        tick = make_tick(price=mid, volume=volume, ask_price=ask, bid_price=bid)
        calc.on_tick("HK.00700", tick)

        # last_direction 应保持为 BUY（Tick Test 回退后方向仍为 BUY）
        assert calc._last_direction["HK.00700"] == TickDirection.BUY


# ── Property 3: Delta 周期累加不变量 ─────────────────────────────
# Feature: intraday-scalping-engine, Property 3: Delta 周期累加不变量
# **Validates: Requirements 2.4, 2.5, 2.6**


# ── 辅助策略：生成一组 Tick 序列 ─────────────────────────────────

def _tick_strategy():
    """生成单笔 Tick 的策略，bid/ask 使用整数分避免浮点精度问题"""
    return st.fixed_dictionaries({
        "bid_cents": st.integers(min_value=100, max_value=500000),
        "spread_cents": st.integers(min_value=2, max_value=10000),
        "price_ratio": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        "volume": st.integers(min_value=0, max_value=10**6),
    })


def _compute_expected_delta_and_volume(
    ticks_params: list[dict], min_volume: int = 100
) -> tuple[float, int]:
    """手动计算一组 Tick 的期望 Delta 和累计成交量

    模拟 Lee-Ready 简化版算法，与 DeltaCalculator 逻辑一致。
    返回 (expected_delta, expected_volume)。
    """
    expected_delta = 0.0
    expected_volume = 0
    last_direction = None  # 模拟 Tick Test 回退

    for params in ticks_params:
        bid = params["bid_cents"] / 100.0
        spread = params["spread_cents"] / 100.0
        ask = bid + spread
        price = bid + spread * params["price_ratio"]
        volume = params["volume"]

        if volume < min_volume:
            continue

        # Lee-Ready 简化版方向判定
        if price == ask:
            direction = TickDirection.BUY
        elif price == bid:
            direction = TickDirection.SELL
        else:
            mid = (ask + bid) / 2.0
            dist_to_ask = abs(price - ask)
            dist_to_bid = abs(price - bid)

            if dist_to_ask < dist_to_bid:
                direction = TickDirection.BUY
            elif dist_to_bid < dist_to_ask:
                direction = TickDirection.SELL
            else:
                # 正好在中间 → Tick Test
                if last_direction is not None and last_direction != TickDirection.NEUTRAL:
                    direction = last_direction
                else:
                    direction = TickDirection.NEUTRAL

        # 更新 last_direction
        if direction != TickDirection.NEUTRAL:
            last_direction = direction

        if direction == TickDirection.BUY:
            expected_delta += volume
            expected_volume += volume
        elif direction == TickDirection.SELL:
            expected_delta -= volume
            expected_volume += volume
        # NEUTRAL: 不计入

    return expected_delta, expected_volume


class TestProperty3DeltaPeriodAccumulationInvariant:
    """Property 3: 对于任意一组 Tick 数据序列，在一个累加周期结束时，
    输出的 Delta 值应等于该周期内所有有效 Tick（成交量 >= 100）的 Delta 代数和，
    累计成交量应等于所有有效 Tick 成交量之和。"""

    # ── 核心属性: 周期累加 Delta 等于各 Tick Delta 代数和 ────────

    @given(
        ticks_params=st.lists(
            _tick_strategy(),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=200)
    def test_flush_delta_equals_algebraic_sum(self, ticks_params: list[dict]):
        """flush_period 返回的 delta 应等于周期内所有有效 Tick 的 Delta 代数和"""
        import asyncio

        stock_code = "HK.00700"
        calc = make_calculator()

        # 喂入所有 Tick
        for params in ticks_params:
            bid = params["bid_cents"] / 100.0
            spread = params["spread_cents"] / 100.0
            ask = bid + spread
            price = bid + spread * params["price_ratio"]
            tick = make_tick(
                price=price,
                volume=params["volume"],
                ask_price=ask,
                bid_price=bid,
                stock_code=stock_code,
            )
            calc.on_tick(stock_code, tick)

        # 手动计算期望值
        expected_delta, expected_volume = _compute_expected_delta_and_volume(ticks_params)

        # flush 周期
        result = asyncio.get_event_loop().run_until_complete(
            calc.flush_period(stock_code)
        )

        if expected_volume == 0:
            # 没有有效 Tick 时，flush 可能返回 None（tick_count 可能为 0 或非 0）
            # 如果所有 Tick 都是 NEUTRAL（volume >= 100 但方向为 NEUTRAL），
            # tick_count > 0 但 delta=0, volume=0
            if result is None:
                return  # 没有任何有效 Tick 被处理
            assert result.delta == expected_delta
            assert result.volume == expected_volume
        else:
            assert result is not None, "有有效 Tick 时 flush_period 不应返回 None"
            assert result.delta == expected_delta, (
                f"Delta 不一致: 期望 {expected_delta}，实际 {result.delta}"
            )
            assert result.volume == expected_volume, (
                f"累计成交量不一致: 期望 {expected_volume}，实际 {result.volume}"
            )

    # ── 累计成交量等于所有有效 Tick 成交量之和 ────────────────────

    @given(
        ticks_params=st.lists(
            _tick_strategy(),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=200)
    def test_flush_volume_equals_valid_tick_sum(self, ticks_params: list[dict]):
        """flush_period 返回的 volume 应等于所有有效 Tick 成交量之和
        （仅计入方向为 BUY 或 SELL 的 Tick，NEUTRAL 不计入）"""
        import asyncio

        stock_code = "HK.00700"
        calc = make_calculator()

        for params in ticks_params:
            bid = params["bid_cents"] / 100.0
            spread = params["spread_cents"] / 100.0
            ask = bid + spread
            price = bid + spread * params["price_ratio"]
            tick = make_tick(
                price=price,
                volume=params["volume"],
                ask_price=ask,
                bid_price=bid,
                stock_code=stock_code,
            )
            calc.on_tick(stock_code, tick)

        _, expected_volume = _compute_expected_delta_and_volume(ticks_params)

        result = asyncio.get_event_loop().run_until_complete(
            calc.flush_period(stock_code)
        )

        if expected_volume == 0:
            if result is None:
                return
            assert result.volume == 0
        else:
            assert result is not None
            assert result.volume == expected_volume

    # ── flush 后周期重置，新周期从零开始 ─────────────────────────

    @given(
        ticks_params_1=st.lists(_tick_strategy(), min_size=1, max_size=20),
        ticks_params_2=st.lists(_tick_strategy(), min_size=1, max_size=20),
    )
    @settings(max_examples=200)
    def test_flush_resets_accumulator_for_next_period(
        self, ticks_params_1: list[dict], ticks_params_2: list[dict]
    ):
        """flush_period 后，新周期的累加应从零开始，
        第二次 flush 的结果仅反映第二批 Tick"""
        import asyncio

        stock_code = "HK.00700"
        calc = make_calculator()

        # 第一批 Tick
        for params in ticks_params_1:
            bid = params["bid_cents"] / 100.0
            spread = params["spread_cents"] / 100.0
            ask = bid + spread
            price = bid + spread * params["price_ratio"]
            tick = make_tick(
                price=price, volume=params["volume"],
                ask_price=ask, bid_price=bid, stock_code=stock_code,
            )
            calc.on_tick(stock_code, tick)

        # flush 第一个周期
        asyncio.get_event_loop().run_until_complete(calc.flush_period(stock_code))

        # 第二批 Tick
        for params in ticks_params_2:
            bid = params["bid_cents"] / 100.0
            spread = params["spread_cents"] / 100.0
            ask = bid + spread
            price = bid + spread * params["price_ratio"]
            tick = make_tick(
                price=price, volume=params["volume"],
                ask_price=ask, bid_price=bid, stock_code=stock_code,
            )
            calc.on_tick(stock_code, tick)

        # 第二次 flush 的期望值仅基于第二批 Tick
        # 注意：last_direction 跨周期保留，所以需要先模拟第一批来获取正确的 last_direction
        _, _ = _compute_expected_delta_and_volume(ticks_params_1)
        # 重新计算：需要考虑第一批 Tick 留下的 last_direction 状态
        # 完整模拟两批 Tick 的 last_direction 传递
        all_ticks = ticks_params_1 + ticks_params_2
        full_delta, full_volume = _compute_expected_delta_and_volume(all_ticks)
        first_delta, first_volume = _compute_expected_delta_and_volume(ticks_params_1)
        expected_delta_2 = full_delta - first_delta
        expected_volume_2 = full_volume - first_volume

        result2 = asyncio.get_event_loop().run_until_complete(
            calc.flush_period(stock_code)
        )

        if expected_volume_2 == 0:
            if result2 is None:
                return
            assert result2.delta == expected_delta_2
            assert result2.volume == expected_volume_2
        else:
            assert result2 is not None
            assert result2.delta == expected_delta_2, (
                f"第二周期 Delta 不一致: 期望 {expected_delta_2}，实际 {result2.delta}"
            )
            assert result2.volume == expected_volume_2, (
                f"第二周期 Volume 不一致: 期望 {expected_volume_2}，实际 {result2.volume}"
            )

    # ── 周期秒数正确传递到输出 ───────────────────────────────────

    @given(
        period=st.sampled_from([10, 60]),
        volume=valid_volume_st,
        bid=price_st,
        spread=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_flush_period_seconds_matches_config(
        self, period: int, volume: int, bid: float, spread: float
    ):
        """flush_period 输出的 period_seconds 应等于构造时配置的周期秒数（10 或 60）"""
        import asyncio

        ask = bid + spread
        assume(ask <= 10000.0)

        mock_sm = MagicMock()
        mock_sm.emit_to_all = AsyncMock()
        calc = DeltaCalculator(socket_manager=mock_sm, period_seconds=period)

        stock_code = "HK.00700"
        tick = make_tick(price=ask, volume=volume, ask_price=ask, bid_price=bid, stock_code=stock_code)
        calc.on_tick(stock_code, tick)

        result = asyncio.get_event_loop().run_until_complete(calc.flush_period(stock_code))
        assert result is not None
        assert result.period_seconds == period, (
            f"period_seconds 应为 {period}，实际为 {result.period_seconds}"
        )

    # ── flush 后通过 SocketManager 推送 DELTA_UPDATE 事件 ────────

    @given(
        volume=valid_volume_st,
        bid=price_st,
        spread=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_flush_emits_delta_update_event(
        self, volume: int, bid: float, spread: float
    ):
        """flush_period 应通过 SocketManager 推送 DELTA_UPDATE 事件"""
        import asyncio
        from simple_trade.websocket.events import SocketEvent

        ask = bid + spread
        assume(ask <= 10000.0)

        mock_sm = MagicMock()
        mock_sm.emit_to_all = AsyncMock()
        calc = DeltaCalculator(socket_manager=mock_sm)

        stock_code = "HK.00700"
        tick = make_tick(price=ask, volume=volume, ask_price=ask, bid_price=bid, stock_code=stock_code)
        calc.on_tick(stock_code, tick)

        asyncio.get_event_loop().run_until_complete(calc.flush_period(stock_code))

        mock_sm.emit_to_all.assert_called_once()
        call_args = mock_sm.emit_to_all.call_args
        assert call_args[0][0] == SocketEvent.DELTA_UPDATE
