#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TickCredibilityFilter 属性测试

使用 hypothesis 验证 Tick 数据可信度过滤的正确性。

Feature: intraday-scalping-engine, Property 24: Tick 数据可信度过滤正确性
**Validates: Requirements 17.1, 17.2, 17.3, 17.4**
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

from simple_trade.services.scalping.calculators.tick_credibility import (
    TickCredibilityFilter,
)
from simple_trade.services.scalping.models import TickData, TickDirection


# ── 常量 ──────────────────────────────────────────────────────────

STOCK = "HK.00700"

# 2024-01-15 09:30:00 UTC+8 = 01:30:00 UTC = 1705282200 秒
_MARKET_OPEN_SEC = 1705282200
_MARKET_OPEN_MS = _MARKET_OPEN_SEC * 1000


# ── hypothesis 策略 ──────────────────────────────────────────────

volume_st = st.integers(min_value=1, max_value=100_000)
price_st = st.floats(
    min_value=0.01, max_value=10000.0,
    allow_nan=False, allow_infinity=False,
)

# 集合竞价时间戳：09:30 之前（同一天 00:00~09:29 UTC+8）
# 2024-01-15 00:00 UTC+8 = 2024-01-14 16:00 UTC = 1705248000
_DAY_START_SEC = 1705248000
pre_market_ts_st = st.integers(
    min_value=_DAY_START_SEC * 1000,
    max_value=_MARKET_OPEN_MS - 1,
).map(float)

# 开盘后时间戳：09:30~15:00 UTC+8（同一天）
# 2024-01-15 15:00 UTC+8 = 07:00 UTC = 1705302000
_MARKET_CLOSE_SEC = 1705302000
post_open_ts_st = st.integers(
    min_value=_MARKET_OPEN_MS,
    max_value=_MARKET_CLOSE_SEC * 1000,
).map(float)


# ── 辅助函数 ──────────────────────────────────────────────────────

def _mock_sm():
    """创建 mock socket_manager"""
    sm = MagicMock()
    sm.emit_to_all = AsyncMock()
    return sm


def _make_filter(**kwargs) -> TickCredibilityFilter:
    """创建带 mock socket_manager 的 TickCredibilityFilter"""
    return TickCredibilityFilter(socket_manager=_mock_sm(), **kwargs)


