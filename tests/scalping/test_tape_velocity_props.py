#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TapeVelocityMonitor 属性测试

使用 hypothesis 验证滑动窗口成交笔数准确性和动能点火触发条件。

Feature: intraday-scalping-engine, Property 4: 滑动窗口成交笔数准确性
Feature: intraday-scalping-engine, Property 5: 动能点火触发条件
**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
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

from simple_trade.services.scalping.calculators.tape_velocity import TapeVelocityMonitor
from simple_trade.services.scalping.models import (
    MomentumIgnitionData,
    TickData,
    TickDirection,
)


# ── hypothesis 策略 ──────────────────────────────────────────────

STOCK = "HK.00700"

# 基准时间戳（毫秒），对应一个合理的 Unix 时间
BASE_TS_MS = 1_700_000_000_000.0

# 时间偏移策略（毫秒），0 ~ 600 秒范围
time_offset_ms_st = st.floats(
    min_value=0.0, max_value=600_000.0,
    allow_nan=False, allow_infinity=False,
)

# 正整数笔数
tick_count_st = st.integers(min_value=1, max_value=100)


# ── 辅助函数 ──────────────────────────────────────────────────────

def make_tick(timestamp_ms: float, stock_code: str = STOCK) -> TickData:
    """创建测试用 TickData"""
    return TickData(
        stock_code=stock_code,
        price=10.0,
        volume=200,
        direction=TickDirection.BUY,
        timestamp=timestamp_ms,
        ask_price=10.0,
        bid_price=9.9,
    )


def make_monitor(
    window_seconds: float = 3.0,
    baseline_window_seconds: float = 300.0,
    ignition_multiplier: float = 3.0,
    cooldown_seconds: float = 10.0,
) -> tuple[TapeVelocityMonitor, MagicMock]:
    """创建带 mock socket_manager 的 TapeVelocityMonitor"""
    mock_sm = MagicMock()
    mock_sm.emit_to_all = AsyncMock()
    monitor = TapeVelocityMonitor(
        socket_manager=mock_sm,
        window_seconds=window_seconds,
        baseline_window_seconds=baseline_window_seconds,
        ignition_multiplier=ignition_multiplier,
        cooldown_seconds=cooldown_seconds,
    )
    return monitor, mock_sm


def count_ticks_in_window(
    timestamps_sec: list[float], now_sec: float, window_seconds: float
) -> int:
    """手动计算 [now - window, now] 范围内的 tick 数量（左开右闭，与实现一致）"""
    cutoff = now_sec - window_seconds
    return sum(1 for ts in timestamps_sec if ts >= cutoff)


# ── Property 4: 滑动窗口成交笔数准确性 ──────────────────────────
# Feature: intraday-scalping-engine, Property 4: 滑动窗口成交笔数准确性
# **Validates: Requirements 3.1**


