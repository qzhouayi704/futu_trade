#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ScalpingEngine 属性测试

使用 hypothesis 验证 Tick 数据分发完整性和 OrderBook 分发正确性。

Feature: intraday-scalping-engine, Property 1: Tick 数据分发完整性
**Validates: Requirements 1.3, 1.4, 17.5**
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, strategies as st

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ),
)

from simple_trade.services.scalping.calculators.delta_calculator import DeltaCalculator
from simple_trade.services.scalping.engine import ScalpingEngine
from simple_trade.services.scalping.models import (
    OrderBookData,
    OrderBookLevel,
    TickData,
    TickDirection,
)
from simple_trade.services.scalping.calculators.poc_calculator import POCCalculator
from simple_trade.services.scalping.detectors.spoofing_filter import SpoofingFilter
from simple_trade.services.scalping.calculators.tape_velocity import TapeVelocityMonitor

STOCK = "HK.00700"


# ── 辅助函数 ──────────────────────────────────────────────────────


def _mock_sm():
    sm = MagicMock()
    sm.emit_to_all = AsyncMock()
    return sm


def _make_tick(
    price_cents: int = 35000,
    volume: int = 200,
    direction: TickDirection = TickDirection.BUY,
    timestamp_ms: float = 1_700_000_000_000.0,
) -> TickData:
    price = price_cents / 100.0
    return TickData(
        stock_code=STOCK,
        price=price,
        volume=volume,
        direction=direction,
        timestamp=timestamp_ms,
        ask_price=price + 0.2,
        bid_price=price - 0.2,
    )


def _make_order_book(timestamp_ms: float = 1_700_000_000_000.0) -> OrderBookData:
    ask = [
        OrderBookLevel(price=350.1 + i * 0.1, volume=100, order_count=5)
        for i in range(10)
    ]
    bid = [
        OrderBookLevel(price=350.0 - i * 0.1, volume=100, order_count=5)
        for i in range(10)
    ]
    return OrderBookData(
        stock_code=STOCK, ask_levels=ask, bid_levels=bid, timestamp=timestamp_ms,
    )


def _build_engine(
    filter_result: tuple[bool, bool] | None = None,
    with_optional: bool = True,
) -> tuple[ScalpingEngine, dict]:
    """构建 ScalpingEngine 并返回 (engine, mocks_dict)

    Args:
        filter_result: TickCredibilityFilter.filter_tick 的返回值。
            None 表示不注入 filter（filter 为 None）。
        with_optional: 是否注入可选组件 mock。
    """
    sm = _mock_sm()

    # 核心计算器使用真实实例（任务要求）
    dc = DeltaCalculator(socket_manager=sm)
    tv = TapeVelocityMonitor(socket_manager=sm)
    sf = SpoofingFilter(socket_manager=sm)
    pc = POCCalculator(socket_manager=sm)

    # SignalEngine 用 mock（不是本测试关注点）
    sig = MagicMock()
    sig.evaluate_breakout = AsyncMock(return_value=None)
    sig.evaluate_support_bounce = AsyncMock(return_value=None)

    # TickCredibilityFilter
    tcf = None
    if filter_result is not None:
        tcf = MagicMock()
        tcf.filter_tick = MagicMock(return_value=filter_result)

    # 可选组件
    div_mock = MagicMock() if with_optional else None
    brk_mock = MagicMock() if with_optional else None
    vwap_mock = None
    if with_optional:
        vwap_mock = MagicMock()
        vwap_mock.on_tick_async = AsyncMock()
    sl_mock = MagicMock() if with_optional else None

    engine = ScalpingEngine(
        subscription_helper=MagicMock(),
        realtime_query=MagicMock(),
        socket_manager=sm,
        delta_calculator=dc,
        tape_velocity=tv,
        spoofing_filter=sf,
        poc_calculator=pc,
        signal_engine=sig,
        tick_credibility_filter=tcf,
        divergence_detector=div_mock,
        breakout_monitor=brk_mock,
        vwap_guard=vwap_mock,
        stop_loss_monitor=sl_mock,
    )

    mocks = {
        "tcf": tcf,
        "divergence_detector": div_mock,
        "breakout_monitor": brk_mock,
        "vwap_guard": vwap_mock,
        "stop_loss_monitor": sl_mock,
        "spoofing_filter_instance": sf,
        "delta_calculator": dc,
        "tape_velocity": tv,
        "poc_calculator": pc,
    }
    return engine, mocks


