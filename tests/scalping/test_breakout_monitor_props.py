"""
BreakoutSurvivalMonitor 属性测试

Feature: intraday-scalping-engine, Property 19: 突破生存法则判定正确性
**Validates: Requirements 14.4, 14.6**

测试突破生存法则的五个核心属性：
1. 真突破判定：survival_seconds 到期 + 流速 >= 3x + 推进 >= 2 Tick → TrueBreakoutConfirmData
2. 假突破判定（流速不足）：survival_seconds 到期 + 流速 < 3x → FakeBreakoutAlertData
3. 假突破判定（价格推进不足）：survival_seconds 到期 + 流速 >= 3x + 推进 < 2 → FakeBreakoutAlertData
4. 未到期返回 None：elapsed < survival_seconds → None
5. market_type 窗口选择：us → 3.0s, hk → 5.0s
"""

import asyncio
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

from simple_trade.services.scalping.detectors.breakout_monitor import (
    BreakoutSurvivalMonitor,
)
from simple_trade.services.scalping.models import (
    FakeBreakoutAlertData,
    TickData,
    TickDirection,
    TrueBreakoutConfirmData,
)

STOCK = "HK.00700"
BASE_MS = 1_700_000_000_000.0  # 合理的 Unix 毫秒基准时间戳


# ── 辅助函数 ──────────────────────────────────────────────────────


def _mock_sm():
    sm = MagicMock()
    sm.emit_to_all = AsyncMock()
    return sm


def _make_tick(price: float, timestamp_ms: float) -> TickData:
    return TickData(
        stock_code=STOCK,
        price=price,
        volume=200,
        direction=TickDirection.BUY,
        timestamp=timestamp_ms,
        ask_price=price + 0.01,
        bid_price=price - 0.01,
    )


def _make_monitor(
    market_type: str = "us",
    survival_seconds: float | None = None,
    velocity_multiplier: float = 3.0,
    min_advance_ticks: int = 2,
    tick_size: float = 0.01,
) -> tuple[BreakoutSurvivalMonitor, MagicMock, MagicMock, MagicMock]:
    """返回 (monitor, mock_sm, mock_tape_velocity, mock_spoofing_filter)"""
    sm = _mock_sm()
    tv = MagicMock()
    tv.get_baseline_avg = MagicMock(return_value=10.0)
    tv.get_window_count = MagicMock(return_value=0)
    sf = MagicMock()
    sf.get_active_levels = MagicMock(return_value=[])

    monitor = BreakoutSurvivalMonitor(
        socket_manager=sm,
        tape_velocity=tv,
        spoofing_filter=sf,
        market_type=market_type,
        survival_seconds=survival_seconds,
        velocity_multiplier=velocity_multiplier,
        min_advance_ticks=min_advance_ticks,
        tick_size=tick_size,
    )
    return monitor, sm, tv, sf


# ── Hypothesis 策略 ───────────────────────────────────────────────

# 突破价格：合理的股票价格范围
st_breakout_price = st.floats(min_value=1.0, max_value=5000.0, allow_nan=False, allow_infinity=False)

# 基准流速：正数
st_baseline_velocity = st.floats(min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False)

# survival_seconds：合理的监控窗口
st_survival = st.floats(min_value=0.5, max_value=30.0, allow_nan=False, allow_infinity=False)

# tick_size：最小价格变动单位
st_tick_size = st.floats(min_value=0.001, max_value=1.0, allow_nan=False, allow_infinity=False)

# 流速倍数（用于 get_window_count 返回值的计算）
st_velocity_ratio = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)

# 价格推进 Tick 数
st_advance_ticks = st.integers(min_value=0, max_value=100)


# ── Property 19: 突破生存法则判定正确性 ───────────────────────────