def _make_tick(
    volume: int = 200,
    price: float = 100.0,
    timestamp_ms: float = _MARKET_OPEN_MS + 60_000,
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
# Property 24: Tick 数据可信度过滤正确性
# **Validates: Requirements 17.1, 17.2, 17.3, 17.4**
# ══════════════════════════════════════════════════════════════════


class TestProperty24_PreMarketFilter:
    """子属性 1: 集合竞价过滤
    对于任意时间戳早于 09:30 UTC+8 的 Tick，filter_tick 返回 (False, False)，
    且该 Tick 不会被加入滚动窗口。
    **Validates: Requirements 17.1**
    """

    @given(
        ts=pre_market_ts_st,
        vol=volume_st,
        price=price_st,
    )
    @settings(max_examples=200)
    def test_pre_market_tick_discarded(self, ts: float, vol: int, price: float):
        """集合竞价 Tick 应被丢弃，返回 (False, False)"""
        f = _make_filter()
        tick = _make_tick(volume=vol, price=price, timestamp_ms=ts)

        should_dispatch, is_outlier = f.filter_tick(STOCK, tick)

        assert should_dispatch is False, "集合竞价 Tick 不应分发"
        assert is_outlier is False, "集合竞价 Tick 不应标记为 OUTLIER"

    @given(
        ts=pre_market_ts_st,
        vol=volume_st,
        price=price_st,
    )
    @settings(max_examples=200)
    def test_pre_market_tick_not_in_rolling_window(
        self, ts: float, vol: int, price: float
    ):
        """集合竞价 Tick 不应加入滚动窗口"""
        f = _make_filter()
        tick = _make_tick(volume=vol, price=price, timestamp_ms=ts)

        f.filter_tick(STOCK, tick)

        # 滚动均值应为 None（窗口为空）
        assert f.get_rolling_avg_volume(STOCK) is None, (
            "集合竞价 Tick 不应影响滚动窗口"
        )


class TestProperty24_RollingAverage:
    """子属性 2: 滚动均值正确性
    处理 N 笔正常 Tick 后，get_rolling_avg_volume 返回 sum(volumes)/N。
    超过 rolling_window_size 笔后，只使用最近 rolling_window_size 笔。
    **Validates: Requirements 17.2**
    """

    @given(
        volumes=st.lists(
            st.integers(min_value=1, max_value=50_000),
            min_size=1,
            max_size=80,
        ),
    )
    @settings(max_examples=200)
    def test_avg_within_window(self, volumes: list[int]):
        """窗口未满时，均值 = sum(volumes) / len(volumes)"""
        window_size = 100
        f = _make_filter(rolling_window_size=window_size)
        assume(len(volumes) <= window_size)

        ts = _MARKET_OPEN_MS + 60_000
        for v in volumes:
            tick = _make_tick(volume=v, timestamp_ms=ts)
            f.filter_tick(STOCK, tick)
            ts += 1000

        avg = f.get_rolling_avg_volume(STOCK)
        expected = sum(volumes) / len(volumes)
        assert avg is not None
        assert abs(avg - expected) < 1e-6, (
            f"均值不正确: got {avg}, expected {expected}"
        )

    @given(
        volumes=st.lists(
            st.integers(min_value=1, max_value=50_000),
            min_size=101,
            max_size=200,
        ),
    )
    @settings(max_examples=200)
    def test_avg_exceeds_window(self, volumes: list[int]):
        """超过窗口大小后，只使用最近 100 笔"""
        window_size = 100
        f = _make_filter(rolling_window_size=window_size)

        ts = _MARKET_OPEN_MS + 60_000
        for v in volumes:
            tick = _make_tick(volume=v, timestamp_ms=ts)
            f.filter_tick(STOCK, tick)
            ts += 1000

        avg = f.get_rolling_avg_volume(STOCK)
        recent = volumes[-window_size:]
        expected = sum(recent) / len(recent)
        assert avg is not None
        assert abs(avg - expected) < 1e-6, (
            f"滚动均值应只使用最近 {window_size} 笔"
        )


class TestProperty24_OutlierDetection:
    """子属性 3: 异常大单检测
    当滚动窗口中有 >= min_samples_for_detection 个样本时，
    成交量 > avg * outlier_multiplier 的 Tick 返回 (False, True)，
    且 OUTLIER 不加入滚动窗口。
    **Validates: Requirements 17.3**
    """

    @given(
        base_vol=st.integers(min_value=100, max_value=1000),
        n_samples=st.integers(min_value=5, max_value=20),
        extra_multiplier=st.floats(
            min_value=1.01, max_value=10.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(max_examples=200)
    def test_outlier_detected_and_not_in_window(
        self, base_vol: int, n_samples: int, extra_multiplier: float
    ):
        """成交量超过均值 50 倍的 Tick 应被标记为 OUTLIER，不加入窗口"""
        multiplier = 50.0
        f = _make_filter(
            outlier_multiplier=multiplier,
            min_samples_for_detection=5,
        )

        # 先填充 n_samples 笔正常 Tick 建立基线
        ts = _MARKET_OPEN_MS + 60_000
        for _ in range(n_samples):
            tick = _make_tick(volume=base_vol, timestamp_ms=ts)
            f.filter_tick(STOCK, tick)
            ts += 1000

        avg_before = f.get_rolling_avg_volume(STOCK)
        assert avg_before is not None

        # 构造一笔超过阈值的 Tick
        outlier_vol = int(avg_before * multiplier * extra_multiplier) + 1
        outlier_tick = _make_tick(volume=outlier_vol, timestamp_ms=ts)

        should_dispatch, is_outlier = f.filter_tick(STOCK, outlier_tick)

        assert should_dispatch is False, "OUTLIER 不应分发"
        assert is_outlier is True, "应标记为 OUTLIER"

        # 均值不应被 OUTLIER 影响
        avg_after = f.get_rolling_avg_volume(STOCK)
        assert abs(avg_after - avg_before) < 1e-6, (
            "OUTLIER 不应加入滚动窗口"
        )

    @given(
        base_vol=st.integers(min_value=100, max_value=1000),
        n_samples=st.integers(min_value=5, max_value=20),
    )
    @settings(max_examples=200)
    def test_just_below_threshold_not_outlier(
        self, base_vol: int, n_samples: int
    ):
        """成交量恰好不超过阈值的 Tick 不应被标记为 OUTLIER"""
        multiplier = 50.0
        f = _make_filter(
            outlier_multiplier=multiplier,
            min_samples_for_detection=5,
        )

        ts = _MARKET_OPEN_MS + 60_000
        for _ in range(n_samples):
            tick = _make_tick(volume=base_vol, timestamp_ms=ts)
            f.filter_tick(STOCK, tick)
            ts += 1000

        avg = f.get_rolling_avg_volume(STOCK)
        assert avg is not None

        # 恰好等于阈值的 Tick（不超过）
        border_vol = int(avg * multiplier)
        border_tick = _make_tick(volume=border_vol, timestamp_ms=ts)

        should_dispatch, is_outlier = f.filter_tick(STOCK, border_tick)

        assert should_dispatch is True, "未超过阈值的 Tick 应正常分发"
        assert is_outlier is False, "未超过阈值不应标记为 OUTLIER"


class TestProperty24_InsufficientSamples:
    """子属性 4: 不足样本时跳过检测
    当滚动窗口中样本数 < min_samples_for_detection 时，
    即使成交量极大也返回 (True, False) 并加入窗口。
    **Validates: Requirements 17.4**
    """

    @given(
        n_existing=st.integers(min_value=0, max_value=4),
        huge_vol=st.integers(min_value=1_000_000, max_value=100_000_000),
    )
    @settings(max_examples=200)
    def test_skip_detection_below_min_samples(
        self, n_existing: int, huge_vol: int
    ):
        """不足 5 笔时，极大成交量 Tick 也应正常放行"""
        f = _make_filter(min_samples_for_detection=5)

        # 先填充 n_existing 笔小量 Tick
        ts = _MARKET_OPEN_MS + 60_000
        for _ in range(n_existing):
            tick = _make_tick(volume=100, timestamp_ms=ts)
            f.filter_tick(STOCK, tick)
            ts += 1000

        # 发送一笔极大成交量 Tick
        huge_tick = _make_tick(volume=huge_vol, timestamp_ms=ts)
        should_dispatch, is_outlier = f.filter_tick(STOCK, huge_tick)

        assert should_dispatch is True, (
            f"不足 {5} 笔时应跳过异常检测，正常放行"
        )
        assert is_outlier is False, "不足样本时不应标记 OUTLIER"

    @given(
        huge_vol=st.integers(min_value=1_000_000, max_value=100_000_000),
    )
    @settings(max_examples=200)
    def test_huge_tick_added_to_window_when_insufficient(
        self, huge_vol: int
    ):
        """不足样本时，极大 Tick 应被加入滚动窗口"""
        f = _make_filter(min_samples_for_detection=5)

        ts = _MARKET_OPEN_MS + 60_000
        huge_tick = _make_tick(volume=huge_vol, timestamp_ms=ts)
        f.filter_tick(STOCK, huge_tick)

        avg = f.get_rolling_avg_volume(STOCK)
        assert avg is not None
        assert abs(avg - huge_vol) < 1e-6, (
            "不足样本时 Tick 应加入窗口"
        )


class TestProperty24_NormalTickPassthrough:
    """子属性 5: 正常 Tick 放行
    开盘后、成交量在阈值内的 Tick 返回 (True, False) 并加入滚动窗口。
    **Validates: Requirements 17.1, 17.2, 17.3, 17.4**
    """

    @given(
        volumes=st.lists(
            st.integers(min_value=100, max_value=4900),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=200)
    def test_normal_ticks_all_dispatched(self, volumes: list[int]):
        """所有正常 Tick 都应被放行"""
        f = _make_filter(
            outlier_multiplier=50.0,
            min_samples_for_detection=5,
        )

        ts = _MARKET_OPEN_MS + 60_000
        for v in volumes:
            tick = _make_tick(volume=v, timestamp_ms=ts)
            should_dispatch, is_outlier = f.filter_tick(STOCK, tick)

            assert should_dispatch is True, "正常 Tick 应被放行"
            assert is_outlier is False, "正常 Tick 不应标记为 OUTLIER"
            ts += 1000

    @given(
        volumes=st.lists(
            st.integers(min_value=100, max_value=4900),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=200)
    def test_normal_ticks_all_in_window(self, volumes: list[int]):
        """所有正常 Tick 都应加入滚动窗口，窗口大小等于 Tick 数量"""
        f = _make_filter(
            rolling_window_size=100,
            outlier_multiplier=50.0,
            min_samples_for_detection=5,
        )

        ts = _MARKET_OPEN_MS + 60_000
        for v in volumes:
            tick = _make_tick(volume=v, timestamp_ms=ts)
            f.filter_tick(STOCK, tick)
            ts += 1000

        avg = f.get_rolling_avg_volume(STOCK)
        expected = sum(volumes) / len(volumes)
        assert avg is not None
        assert abs(avg - expected) < 1e-6
