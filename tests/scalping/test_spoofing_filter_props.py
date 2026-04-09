#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SpoofingFilter 属性测试

使用 hypothesis 验证巨单检测阈值和巨单生命周期状态转换。

Feature: intraday-scalping-engine, Property 6: 巨单检测阈值
Feature: intraday-scalping-engine, Property 7: 巨单生命周期状态转换
**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**
"""

import asyncio
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

from simple_trade.services.scalping.detectors.spoofing_filter import SpoofingFilter
from simple_trade.services.scalping.models import (
    OrderBookData,
    OrderBookLevel,
    PriceLevelAction,
    PriceLevelSide,
)
from simple_trade.websocket.events import SocketEvent


# ── 常量 ──────────────────────────────────────────────────────

STOCK = "HK.00700"
TICK_SIZE = 0.01
BASE_TS_S = 1000.0  # 基准时间戳（秒）


# ── hypothesis 策略 ──────────────────────────────────────────────

# 正常挂单量（用于建立基线）
normal_volume_st = st.integers(min_value=50, max_value=500)

# 基线快照数量
baseline_count_st = st.integers(min_value=3, max_value=20)

# 巨单倍数（超过阈值的额外倍数）
extra_multiplier_st = st.floats(
    min_value=1.0, max_value=5.0,
    allow_nan=False, allow_infinity=False,
)

# 不足阈值的比例
below_ratio_st = st.floats(
    min_value=0.1, max_value=0.95,
    allow_nan=False, allow_infinity=False,
)

# 价格策略
price_st = st.floats(
    min_value=1.0, max_value=1000.0,
    allow_nan=False, allow_infinity=False,
)

# 存活时间策略（秒）
survive_time_st = st.floats(
    min_value=0.1, max_value=20.0,
    allow_nan=False, allow_infinity=False,
)


# ── 辅助函数 ──────────────────────────────────────────────────────

def make_level(
    price: float, volume: int, order_count: int = 1
) -> OrderBookLevel:
    return OrderBookLevel(price=price, volume=volume, order_count=order_count)


def make_order_book(
    ask_levels: list[OrderBookLevel],
    bid_levels: list[OrderBookLevel],
    timestamp_s: float,
    stock_code: str = STOCK,
) -> OrderBookData:
    """创建测试用 OrderBookData，timestamp_s 为秒，内部转毫秒"""
    return OrderBookData(
        stock_code=stock_code,
        ask_levels=ask_levels,
        bid_levels=bid_levels,
        timestamp=timestamp_s * 1000.0,
    )


def make_filter(
    volume_multiplier: float = 5.0,
    survive_seconds_min: float = 3.0,
    survive_seconds_max: float = 5.0,
    history_window_seconds: float = 60.0,
    proximity_ticks: int = 5,
    tick_size: float = TICK_SIZE,
) -> tuple[SpoofingFilter, MagicMock]:
    """创建带 mock socket_manager 的 SpoofingFilter"""
    mock_sm = MagicMock()
    mock_sm.emit_to_all = AsyncMock()
    sf = SpoofingFilter(
        socket_manager=mock_sm,
        volume_multiplier=volume_multiplier,
        survive_seconds_min=survive_seconds_min,
        survive_seconds_max=survive_seconds_max,
        history_window_seconds=history_window_seconds,
        proximity_ticks=proximity_ticks,
        tick_size=tick_size,
    )
    return sf, mock_sm


async def build_baseline(
    sf: SpoofingFilter,
    ask_price: float,
    bid_price: float,
    normal_vol: int,
    count: int,
    start_ts_s: float = BASE_TS_S,
) -> float:
    """发送多次正常挂单量的 OrderBook 来建立历史均值基线。

    返回最后一次快照的时间戳（秒）。
    """
    for i in range(count):
        ob = make_order_book(
            ask_levels=[make_level(ask_price, normal_vol)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=start_ts_s + i,
        )
        await sf.on_order_book(STOCK, ob)
    return start_ts_s + count - 1


def get_emit_events(mock_sm: MagicMock) -> list[tuple]:
    """从 mock socket_manager 中提取所有 emit_to_all 调用"""
    return [call.args for call in mock_sm.emit_to_all.call_args_list]


def get_events_by_type(
    mock_sm: MagicMock, event_type: SocketEvent
) -> list[dict]:
    """获取指定类型的所有推送事件数据"""
    return [
        args[1] for args in get_emit_events(mock_sm)
        if args[0] == event_type
    ]


# ── Property 6: 巨单检测阈值 ────────────────────────────────────
# Feature: intraday-scalping-engine, Property 6: 巨单检测阈值
# **Validates: Requirements 4.1, 4.4**


class TestProperty6LargeOrderDetectionThreshold:
    """Property 6: 对于任意 OrderBook 快照序列，当某档位挂单量
    >= 该档位最近 60 秒历史均值 × 5 时，SpoofingFilter 应将该档位
    标记为疑似巨单。"""

    @given(
        normal_vol=normal_volume_st,
        baseline_count=baseline_count_st,
        extra_mult=extra_multiplier_st,
    )
    @settings(max_examples=200)
    def test_volume_above_threshold_is_tracked(
        self, normal_vol: int, baseline_count: int, extra_mult: float,
    ):
        """挂单量 >= 历史均值 × volume_multiplier 时，应被标记为疑似巨单"""
        loop = asyncio.get_event_loop()
        multiplier = 5.0
        sf, mock_sm = make_filter(volume_multiplier=multiplier)

        ask_price = 10.05
        bid_price = 10.04

        # 建立基线
        last_ts = loop.run_until_complete(
            build_baseline(sf, ask_price, bid_price, normal_vol, baseline_count)
        )

        # 注入巨单：挂单量 = 均值 × multiplier × extra_mult
        large_vol = int(normal_vol * multiplier * extra_mult) + 1
        assume(large_vol > normal_vol * multiplier)

        ob = make_order_book(
            ask_levels=[make_level(ask_price, large_vol)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=last_ts + 1,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob))

        # 验证：ask_price 应被跟踪为疑似巨单
        tracked = sf._tracked.get(STOCK, {})
        assert ask_price in tracked, (
            f"挂单量 {large_vol} >= 均值 {normal_vol} × {multiplier} "
            f"时应被标记为疑似巨单"
        )
        assert tracked[ask_price].side == PriceLevelSide.RESISTANCE

    @given(
        normal_vol=normal_volume_st,
        baseline_count=baseline_count_st,
        below_ratio=below_ratio_st,
    )
    @settings(max_examples=200)
    def test_volume_below_threshold_not_tracked(
        self, normal_vol: int, baseline_count: int, below_ratio: float,
    ):
        """挂单量 < 历史均值 × volume_multiplier 时，不应被标记"""
        loop = asyncio.get_event_loop()
        multiplier = 5.0
        sf, mock_sm = make_filter(volume_multiplier=multiplier)

        ask_price = 10.05
        bid_price = 10.04

        last_ts = loop.run_until_complete(
            build_baseline(sf, ask_price, bid_price, normal_vol, baseline_count)
        )

        # 注入不足阈值的挂单量
        small_vol = int(normal_vol * multiplier * below_ratio)
        assume(small_vol < normal_vol * multiplier)
        assume(small_vol > 0)

        ob = make_order_book(
            ask_levels=[make_level(ask_price, small_vol)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=last_ts + 1,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob))

        tracked = sf._tracked.get(STOCK, {})
        assert ask_price not in tracked, (
            f"挂单量 {small_vol} < 均值 {normal_vol} × {multiplier} "
            f"时不应被标记为疑似巨单"
        )

    @given(
        normal_vol=normal_volume_st,
        baseline_count=baseline_count_st,
        extra_mult=extra_multiplier_st,
    )
    @settings(max_examples=200)
    def test_bid_side_large_order_tracked_as_support(
        self, normal_vol: int, baseline_count: int, extra_mult: float,
    ):
        """Bid 侧巨单应被标记为支撑（SUPPORT）"""
        loop = asyncio.get_event_loop()
        multiplier = 5.0
        sf, mock_sm = make_filter(volume_multiplier=multiplier)

        ask_price = 10.05
        bid_price = 10.04

        last_ts = loop.run_until_complete(
            build_baseline(sf, ask_price, bid_price, normal_vol, baseline_count)
        )

        large_vol = int(normal_vol * multiplier * extra_mult) + 1
        assume(large_vol > normal_vol * multiplier)

        ob = make_order_book(
            ask_levels=[make_level(ask_price, normal_vol)],
            bid_levels=[make_level(bid_price, large_vol)],
            timestamp_s=last_ts + 1,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob))

        tracked = sf._tracked.get(STOCK, {})
        assert bid_price in tracked, "Bid 侧巨单应被跟踪"
        assert tracked[bid_price].side == PriceLevelSide.SUPPORT

    @given(
        normal_vol=normal_volume_st,
        baseline_count=baseline_count_st,
        custom_multiplier=st.floats(
            min_value=2.0, max_value=10.0,
            allow_nan=False, allow_infinity=False,
        ),
        extra_mult=extra_multiplier_st,
    )
    @settings(max_examples=200)
    def test_custom_volume_multiplier(
        self,
        normal_vol: int,
        baseline_count: int,
        custom_multiplier: float,
        extra_mult: float,
    ):
        """可配置的 volume_multiplier 应正确影响检测阈值"""
        loop = asyncio.get_event_loop()
        sf, mock_sm = make_filter(volume_multiplier=custom_multiplier)

        ask_price = 10.05
        bid_price = 10.04

        last_ts = loop.run_until_complete(
            build_baseline(sf, ask_price, bid_price, normal_vol, baseline_count)
        )

        large_vol = int(normal_vol * custom_multiplier * extra_mult) + 1
        assume(large_vol > normal_vol * custom_multiplier)

        ob = make_order_book(
            ask_levels=[make_level(ask_price, large_vol)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=last_ts + 1,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob))

        tracked = sf._tracked.get(STOCK, {})
        assert ask_price in tracked, (
            f"自定义倍数 {custom_multiplier}: 挂单量 {large_vol} "
            f"应触发巨单检测"
        )

    @given(
        normal_vol=normal_volume_st,
        baseline_count=baseline_count_st,
    )
    @settings(max_examples=200)
    def test_rolling_avg_uses_60s_window(
        self, normal_vol: int, baseline_count: int,
    ):
        """历史均值应基于最近 60 秒的快照"""
        loop = asyncio.get_event_loop()
        sf, mock_sm = make_filter(
            volume_multiplier=5.0,
            history_window_seconds=60.0,
        )

        ask_price = 10.05
        bid_price = 10.04

        # 在 60 秒窗口内建立基线
        last_ts = loop.run_until_complete(
            build_baseline(
                sf, ask_price, bid_price, normal_vol,
                baseline_count, start_ts_s=BASE_TS_S,
            )
        )

        # 验证均值存在且合理
        avg = sf._compute_rolling_avg(STOCK, ask_price, last_ts + 1)
        assert avg is not None, "建立基线后均值不应为 None"
        assert avg == pytest.approx(normal_vol, rel=0.01), (
            f"均值应约等于 {normal_vol}，实际为 {avg}"
        )


# ── Property 7: 巨单生命周期状态转换 ────────────────────────────
# Feature: intraday-scalping-engine, Property 7: 巨单生命周期状态转换
# **Validates: Requirements 4.2, 4.3, 4.4, 4.5**


class TestProperty7LargeOrderLifecycleTransitions:
    """Property 7: 对于任意已标记的疑似巨单，
    - 存活未达 survive_seconds_min（默认 3 秒）时被撤销 → 直接移除，不生成事件
    - 存活超过 survive_seconds_max（默认 5 秒）→ 生成 CREATE 事件
    - 价格靠近（< 5 Tick）时被撤销 → 生成 REMOVE 事件
    - 被市场成交吃透 → 生成 BREAK 事件
    四种结局互斥。"""

    def _setup_tracked_large_order(
        self,
        normal_vol: int,
        baseline_count: int,
        volume_multiplier: float = 5.0,
        survive_min: float = 3.0,
        survive_max: float = 5.0,
    ) -> tuple[SpoofingFilter, MagicMock, float, float, float]:
        """建立基线并注入巨单，返回 (sf, mock_sm, ask_price, bid_price, inject_ts)。

        巨单注入在 ask_price 侧（RESISTANCE）。
        """
        loop = asyncio.get_event_loop()
        sf, mock_sm = make_filter(
            volume_multiplier=volume_multiplier,
            survive_seconds_min=survive_min,
            survive_seconds_max=survive_max,
        )

        ask_price = 10.05
        bid_price = 10.04

        last_ts = loop.run_until_complete(
            build_baseline(sf, ask_price, bid_price, normal_vol, baseline_count)
        )

        # 注入巨单
        large_vol = int(normal_vol * volume_multiplier) + 100
        inject_ts = last_ts + 1
        ob = make_order_book(
            ask_levels=[make_level(ask_price, large_vol)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=inject_ts,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob))

        # 确认巨单已被跟踪
        assert ask_price in sf._tracked.get(STOCK, {}), "巨单应已被跟踪"

        return sf, mock_sm, ask_price, bid_price, inject_ts

    # ── 需求 4.3: 存活未达 survive_seconds_min → 静默移除 ────────

    @given(
        normal_vol=normal_volume_st,
        baseline_count=baseline_count_st,
        survive_ratio=st.floats(
            min_value=0.1, max_value=0.9,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200)
    def test_silent_removal_before_min_survive(
        self, normal_vol: int, baseline_count: int, survive_ratio: float,
    ):
        """巨单存活未达 survive_seconds_min 时被撤销，应直接移除不生成事件"""
        loop = asyncio.get_event_loop()
        survive_min = 3.0
        sf, mock_sm, ask_price, bid_price, inject_ts = (
            self._setup_tracked_large_order(
                normal_vol, baseline_count, survive_min=survive_min,
            )
        )

        # 清除基线阶段的 emit 调用
        mock_sm.emit_to_all.reset_mock()

        # 在 survive_min 之前让巨单消失
        disappear_ts = inject_ts + survive_min * survive_ratio
        ob = make_order_book(
            ask_levels=[make_level(ask_price, 0)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=disappear_ts,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob))

        # 验证：不应生成任何事件
        mock_sm.emit_to_all.assert_not_called(), (
            f"存活 {survive_min * survive_ratio:.1f}s < {survive_min}s "
            f"时不应生成任何事件"
        )

        # 验证：巨单应已从跟踪列表中移除
        tracked = sf._tracked.get(STOCK, {})
        assert ask_price not in tracked, "静默移除后不应继续跟踪"

    # ── 需求 4.2: 存活超过 survive_seconds_max → CREATE 事件 ────

    @given(
        normal_vol=normal_volume_st,
        baseline_count=baseline_count_st,
        extra_survive=st.floats(
            min_value=0.1, max_value=10.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200)
    def test_create_event_after_max_survive(
        self, normal_vol: int, baseline_count: int, extra_survive: float,
    ):
        """巨单存活超过 survive_seconds_max 时，应生成 CREATE 事件"""
        loop = asyncio.get_event_loop()
        survive_max = 5.0
        sf, mock_sm, ask_price, bid_price, inject_ts = (
            self._setup_tracked_large_order(
                normal_vol, baseline_count, survive_max=survive_max,
            )
        )

        mock_sm.emit_to_all.reset_mock()

        # 巨单持续存在超过 survive_max
        large_vol = int(normal_vol * 5.0) + 100
        confirm_ts = inject_ts + survive_max + extra_survive
        ob = make_order_book(
            ask_levels=[make_level(ask_price, large_vol)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=confirm_ts,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob))

        # 验证：应推送 PRICE_LEVEL_CREATE 事件
        create_events = get_events_by_type(
            mock_sm, SocketEvent.PRICE_LEVEL_CREATE
        )
        assert len(create_events) >= 1, (
            f"存活 {survive_max + extra_survive:.1f}s > {survive_max}s "
            f"时应生成 CREATE 事件"
        )
        assert create_events[0]["price"] == ask_price
        assert create_events[0]["side"] == PriceLevelSide.RESISTANCE.value

    # ── 需求 4.4: 价格靠近时被撤销 → REMOVE 事件 ────────────────

    @given(
        normal_vol=normal_volume_st,
        baseline_count=baseline_count_st,
        proximity_offset=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=200)
    def test_remove_event_when_close_and_cancelled(
        self, normal_vol: int, baseline_count: int, proximity_offset: int,
    ):
        """巨单在价格靠近（< 5 Tick）时被撤销，应生成 REMOVE 事件"""
        loop = asyncio.get_event_loop()
        survive_min = 3.0
        survive_max = 5.0
        sf, mock_sm, ask_price, bid_price, inject_ts = (
            self._setup_tracked_large_order(
                normal_vol, baseline_count,
                survive_min=survive_min, survive_max=survive_max,
            )
        )

        mock_sm.emit_to_all.reset_mock()

        # 先让巨单存活超过 survive_min 但不超过 survive_max
        mid_ts = inject_ts + (survive_min + survive_max) / 2.0
        large_vol = int(normal_vol * 5.0) + 100

        # 保持巨单存在
        ob_keep = make_order_book(
            ask_levels=[make_level(ask_price, large_vol)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=mid_ts,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob_keep))

        mock_sm.emit_to_all.reset_mock()

        # 价格靠近巨单（mid_price 距离 ask_price < 5 Tick）
        # mid_price = (new_ask + new_bid) / 2，让 mid_price 靠近 ask_price
        close_bid = ask_price - proximity_offset * TICK_SIZE
        close_ask = ask_price + TICK_SIZE

        # 巨单消失（挂单量降为 0）
        disappear_ts = mid_ts + 0.5
        ob_disappear = make_order_book(
            ask_levels=[make_level(close_ask, normal_vol)],
            bid_levels=[make_level(close_bid, normal_vol)],
            timestamp_s=disappear_ts,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob_disappear))

        # 验证：应推送 REMOVE 事件
        remove_events = get_events_by_type(
            mock_sm, SocketEvent.PRICE_LEVEL_REMOVE
        )
        assert len(remove_events) >= 1, (
            f"价格靠近（{proximity_offset} Tick）时被撤销应生成 REMOVE 事件"
        )
        assert remove_events[0]["price"] == ask_price

    # ── 需求 4.5: 被市场成交吃透 → BREAK 事件 ───────────────────

    @given(
        normal_vol=normal_volume_st,
        baseline_count=baseline_count_st,
    )
    @settings(max_examples=200)
    def test_break_event_when_consumed(
        self, normal_vol: int, baseline_count: int,
    ):
        """巨单被市场成交吃透时，应生成 BREAK 事件"""
        loop = asyncio.get_event_loop()
        survive_min = 3.0
        sf, mock_sm, ask_price, bid_price, inject_ts = (
            self._setup_tracked_large_order(
                normal_vol, baseline_count, survive_min=survive_min,
            )
        )

        large_vol = int(normal_vol * 5.0) + 100

        # 让巨单存活超过 survive_min
        mid_ts = inject_ts + survive_min + 0.5
        ob_keep = make_order_book(
            ask_levels=[make_level(ask_price, large_vol)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=mid_ts,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob_keep))

        mock_sm.emit_to_all.reset_mock()

        # 模拟逐步被吃透：先降到初始量的 40%，再降到 0
        # 这样 last_volume < initial_volume * 0.5，满足 _is_consumed 判定
        eaten_vol = int(large_vol * 0.4)
        eat_ts = mid_ts + 0.5
        ob_eat = make_order_book(
            ask_levels=[make_level(ask_price, eaten_vol)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=eat_ts,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob_eat))

        # 完全消失（current_volume = 0，且 last_volume < initial * 0.5）
        # 价格远离，确保不触发 REMOVE（is_close = False）
        far_bid = ask_price - 10 * TICK_SIZE
        far_ask = ask_price + 10 * TICK_SIZE
        consume_ts = eat_ts + 0.5
        ob_consume = make_order_book(
            ask_levels=[make_level(far_ask, normal_vol)],
            bid_levels=[make_level(far_bid, normal_vol)],
            timestamp_s=consume_ts,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob_consume))

        # 验证：应推送 BREAK 事件
        break_events = get_events_by_type(
            mock_sm, SocketEvent.PRICE_LEVEL_BREAK
        )
        assert len(break_events) >= 1, "巨单被吃透时应生成 BREAK 事件"
        assert break_events[0]["price"] == ask_price

    # ── 四种结局互斥性 ───────────────────────────────────────────

    @given(
        normal_vol=normal_volume_st,
        baseline_count=baseline_count_st,
    )
    @settings(max_examples=200)
    def test_create_event_emitted_only_once(
        self, normal_vol: int, baseline_count: int,
    ):
        """CREATE 事件对同一巨单只应推送一次"""
        loop = asyncio.get_event_loop()
        survive_max = 5.0
        sf, mock_sm, ask_price, bid_price, inject_ts = (
            self._setup_tracked_large_order(
                normal_vol, baseline_count, survive_max=survive_max,
            )
        )

        mock_sm.emit_to_all.reset_mock()
        large_vol = int(normal_vol * 5.0) + 100

        # 第一次超过 survive_max → 应触发 CREATE
        ts1 = inject_ts + survive_max + 1.0
        ob1 = make_order_book(
            ask_levels=[make_level(ask_price, large_vol)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=ts1,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob1))

        # 第二次仍然存在 → 不应再次触发 CREATE
        ts2 = ts1 + 2.0
        ob2 = make_order_book(
            ask_levels=[make_level(ask_price, large_vol)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=ts2,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob2))

        create_events = get_events_by_type(
            mock_sm, SocketEvent.PRICE_LEVEL_CREATE
        )
        assert len(create_events) == 1, (
            f"CREATE 事件应只推送一次，实际推送了 {len(create_events)} 次"
        )

    @given(
        normal_vol=normal_volume_st,
        baseline_count=baseline_count_st,
        survive_min=st.floats(
            min_value=1.0, max_value=5.0,
            allow_nan=False, allow_infinity=False,
        ),
        survive_max=st.floats(
            min_value=6.0, max_value=15.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200)
    def test_configurable_survive_time_range(
        self,
        normal_vol: int,
        baseline_count: int,
        survive_min: float,
        survive_max: float,
    ):
        """可配置的 survive_seconds_min/max 应正确影响生命周期判定"""
        loop = asyncio.get_event_loop()
        assume(survive_max > survive_min + 0.5)

        sf, mock_sm, ask_price, bid_price, inject_ts = (
            self._setup_tracked_large_order(
                normal_vol, baseline_count,
                survive_min=survive_min, survive_max=survive_max,
            )
        )

        mock_sm.emit_to_all.reset_mock()

        # 在 survive_min 之前让巨单消失 → 应静默移除
        early_ts = inject_ts + survive_min * 0.5
        ob_early = make_order_book(
            ask_levels=[make_level(ask_price, 0)],
            bid_levels=[make_level(bid_price, normal_vol)],
            timestamp_s=early_ts,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob_early))

        mock_sm.emit_to_all.assert_not_called(), (
            f"自定义 survive_min={survive_min}: 存活 "
            f"{survive_min * 0.5:.1f}s 时不应生成事件"
        )


# ── Property 20: 虚假流动性步步紧逼检测 ─────────────────────────
# Feature: intraday-scalping-engine, Property 20: 虚假流动性步步紧逼检测
# **Validates: Requirements 15.2, 15.3**


# ── Property 20 辅助策略 ─────────────────────────────────────────

# 步步紧逼的移动步数（>= 4 确保 path 长度 >= 3 触发 confirmed）
move_steps_st = st.integers(min_value=4, max_value=6)


def _build_multi_level_baseline(
    sf: SpoofingFilter,
    normal_vol: int,
    baseline_count: int,
    base_ask: float,
    base_bid: float,
    num_levels: int = 10,
) -> float:
    """在多个 bid/ask 档位建立基线，返回最后时间戳（秒）。

    确保后续大单出现的各个价位都有足够的历史均值。
    """
    loop = asyncio.get_event_loop()
    for i in range(baseline_count):
        bid_levels = [
            make_level(round(base_bid + j * TICK_SIZE, 2), normal_vol)
            for j in range(num_levels)
        ]
        ask_levels = [
            make_level(round(base_ask + j * TICK_SIZE, 2), normal_vol)
            for j in range(num_levels)
        ]
        ob = make_order_book(
            ask_levels=ask_levels,
            bid_levels=bid_levels,
            timestamp_s=BASE_TS_S + i,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob))
    return BASE_TS_S + baseline_count - 1


def _compute_dilution_safe_volume(
    normal_vol: int, baseline_count: int, multiplier: float,
    max_large_snapshots: int = 4,
) -> int:
    """计算考虑滚动均值稀释效应后的安全大单量。

    大单快照会稀释 rolling avg。假设某价位最多出现 max_large_snapshots 次大单快照，
    需要确保 large_vol 始终 >= diluted_avg * multiplier。
    公式推导：
      avg = (N * normal_vol + K * large_vol) / (N + K)
      large_vol >= avg * multiplier
      => large_vol >= N * normal_vol * multiplier / (N + K - K * multiplier)
    其中 N=baseline_count, K=max_large_snapshots
    """
    denominator = baseline_count + max_large_snapshots - max_large_snapshots * multiplier
    if denominator <= 0:
        return normal_vol * int(multiplier) * 100
    min_vol = baseline_count * normal_vol * multiplier / denominator
    return int(min_vol) + 50  # 加余量确保严格大于


def _inject_moving_large_order(
    sf: SpoofingFilter,
    normal_vol: int,
    large_vol: int,
    base_ask: float,
    base_bid: float,
    move_steps: int,
    start_ts: float,
    step_interval: float = 1.0,
) -> tuple[float, float]:
    """注入逐档上移的 Bid 侧大单，同时中间价同步上涨。

    返回 (最后大单价格, 最后时间戳)。
    step_interval: 每步之间的时间间隔（秒）
    """
    loop = asyncio.get_event_loop()
    last_price = base_bid
    last_ts = start_ts
    for step in range(move_steps):
        bid_large_price = round(base_bid + step * TICK_SIZE, 2)
        current_ask = round(base_ask + step * TICK_SIZE, 2)
        bid_levels = [make_level(bid_large_price, large_vol)]
        ask_levels = [make_level(current_ask, normal_vol)]
        ts = start_ts + step * step_interval
        ob = make_order_book(
            ask_levels=ask_levels,
            bid_levels=bid_levels,
            timestamp_s=ts,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob))
        last_price = bid_large_price
        last_ts = ts
    return last_price, last_ts


class TestProperty20FakeLiquidityDetection:
    """Property 20: 虚假流动性步步紧逼检测

    - Bid 侧大单在连续 3+ 次 OrderBook 快照中逐档上移且中间价同步上涨
      → 标记为"疑似虚假流动性"（confirmed_suspicious = True）
    - 已标记大单在价格停滞期间消失 → 推送 FAKE_LIQUIDITY_ALERT 事件
    """

    @given(
        normal_vol=st.integers(min_value=100, max_value=500),
        baseline_count=st.integers(min_value=20, max_value=40),
        move_steps=move_steps_st,
    )
    @settings(max_examples=200)
    def test_bid_large_order_moving_up_marked_suspicious(
        self,
        normal_vol: int,
        baseline_count: int,
        move_steps: int,
    ):
        """Bid 侧大单连续 3+ 次上移且中间价同步上涨 → confirmed_suspicious"""
        loop = asyncio.get_event_loop()
        multiplier = 5.0
        sf, mock_sm = make_filter(volume_multiplier=multiplier)

        base_ask = 10.10
        base_bid = 10.00

        # 建立基线（多档位，确保大单移动路径上每个价位都有历史均值）
        last_baseline_ts = _build_multi_level_baseline(
            sf, normal_vol, baseline_count, base_ask, base_bid,
        )

        # 计算考虑稀释效应的安全大单量
        large_vol = _compute_dilution_safe_volume(
            normal_vol, baseline_count, multiplier,
        )

        # 注入逐档上移的大单
        last_price, _ = _inject_moving_large_order(
            sf, normal_vol, large_vol,
            base_ask, base_bid, move_steps,
            start_ts=last_baseline_ts + 1,
        )

        # 验证：应存在 confirmed_suspicious = True 的 tracker
        # 方案 I 改为按侧面分 key: "{stock_code}_bid" / "{stock_code}_ask"
        trackers = sf._fake_liquidity_trackers.get(f"{STOCK}_bid", [])
        suspicious = [t for t in trackers if t.confirmed_suspicious]
        assert len(suspicious) >= 1, (
            f"Bid 侧大单连续 {move_steps} 次上移后应标记为疑似虚假流动性"
        )
        assert len(suspicious[0].move_path) >= 3, (
            f"移动路径应至少 3 步，实际 {len(suspicious[0].move_path)} 步"
        )

    @given(
        normal_vol=st.integers(min_value=100, max_value=500),
        baseline_count=st.integers(min_value=20, max_value=40),
    )
    @settings(max_examples=200)
    def test_fake_liquidity_alert_on_stagnant_disappear(
        self,
        normal_vol: int,
        baseline_count: int,
    ):
        """已标记大单在价格停滞期间消失 → 推送 FAKE_LIQUIDITY_ALERT

        实现逻辑：confirmed_suspicious 的 tracker 在没有更高价位大单时，
        会立即触发停滞检测。需要确保此时 mid_list 中最近 3 秒的
        中间价波动 < 2 Tick。
        方案：移动步骤间隔 > 3 秒，使得最后一步时 mid_list 只含最近的
        停滞价格。然后在最后一步后紧接发送停滞快照触发检测。
        """
        loop = asyncio.get_event_loop()
        multiplier = 5.0
        sf, mock_sm = make_filter(volume_multiplier=multiplier)

        base_ask = 10.10
        base_bid = 10.00
        move_steps = 4

        last_baseline_ts = _build_multi_level_baseline(
            sf, normal_vol, baseline_count, base_ask, base_bid,
        )

        large_vol = _compute_dilution_safe_volume(
            normal_vol, baseline_count, multiplier, max_large_snapshots=4,
        )

        # 移动步骤间隔 4 秒，确保每步的 mid_price 不在前一步的 3 秒窗口内
        last_price, last_move_ts = _inject_moving_large_order(
            sf, normal_vol, large_vol,
            base_ask, base_bid, move_steps,
            start_ts=last_baseline_ts + 1,
            step_interval=4.0,
        )

        # 确认已标记（方案 I: key 为 "{stock_code}_bid"）
        trackers = sf._fake_liquidity_trackers.get(f"{STOCK}_bid", [])
        suspicious = [t for t in trackers if t.confirmed_suspicious]
        assert len(suspicious) >= 1, "应已标记为疑似虚假流动性"

        mock_sm.emit_to_all.reset_mock()

        # 在最后一步后 1 秒发送停滞快照（大单不上移）
        # 此时 mid_list 3 秒窗口内只有 last_move_ts 和 stop_ts 的 mid_price
        # 两者中间价相同 → 停滞 → 应推送 FAKE_LIQUIDITY_ALERT
        stagnant_ask = round(base_ask + (move_steps - 1) * TICK_SIZE, 2)
        stop_ts = last_move_ts + 1.0
        ob_stop = make_order_book(
            ask_levels=[make_level(stagnant_ask, normal_vol)],
            bid_levels=[make_level(last_price, large_vol)],
            timestamp_s=stop_ts,
        )
        loop.run_until_complete(sf.on_order_book(STOCK, ob_stop))

        # 验证：应推送 FAKE_LIQUIDITY_ALERT 事件
        alert_events = get_events_by_type(
            mock_sm, SocketEvent.FAKE_LIQUIDITY_ALERT
        )
        assert len(alert_events) >= 1, (
            "已标记大单在价格停滞期间停止上移时应推送 FAKE_LIQUIDITY_ALERT"
        )
        assert alert_events[0]["stock_code"] == STOCK
        assert "move_path" in alert_events[0]
        assert len(alert_events[0]["move_path"]) >= 3