class TestProperty19TrueBreakout:
    """真突破判定：survival_seconds 到期 + 流速 >= 3x + 推进 >= 2 Tick
    → 返回 TrueBreakoutConfirmData"""

    @settings(max_examples=200)
    @given(
        breakout_price=st_breakout_price,
        baseline_velocity=st_baseline_velocity,
        survival_sec=st_survival,
        tick_size=st_tick_size,
        velocity_ratio=st.floats(
            min_value=3.0, max_value=50.0,
            allow_nan=False, allow_infinity=False,
        ),
        advance_ticks=st.integers(min_value=2, max_value=50),
    )
    @pytest.mark.asyncio
    async def test_true_breakout_when_velocity_and_advance_sufficient(
        self,
        breakout_price: float,
        baseline_velocity: float,
        survival_sec: float,
        tick_size: float,
        velocity_ratio: float,
        advance_ticks: int,
    ):
        """当 survival_seconds 到期、流速 >= 3x、价格推进 >= 2 Tick 时，
        应返回 TrueBreakoutConfirmData"""
        monitor, sm, tv, _ = _make_monitor(
            survival_seconds=survival_sec,
            tick_size=tick_size,
        )

        # 使用 ceil 确保 window_count / baseline_velocity >= velocity_ratio
        # int() 会截断导致实际比值低于预期
        window_count = math.ceil(velocity_ratio * baseline_velocity)
        tv.get_window_count.return_value = window_count

        # 初始 tick 设置时间
        monitor.on_tick(STOCK, _make_tick(breakout_price, BASE_MS))
        monitor.start_monitoring(STOCK, breakout_price, baseline_velocity)

        # 价格推进到 breakout_price + advance_ticks * tick_size
        advanced_price = breakout_price + advance_ticks * tick_size
        monitor.on_tick(STOCK, _make_tick(advanced_price, BASE_MS + 500))

        # 到期后的 tick（elapsed >= survival_sec）
        expire_ms = BASE_MS + (survival_sec + 0.5) * 1000
        monitor.on_tick(STOCK, _make_tick(advanced_price, expire_ms))

        result = await monitor.evaluate_survival(STOCK)

        assert result is not None
        assert isinstance(result, TrueBreakoutConfirmData)
        assert result.stock_code == STOCK
        assert result.breakout_price == breakout_price
        assert result.advance_ticks >= 2