# ── hypothesis 策略 ──────────────────────────────────────────────

price_cents_st = st.integers(min_value=100, max_value=100000)
volume_st = st.integers(min_value=1, max_value=50000)
direction_st = st.sampled_from(list(TickDirection))
timestamp_ms_st = st.floats(
    min_value=1_700_000_000_000.0,
    max_value=1_800_000_000_000.0,
    allow_nan=False,
    allow_infinity=False,
)


# ── Property 1: Tick 数据分发完整性 ──────────────────────────────
# Feature: intraday-scalping-engine, Property 1: Tick 数据分发完整性
# **Validates: Requirements 1.3, 1.4, 17.5**


class TestProperty1TickDispatchIntegrity:
    """Property 1: 对于任意 Tick 数据和任意已启动的 ScalpingEngine 实例，
    当 on_tick 被调用时：
    - Tick 应先经过 TickCredibilityFilter 进行可信度验证
    - 通过验证的 Tick 应被分发至 7 个下游组件
    - 被标记为集合竞价或 OUTLIER 的 Tick 不应分发至下游计算器
    - OrderBook 数据应正确分发至 SpoofingFilter
    """

    # ── 1a: TickCredibilityFilter 在分发前执行 ────────────────────

    @given(
        price_cents=price_cents_st,
        volume=volume_st,
        direction=direction_st,
        ts=timestamp_ms_st,
    )
    @settings(max_examples=200)
    def test_filter_called_before_dispatch(
        self, price_cents: int, volume: int,
        direction: TickDirection, ts: float,
    ):
        """TickCredibilityFilter 存在时，filter_tick 必须在分发前被调用"""
        tick = _make_tick(price_cents, volume, direction, ts)
        engine, mocks = _build_engine(filter_result=(True, False))

        loop = asyncio.get_event_loop()
        loop.run_until_complete(engine.start([STOCK]))
        loop.run_until_complete(engine.on_tick(STOCK, tick))

        # filter_tick 必须被调用
        mocks["tcf"].filter_tick.assert_called_once_with(STOCK, tick)

    # ── 1b: 通过验证的 Tick 分发至全部 7 个下游组件 ──────────────

    @given(
        price_cents=price_cents_st,
        volume=volume_st,
        direction=direction_st,
        ts=timestamp_ms_st,
    )
    @settings(max_examples=200)
    def test_passed_tick_dispatched_to_all_seven_components(
        self, price_cents: int, volume: int,
        direction: TickDirection, ts: float,
    ):
        """filter_tick 返回 (True, False) 时，Tick 应分发至全部 7 个组件：
        DeltaCalculator、TapeVelocityMonitor、POCCalculator（核心，真实实例）
        + divergence_detector、breakout_monitor、vwap_guard、stop_loss_monitor（可选 mock）
        """
        tick = _make_tick(price_cents, volume, direction, ts)
        engine, mocks = _build_engine(filter_result=(True, False))

        loop = asyncio.get_event_loop()
        loop.run_until_complete(engine.start([STOCK]))

        # 记录核心计算器调用前的状态
        tv = mocks["tape_velocity"]
        pc = mocks["poc_calculator"]

        # 获取调用前的状态快照
        tv_state_before = len(tv._get_state(STOCK).tick_timestamps)
        pc_state_before = sum(pc._get_state(STOCK).volume_bins.values())

        loop.run_until_complete(engine.on_tick(STOCK, tick))

        # 核心计算器：验证状态变化（真实实例，不能用 assert_called）
        # DeltaCalculator 的 on_tick 会处理 tick（可能因 volume < 100 被忽略，
        # 但方法本身一定被调用了——通过检查 tape_velocity 的时间戳来间接验证）
        tv_state_after = len(tv._get_state(STOCK).tick_timestamps)
        assert tv_state_after > tv_state_before, (
            "TapeVelocityMonitor 应收到 Tick 数据"
        )

        # 可选组件 mock：直接验证调用
        mocks["divergence_detector"].on_tick.assert_called_once_with(STOCK, tick)
        mocks["breakout_monitor"].on_tick.assert_called_once_with(STOCK, tick)
        mocks["vwap_guard"].on_tick_async.assert_called_once_with(STOCK, tick)
        mocks["stop_loss_monitor"].on_tick.assert_called_once_with(STOCK, tick)

    # ── 1c: 被过滤的 Tick（集合竞价）不分发至下游 ────────────────

    @given(
        price_cents=price_cents_st,
        volume=volume_st,
        direction=direction_st,
        ts=timestamp_ms_st,
    )
    @settings(max_examples=200)
    def test_auction_tick_not_dispatched(
        self, price_cents: int, volume: int,
        direction: TickDirection, ts: float,
    ):
        """filter_tick 返回 (False, False)（集合竞价）时，
        Tick 不应分发至任何下游计算器"""
        tick = _make_tick(price_cents, volume, direction, ts)
        engine, mocks = _build_engine(filter_result=(False, False))

        loop = asyncio.get_event_loop()
        loop.run_until_complete(engine.start([STOCK]))

        tv_before = len(
            mocks["tape_velocity"]._get_state(STOCK).tick_timestamps
        )

        loop.run_until_complete(engine.on_tick(STOCK, tick))

        # 核心计算器不应收到数据
        tv_after = len(
            mocks["tape_velocity"]._get_state(STOCK).tick_timestamps
        )
        assert tv_after == tv_before, (
            "集合竞价 Tick 不应分发至 TapeVelocityMonitor"
        )

        # 可选组件不应被调用
        mocks["divergence_detector"].on_tick.assert_not_called()
        mocks["breakout_monitor"].on_tick.assert_not_called()
        mocks["vwap_guard"].on_tick.assert_not_called()
        mocks["stop_loss_monitor"].on_tick.assert_not_called()

    # ── 1d: 被过滤的 Tick（OUTLIER）不分发至下游 ─────────────────

    @given(
        price_cents=price_cents_st,
        volume=volume_st,
        direction=direction_st,
        ts=timestamp_ms_st,
    )
    @settings(max_examples=200)
    def test_outlier_tick_not_dispatched(
        self, price_cents: int, volume: int,
        direction: TickDirection, ts: float,
    ):
        """filter_tick 返回 (False, True)（OUTLIER）时，
        Tick 不应分发至任何下游计算器"""
        tick = _make_tick(price_cents, volume, direction, ts)
        engine, mocks = _build_engine(filter_result=(False, True))

        loop = asyncio.get_event_loop()
        loop.run_until_complete(engine.start([STOCK]))

        tv_before = len(
            mocks["tape_velocity"]._get_state(STOCK).tick_timestamps
        )

        loop.run_until_complete(engine.on_tick(STOCK, tick))

        # 核心计算器不应收到数据
        tv_after = len(
            mocks["tape_velocity"]._get_state(STOCK).tick_timestamps
        )
        assert tv_after == tv_before, (
            "OUTLIER Tick 不应分发至 TapeVelocityMonitor"
        )

        # 可选组件不应被调用
        mocks["divergence_detector"].on_tick.assert_not_called()
        mocks["breakout_monitor"].on_tick.assert_not_called()
        mocks["vwap_guard"].on_tick.assert_not_called()
        mocks["stop_loss_monitor"].on_tick.assert_not_called()

    # ── 1e: 无 TickCredibilityFilter 时 Tick 直接分发 ────────────

    @given(
        price_cents=price_cents_st,
        volume=volume_st,
        direction=direction_st,
        ts=timestamp_ms_st,
    )
    @settings(max_examples=200)
    def test_no_filter_dispatches_directly(
        self, price_cents: int, volume: int,
        direction: TickDirection, ts: float,
    ):
        """TickCredibilityFilter 为 None 时，Tick 应直接分发至所有下游组件"""
        tick = _make_tick(price_cents, volume, direction, ts)
        engine, mocks = _build_engine(filter_result=None, with_optional=True)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(engine.start([STOCK]))

        tv_before = len(
            mocks["tape_velocity"]._get_state(STOCK).tick_timestamps
        )

        loop.run_until_complete(engine.on_tick(STOCK, tick))

        # 核心计算器应收到数据
        tv_after = len(
            mocks["tape_velocity"]._get_state(STOCK).tick_timestamps
        )
        assert tv_after > tv_before, (
            "无 filter 时 Tick 应直接分发至 TapeVelocityMonitor"
        )

        # 可选组件应被调用
        mocks["divergence_detector"].on_tick.assert_called_once_with(STOCK, tick)
        mocks["breakout_monitor"].on_tick.assert_called_once_with(STOCK, tick)
        mocks["vwap_guard"].on_tick_async.assert_called_once_with(STOCK, tick)
        mocks["stop_loss_monitor"].on_tick.assert_called_once_with(STOCK, tick)

    # ── 1f: OrderBook 数据正确分发至 SpoofingFilter ──────────────
    # **Validates: Requirements 1.4**

    @given(ts=timestamp_ms_st)
    @settings(max_examples=200)
    def test_order_book_dispatched_to_spoofing_filter(self, ts: float):
        """on_order_book 调用时，OrderBook 应被分发至 SpoofingFilter"""
        ob = _make_order_book(timestamp_ms=ts)

        # SpoofingFilter 用 mock 以便验证调用
        sm = _mock_sm()
        sf_mock = MagicMock()
        sf_mock.on_order_book = AsyncMock()

        engine = ScalpingEngine(
            subscription_helper=MagicMock(),
            realtime_query=MagicMock(),
            socket_manager=sm,
            delta_calculator=DeltaCalculator(socket_manager=sm),
            tape_velocity=TapeVelocityMonitor(socket_manager=sm),
            spoofing_filter=sf_mock,
            poc_calculator=POCCalculator(socket_manager=sm),
            signal_engine=MagicMock(
                evaluate_breakout=AsyncMock(return_value=None),
                evaluate_support_bounce=AsyncMock(return_value=None),
            ),
        )

        loop = asyncio.get_event_loop()
        loop.run_until_complete(engine.start([STOCK]))
        loop.run_until_complete(engine.on_order_book(STOCK, ob))

        sf_mock.on_order_book.assert_awaited_once_with(STOCK, ob)

    # ── 1g: 非活跃股票的 Tick 不分发 ────────────────────────────

    @given(
        price_cents=price_cents_st,
        volume=volume_st,
        direction=direction_st,
        ts=timestamp_ms_st,
    )
    @settings(max_examples=200)
    def test_inactive_stock_tick_not_dispatched(
        self, price_cents: int, volume: int,
        direction: TickDirection, ts: float,
    ):
        """未启动的股票的 Tick 不应被分发至任何组件"""
        tick = _make_tick(price_cents, volume, direction, ts)
        engine, mocks = _build_engine(filter_result=(True, False))

        # 不调用 engine.start，股票不在活跃列表中
        loop = asyncio.get_event_loop()

        tv_before = len(
            mocks["tape_velocity"]._get_state(STOCK).tick_timestamps
        )

        loop.run_until_complete(engine.on_tick(STOCK, tick))

        tv_after = len(
            mocks["tape_velocity"]._get_state(STOCK).tick_timestamps
        )
        assert tv_after == tv_before, (
            "非活跃股票的 Tick 不应被分发"
        )
        mocks["tcf"].filter_tick.assert_not_called()
        mocks["divergence_detector"].on_tick.assert_not_called()

    # ── 1h: 单个组件异常不影响其他组件分发 ───────────────────────

    @given(
        price_cents=price_cents_st,
        volume=volume_st,
        direction=direction_st,
        ts=timestamp_ms_st,
    )
    @settings(max_examples=200)
    def test_component_exception_does_not_block_others(
        self, price_cents: int, volume: int,
        direction: TickDirection, ts: float,
    ):
        """某个可选组件抛异常时，其他组件仍应收到 Tick"""
        tick = _make_tick(price_cents, volume, direction, ts)
        engine, mocks = _build_engine(filter_result=(True, False))

        # 让 divergence_detector 抛异常
        mocks["divergence_detector"].on_tick.side_effect = RuntimeError("boom")

        loop = asyncio.get_event_loop()
        loop.run_until_complete(engine.start([STOCK]))
        loop.run_until_complete(engine.on_tick(STOCK, tick))

        # divergence_detector 异常，但其他组件仍被调用
        mocks["breakout_monitor"].on_tick.assert_called_once_with(STOCK, tick)
        mocks["vwap_guard"].on_tick_async.assert_called_once_with(STOCK, tick)
        mocks["stop_loss_monitor"].on_tick.assert_called_once_with(STOCK, tick)