class TestProperty4SlidingWindowAccuracy:
    """Property 4: 对于任意带时间戳的 Tick 序列，TapeVelocityMonitor 的
    3 秒滑动窗口内的成交笔数应仅包含时间戳在 [now - 3s, now] 范围内的 Tick。"""

    @given(
        offsets=st.lists(
            st.floats(
                min_value=0.0, max_value=10_000.0,
                allow_nan=False, allow_infinity=False,
            ),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=200)
    def test_window_count_matches_manual_calculation(self, offsets: list[float]):
        """窗口内笔数应等于手动计算的 [now - 3s, now] 范围内的 Tick 数量"""
        # 排序偏移量，模拟时间递增的 Tick 序列
        offsets_sorted = sorted(offsets)
        timestamps_ms = [BASE_TS_MS + off for off in offsets_sorted]

        monitor, _ = make_monitor(window_seconds=3.0)

        # 喂入所有 Tick
        for ts_ms in timestamps_ms:
            monitor.on_tick(STOCK, make_tick(ts_ms))

        # 最后一笔的时间作为 "now"
        now_sec = timestamps_ms[-1] / 1000.0
        timestamps_sec = [ts / 1000.0 for ts in timestamps_ms]

        # 手动计算期望值：实现中 cutoff = now - window，保留 ts >= cutoff 的
        # 但注意 purge 只在新 tick 到达时执行，且只清理 < cutoff 的
        cutoff = now_sec - 3.0
        expected = sum(1 for ts in timestamps_sec if ts >= cutoff)

        actual = monitor.get_window_count(STOCK)
        assert actual == expected, (
            f"窗口笔数不一致: 期望 {expected}，实际 {actual}，"
            f"now={now_sec:.3f}, cutoff={cutoff:.3f}"
        )

    @given(
        n_old=st.integers(min_value=1, max_value=20),
        n_new=st.integers(min_value=1, max_value=20),
        extra_gap_ms=st.floats(
            min_value=1.0, max_value=60_000.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200)
    def test_old_ticks_excluded_after_gap(
        self, n_old: int, n_new: int, extra_gap_ms: float
    ):
        """当新 Tick 到达时间超出窗口后，旧 Tick 应被排除"""
        monitor, _ = make_monitor(window_seconds=3.0)

        # 旧 Tick：在 BASE_TS 附近，间距 10ms
        old_span_ms = (n_old - 1) * 10.0
        for i in range(n_old):
            monitor.on_tick(STOCK, make_tick(BASE_TS_MS + i * 10))

        # 新 Tick 的起始时间 = 旧 Tick 最后一笔 + 3s 窗口 + extra_gap
        # 确保所有旧 Tick 都在新 Tick 的窗口之外
        new_base = BASE_TS_MS + old_span_ms + 3000.0 + extra_gap_ms
        for i in range(n_new):
            monitor.on_tick(STOCK, make_tick(new_base + i * 10))

        # 所有旧 Tick 应被清理，只剩新 Tick
        actual = monitor.get_window_count(STOCK)
        assert actual == n_new, (
            f"旧 Tick 未被清理: 期望 {n_new}，实际 {actual}"
        )

    @given(
        n_ticks=st.integers(min_value=2, max_value=30),
        spacing_ms=st.floats(
            min_value=1.0, max_value=2999.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200)
    def test_all_ticks_within_window_are_counted(
        self, n_ticks: int, spacing_ms: float
    ):
        """所有在 3 秒窗口内的 Tick 都应被计入"""
        # 确保总时间跨度 < 3 秒
        total_span_ms = (n_ticks - 1) * spacing_ms
        assume(total_span_ms < 3000.0)

        monitor, _ = make_monitor(window_seconds=3.0)

        for i in range(n_ticks):
            monitor.on_tick(STOCK, make_tick(BASE_TS_MS + i * spacing_ms))

        actual = monitor.get_window_count(STOCK)
        assert actual == n_ticks, (
            f"窗口内所有 Tick 应被计入: 期望 {n_ticks}，实际 {actual}"
        )

    @given(
        window_sec=st.floats(
            min_value=1.0, max_value=10.0,
            allow_nan=False, allow_infinity=False,
        ),
        offsets=st.lists(
            st.floats(
                min_value=0.0, max_value=30_000.0,
                allow_nan=False, allow_infinity=False,
            ),
            min_size=1,
            max_size=40,
        ),
    )
    @settings(max_examples=200)
    def test_configurable_window_size(
        self, window_sec: float, offsets: list[float]
    ):
        """不同窗口大小下，笔数统计应与手动计算一致"""
        offsets_sorted = sorted(offsets)
        timestamps_ms = [BASE_TS_MS + off for off in offsets_sorted]

        monitor, _ = make_monitor(window_seconds=window_sec)

        for ts_ms in timestamps_ms:
            monitor.on_tick(STOCK, make_tick(ts_ms))

        now_sec = timestamps_ms[-1] / 1000.0
        cutoff = now_sec - window_sec
        expected = sum(
            1 for ts_ms in timestamps_ms if ts_ms / 1000.0 >= cutoff
        )

        actual = monitor.get_window_count(STOCK)
        assert actual == expected


# ── Property 5: 动能点火触发条件 ─────────────────────────────────
# Feature: intraday-scalping-engine, Property 5: 动能点火触发条件
# **Validates: Requirements 3.2, 3.3, 3.4**


class TestProperty5MomentumIgnitionCondition:
    """Property 5: 对于任意 Tick 序列，当且仅当 3 秒窗口内的成交笔数
    >= 最近 5 分钟（300 秒）滚动均值 × 3 且不在冷却期内时，
    TapeVelocityMonitor 应触发动能点火事件。
    开盘不足 5 分钟时，应使用已有数据的均值作为基准。"""

    def _build_baseline(
        self,
        monitor: TapeVelocityMonitor,
        n_slices: int,
        ticks_per_slice: int,
        start_ms: float,
        window_seconds: float = 3.0,
    ) -> float:
        """构建基准历史数据，返回最后一笔 tick 的时间戳（毫秒）。

        每个切片间隔 window_seconds，每个切片内均匀分布 ticks_per_slice 笔。
        """
        ts = start_ms
        for _ in range(n_slices):
            for j in range(ticks_per_slice):
                monitor.on_tick(STOCK, make_tick(ts + j * 10))
            ts += window_seconds * 1000  # 跳到下一个切片
        return ts

    @given(
        baseline_ticks_per_slice=st.integers(min_value=2, max_value=10),
        n_slices=st.integers(min_value=3, max_value=20),
        burst_extra_factor=st.floats(
            min_value=3.0, max_value=10.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200)
    def test_ignition_fires_when_threshold_met(
        self,
        baseline_ticks_per_slice: int,
        n_slices: int,
        burst_extra_factor: float,
    ):
        """成交笔数 >= 基准均值 × 3 且不在冷却期时，应触发动能点火"""
        monitor, _ = make_monitor(
            window_seconds=3.0,
            ignition_multiplier=3.0,
            cooldown_seconds=10.0,
        )

        # 建立基准
        ts = self._build_baseline(
            monitor, n_slices, baseline_ticks_per_slice, BASE_TS_MS
        )

        baseline_avg = monitor.get_baseline_avg(STOCK)
        assume(baseline_avg > 0)

        # 在当前窗口内注入足够多的 tick 以超过 3 倍基准
        needed = int(baseline_avg * burst_extra_factor) + 1
        for i in range(needed):
            monitor.on_tick(STOCK, make_tick(ts + i * 5))

        current_count = monitor.get_window_count(STOCK)
        assume(current_count >= baseline_avg * 3.0)

        result = asyncio.get_event_loop().run_until_complete(
            monitor.check_ignition(STOCK)
        )
        assert result is not None, (
            f"应触发动能点火: count={current_count}, "
            f"baseline={baseline_avg:.2f}, "
            f"threshold={baseline_avg * 3.0:.2f}"
        )
        assert isinstance(result, MomentumIgnitionData)
        assert result.stock_code == STOCK
        assert result.multiplier >= 3.0

    @given(
        baseline_ticks_per_slice=st.integers(min_value=5, max_value=15),
        n_slices=st.integers(min_value=3, max_value=20),
        burst_ratio=st.floats(
            min_value=0.1, max_value=2.5,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200)
    def test_no_ignition_below_threshold(
        self,
        baseline_ticks_per_slice: int,
        n_slices: int,
        burst_ratio: float,
    ):
        """成交笔数 < 基准均值 × 3 时，不应触发动能点火"""
        monitor, _ = make_monitor(
            window_seconds=3.0,
            ignition_multiplier=3.0,
            cooldown_seconds=10.0,
        )

        ts = self._build_baseline(
            monitor, n_slices, baseline_ticks_per_slice, BASE_TS_MS
        )

        baseline_avg = monitor.get_baseline_avg(STOCK)
        assume(baseline_avg > 0)

        # 注入不足 3 倍基准的 tick
        target_count = max(1, int(baseline_avg * burst_ratio))
        # 确保不会达到 3 倍
        assume(target_count < baseline_avg * 3.0)

        for i in range(target_count):
            monitor.on_tick(STOCK, make_tick(ts + i * 5))

        current_count = monitor.get_window_count(STOCK)
        assume(current_count < baseline_avg * 3.0)

        result = asyncio.get_event_loop().run_until_complete(
            monitor.check_ignition(STOCK)
        )
        assert result is None, (
            f"不应触发动能点火: count={current_count}, "
            f"baseline={baseline_avg:.2f}, "
            f"threshold={baseline_avg * 3.0:.2f}"
        )

    @given(
        baseline_ticks_per_slice=st.integers(min_value=2, max_value=8),
        n_slices=st.integers(min_value=3, max_value=15),
    )
    @settings(max_examples=200)
    def test_cooldown_blocks_second_ignition(
        self,
        baseline_ticks_per_slice: int,
        n_slices: int,
    ):
        """触发后 10 秒冷却期内不重复触发"""
        cooldown_sec = 10.0
        monitor, _ = make_monitor(
            window_seconds=3.0,
            ignition_multiplier=3.0,
            cooldown_seconds=cooldown_sec,
        )

        ts = self._build_baseline(
            monitor, n_slices, baseline_ticks_per_slice, BASE_TS_MS
        )

        baseline_avg = monitor.get_baseline_avg(STOCK)
        assume(baseline_avg > 0)

        # 第一次触发
        needed = int(baseline_avg * 4) + 1
        for i in range(needed):
            monitor.on_tick(STOCK, make_tick(ts + i * 5))

        result1 = asyncio.get_event_loop().run_until_complete(
            monitor.check_ignition(STOCK)
        )
        assume(result1 is not None)  # 确保第一次确实触发了

        # 冷却期内（+5 秒，仍在 10 秒冷却期内）再次尝试
        ts2 = ts + needed * 5 + 5000  # +5 秒
        for i in range(needed):
            monitor.on_tick(STOCK, make_tick(ts2 + i * 5))

        result2 = asyncio.get_event_loop().run_until_complete(
            monitor.check_ignition(STOCK)
        )
        assert result2 is None, "冷却期内不应重复触发动能点火"

    @given(
        baseline_ticks_per_slice=st.integers(min_value=2, max_value=8),
        n_slices=st.integers(min_value=3, max_value=15),
    )
    @settings(max_examples=200)
    def test_ignition_allowed_after_cooldown_expires(
        self,
        baseline_ticks_per_slice: int,
        n_slices: int,
    ):
        """冷却期过后应允许再次触发"""
        cooldown_sec = 10.0
        monitor, _ = make_monitor(
            window_seconds=3.0,
            ignition_multiplier=3.0,
            cooldown_seconds=cooldown_sec,
        )

        ts = self._build_baseline(
            monitor, n_slices, baseline_ticks_per_slice, BASE_TS_MS
        )

        baseline_avg = monitor.get_baseline_avg(STOCK)
        assume(baseline_avg > 0)

        # 第一次触发
        needed = int(baseline_avg * 4) + 1
        for i in range(needed):
            monitor.on_tick(STOCK, make_tick(ts + i * 5))

        result1 = asyncio.get_event_loop().run_until_complete(
            monitor.check_ignition(STOCK)
        )
        assume(result1 is not None)

        # 冷却期后（+11 秒，超过 10 秒冷却期）
        ts2 = ts + needed * 5 + 11_000
        # 需要重新建立基准（因为时间跳跃，旧切片可能被清理）
        for _ in range(n_slices):
            for j in range(baseline_ticks_per_slice):
                monitor.on_tick(STOCK, make_tick(ts2 + j * 10))
            ts2 += 3000

        baseline_avg2 = monitor.get_baseline_avg(STOCK)
        assume(baseline_avg2 > 0)

        # 再次注入大量 tick
        needed2 = int(baseline_avg2 * 4) + 1
        for i in range(needed2):
            monitor.on_tick(STOCK, make_tick(ts2 + i * 5))

        current_count = monitor.get_window_count(STOCK)
        assume(current_count >= baseline_avg2 * 3.0)

        result2 = asyncio.get_event_loop().run_until_complete(
            monitor.check_ignition(STOCK)
        )
        assert result2 is not None, "冷却期过后应允许再次触发动能点火"

    @given(
        ticks_per_slice=st.integers(min_value=2, max_value=10),
        n_slices=st.integers(min_value=2, max_value=10),
    )
    @settings(max_examples=200)
    def test_early_session_uses_available_data_as_baseline(
        self,
        ticks_per_slice: int,
        n_slices: int,
    ):
        """开盘不足 5 分钟时，应使用已有数据的均值作为基准。

        模拟仅有少量切片（远不足 300 秒 / 3 秒 = 100 个切片），
        验证基准均值基于已有数据计算。
        """
        monitor, _ = make_monitor(
            window_seconds=3.0,
            baseline_window_seconds=300.0,
            ignition_multiplier=3.0,
        )

        # 模拟开盘初期：仅 n_slices 个切片（远不足 100 个）
        ts = BASE_TS_MS
        for _ in range(n_slices):
            for j in range(ticks_per_slice):
                monitor.on_tick(STOCK, make_tick(ts + j * 10))
            ts += 3000

        baseline_avg = monitor.get_baseline_avg(STOCK)

        # 开盘不足 5 分钟时，只要有历史切片就应有非零基准
        state = monitor._get_state(STOCK)
        if len(state.history_slices) > 0:
            assert baseline_avg > 0, (
                f"有 {len(state.history_slices)} 个历史切片时基准不应为 0"
            )

    @given(
        baseline_ticks_per_slice=st.integers(min_value=2, max_value=10),
        n_slices=st.integers(min_value=3, max_value=15),
    )
    @settings(max_examples=200)
    def test_no_baseline_means_no_ignition(
        self,
        baseline_ticks_per_slice: int,
        n_slices: int,
    ):
        """基准均值为 0 时（无历史数据），不应触发动能点火"""
        monitor, _ = make_monitor(window_seconds=3.0, ignition_multiplier=3.0)

        # 仅在一个窗口内发送 tick，不触发归档（没有历史切片）
        for i in range(20):
            monitor.on_tick(STOCK, make_tick(BASE_TS_MS + i * 10))

        baseline = monitor.get_baseline_avg(STOCK)
        assume(baseline <= 0)

        result = asyncio.get_event_loop().run_until_complete(
            monitor.check_ignition(STOCK)
        )
        assert result is None, "无基准数据时不应触发动能点火"