class TestProperty19FakeBreakoutLowVelocity:
    """假突破判定（流速不足）：survival_seconds 到期 + 流速 < 3x
    → 返回 FakeBreakoutAlertData"""

    @settings(max_examples=200)
    @given(
        breakout_price=st_breakout_price,
        baseline_velocity=st_baseline_velocity,
        survival_sec=st_survival,
        tick_size=st_tick_size,
        velocity_ratio=st.floats(
            min_value=0.0, max_value=2.99,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @pytest.mark.asyncio
    async def test_fake_breakout_when_velocity_insufficient(
        self,
        breakout_price: float,
        baseline_velocity: float,
        survival_sec: float,
        tick_size: float,
        velocity_ratio: float,
    ):
        """当 survival_seconds 到期但流速 < 3x 时，
        无论价格推进多少，应返回 FakeBreakoutAlertData"""
        monitor, sm, tv, _ = _make_monitor(
            survival_seconds=survival_sec,
            tick_size=tick_size,
        )

        window_count = int(velocity_ratio * baseline_velocity)
        tv.get_window_count.return_value = window_count

        # 初始 tick
        monitor.on_tick(STOCK, _make_tick(breakout_price, BASE_MS))
        monitor.start_monitoring(STOCK, breakout_price, baseline_velocity)

        # 即使价格推进了很多 Tick，流速不足仍应判定为假突破
        advanced_price = breakout_price + 10 * tick_size
        monitor.on_tick(STOCK, _make_tick(advanced_price, BASE_MS + 500))

        # 到期
        expire_ms = BASE_MS + (survival_sec + 0.5) * 1000
        monitor.on_tick(STOCK, _make_tick(advanced_price, expire_ms))

        result = await monitor.evaluate_survival(STOCK)

        assert result is not None
        assert isinstance(result, FakeBreakoutAlertData)
        assert result.stock_code == STOCK
        assert result.breakout_price == breakout_price


class TestProperty19FakeBreakoutLowAdvance:
    """假突破判定（价格推进不足）：survival_seconds 到期 + 流速 >= 3x
    但 advance_ticks < 2 → 返回 FakeBreakoutAlertData"""

    @settings(max_examples=200)
    @given(
        breakout_price=st_breakout_price,
        baseline_velocity=st_baseline_velocity,
        survival_sec=st_survival,
        tick_size=st_tick_size,
        velocity_ratio=st.floats(
            min_value=3.0, max_value=50.0,
            allow_nan=False, allow_infinity=False,
        ),
        advance_ticks=st.integers(min_value=0, max_value=1),
    )
    @pytest.mark.asyncio
    async def test_fake_breakout_when_advance_insufficient(
        self,
        breakout_price: float,
        baseline_velocity: float,
        survival_sec: float,
        tick_size: float,
        velocity_ratio: float,
        advance_ticks: int,
    ):
        """当 survival_seconds 到期、流速 >= 3x 但价格推进 < 2 Tick 时，
        应返回 FakeBreakoutAlertData"""
        monitor, sm, tv, _ = _make_monitor(
            survival_seconds=survival_sec,
            tick_size=tick_size,
        )

        # 使用 ceil 确保流速确实 >= 3x，验证的是"价格推进不足"这一单一原因
        window_count = math.ceil(velocity_ratio * baseline_velocity)
        tv.get_window_count.return_value = window_count

        # 初始 tick
        monitor.on_tick(STOCK, _make_tick(breakout_price, BASE_MS))
        monitor.start_monitoring(STOCK, breakout_price, baseline_velocity)

        # 价格仅推进 advance_ticks 个 Tick（0 或 1，不足 2）
        advanced_price = breakout_price + advance_ticks * tick_size
        monitor.on_tick(STOCK, _make_tick(advanced_price, BASE_MS + 500))

        # 到期
        expire_ms = BASE_MS + (survival_sec + 0.5) * 1000
        monitor.on_tick(STOCK, _make_tick(advanced_price, expire_ms))

        result = await monitor.evaluate_survival(STOCK)

        assert result is not None
        assert isinstance(result, FakeBreakoutAlertData)
        assert result.stock_code == STOCK
        assert result.breakout_price == breakout_price


class TestProperty19NotExpired:
    """未到期返回 None：elapsed < survival_seconds → None"""

    @settings(max_examples=200)
    @given(
        breakout_price=st_breakout_price,
        baseline_velocity=st_baseline_velocity,
        survival_sec=st.floats(
            min_value=2.0, max_value=30.0,
            allow_nan=False, allow_infinity=False,
        ),
        elapsed_ratio=st.floats(
            min_value=0.01, max_value=0.95,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @pytest.mark.asyncio
    async def test_returns_none_when_not_expired(
        self,
        breakout_price: float,
        baseline_velocity: float,
        survival_sec: float,
        elapsed_ratio: float,
    ):
        """当 elapsed < survival_seconds 时，应返回 None 且监控仍活跃"""
        monitor, _, tv, _ = _make_monitor(survival_seconds=survival_sec)

        tv.get_window_count.return_value = 100  # 高流速，不影响结果

        # 初始 tick
        monitor.on_tick(STOCK, _make_tick(breakout_price, BASE_MS))
        monitor.start_monitoring(STOCK, breakout_price, baseline_velocity)

        # 仅经过 elapsed_ratio * survival_sec（不到期）
        elapsed_ms = elapsed_ratio * survival_sec * 1000
        monitor.on_tick(
            STOCK,
            _make_tick(breakout_price + 0.05, BASE_MS + elapsed_ms),
        )

        result = await monitor.evaluate_survival(STOCK)

        assert result is None
        # 监控仍然活跃
        assert len(monitor.get_active_monitors(STOCK)) == 1


class TestProperty19MarketTypeWindow:
    """market_type 窗口选择：us → 3.0s, hk → 5.0s"""

    @settings(max_examples=200)
    @given(
        market_type=st.sampled_from(["us", "hk"]),
        breakout_price=st_breakout_price,
        baseline_velocity=st_baseline_velocity,
    )
    @pytest.mark.asyncio
    async def test_market_type_determines_survival_window(
        self,
        market_type: str,
        breakout_price: float,
        baseline_velocity: float,
    ):
        """market_type 应正确决定 survival_seconds：us=3.0, hk=5.0

        在 survival_seconds 之前评估应返回 None，
        在 survival_seconds 之后评估应返回非 None。
        """
        expected_seconds = {"us": 3.0, "hk": 5.0}[market_type]
        monitor, _, tv, _ = _make_monitor(market_type=market_type)

        # 验证内部 survival_seconds 设置正确
        assert monitor._survival_seconds == expected_seconds

        tv.get_window_count.return_value = 50  # 高流速

        # 初始 tick + 启动监控
        monitor.on_tick(STOCK, _make_tick(breakout_price, BASE_MS))
        monitor.start_monitoring(STOCK, breakout_price, baseline_velocity)

        # 价格推进足够
        advanced_price = breakout_price + 0.05
        monitor.on_tick(
            STOCK, _make_tick(advanced_price, BASE_MS + 500),
        )

        # 在 survival_seconds 之前（取 80% 时间点）评估 → None
        before_ms = BASE_MS + expected_seconds * 0.8 * 1000
        monitor.on_tick(STOCK, _make_tick(advanced_price, before_ms))
        result_before = await monitor.evaluate_survival(STOCK)
        assert result_before is None

        # 在 survival_seconds 之后评估 → 非 None
        after_ms = BASE_MS + (expected_seconds + 0.5) * 1000
        monitor.on_tick(STOCK, _make_tick(advanced_price, after_ms))
        result_after = await monitor.evaluate_survival(STOCK)
        assert result_after is not None


class TestProperty19MutualExclusivity:
    """真突破和假突破结果互斥：同一次评估只能返回其中一种"""

    @settings(max_examples=200)
    @given(
        breakout_price=st_breakout_price,
        baseline_velocity=st_baseline_velocity,
        survival_sec=st_survival,
        tick_size=st_tick_size,
        velocity_ratio=st_velocity_ratio,
        advance_ticks=st_advance_ticks,
    )
    @pytest.mark.asyncio
    async def test_result_is_either_true_or_fake_never_both(
        self,
        breakout_price: float,
        baseline_velocity: float,
        survival_sec: float,
        tick_size: float,
        velocity_ratio: float,
        advance_ticks: int,
    ):
        """到期后的评估结果只能是 TrueBreakoutConfirmData 或
        FakeBreakoutAlertData 之一，不可能同时为两者"""
        monitor, _, tv, _ = _make_monitor(
            survival_seconds=survival_sec,
            tick_size=tick_size,
        )

        window_count = int(velocity_ratio * baseline_velocity)
        tv.get_window_count.return_value = window_count

        # 初始 tick + 启动监控
        monitor.on_tick(STOCK, _make_tick(breakout_price, BASE_MS))
        monitor.start_monitoring(STOCK, breakout_price, baseline_velocity)

        # 价格推进
        advanced_price = breakout_price + advance_ticks * tick_size
        monitor.on_tick(STOCK, _make_tick(advanced_price, BASE_MS + 500))

        # 到期
        expire_ms = BASE_MS + (survival_sec + 0.5) * 1000
        monitor.on_tick(STOCK, _make_tick(advanced_price, expire_ms))

        result = await monitor.evaluate_survival(STOCK)

        # 到期后必定返回结果
        assert result is not None
        # 结果类型互斥
        is_true = isinstance(result, TrueBreakoutConfirmData)
        is_fake = isinstance(result, FakeBreakoutAlertData)
        assert is_true != is_fake, "结果必须是真突破或假突破之一，不可同时为两者"

        # 验证判定逻辑一致性
        actual_ratio = (
            window_count / baseline_velocity
            if baseline_velocity > 0
            else 0.0
        )
        actual_advance = round(
            (advanced_price - breakout_price) / tick_size
        ) if tick_size > 0 else 0

        if actual_ratio >= 3.0 and actual_advance >= 2:
            assert is_true, (
                f"流速比={actual_ratio:.2f}>=3.0 且推进={actual_advance}>=2 "
                f"应为真突破"
            )
        else:
            assert is_fake, (
                f"流速比={actual_ratio:.2f} 或推进={actual_advance} 不足，"
                f"应为假突破"
            )
