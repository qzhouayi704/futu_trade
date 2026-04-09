"""
BreakoutSurvivalMonitor 单元测试

验证突破生存法则监控器的核心逻辑：
- market_type 参数自动选择窗口
- 突破监控启动与到期评估
- 假突破和真突破判定
- 活跃监控列表管理
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

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
    PriceLevelData,
    PriceLevelAction,
    PriceLevelSide,
    TickData,
    TickDirection,
)

STOCK = "HK.00700"


# ── 辅助函数 ──────────────────────────────────────────────────────


def _mock_sm():
    sm = MagicMock()
    sm.emit_to_all = AsyncMock()
    return sm


def _make_tick(
    price: float, timestamp_ms: float, volume: int = 200
) -> TickData:
    return TickData(
        stock_code=STOCK,
        price=price,
        volume=volume,
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


# ── market_type 参数测试 ──────────────────────────────────────────


class TestMarketTypeDefaults:
    """测试 market_type 参数自动选择 survival_seconds"""

    def test_us_default_3_seconds(self):
        monitor, *_ = _make_monitor(market_type="us")
        assert monitor._survival_seconds == 3.0

    def test_hk_default_5_seconds(self):
        monitor, *_ = _make_monitor(market_type="hk")
        assert monitor._survival_seconds == 5.0

    def test_explicit_override(self):
        monitor, *_ = _make_monitor(
            market_type="us", survival_seconds=4.0
        )
        assert monitor._survival_seconds == 4.0

    def test_unknown_market_fallback(self):
        """未知市场类型回退到 3.0 秒"""
        monitor, *_ = _make_monitor(market_type="jp")
        assert monitor._survival_seconds == 3.0


# ── start_monitoring 测试 ─────────────────────────────────────────


class TestStartMonitoring:
    """测试突破监控启动"""

    def test_start_creates_entry(self):
        monitor, *_ = _make_monitor()
        base_ms = 1_700_000_000_000.0
        # 先发一个 tick 设置时间
        monitor.on_tick(STOCK, _make_tick(100.0, base_ms))
        monitor.start_monitoring(STOCK, 100.0, 10.0)

        monitors = monitor.get_active_monitors(STOCK)
        assert len(monitors) == 1
        assert monitors[0]["breakout_price"] == 100.0
        assert monitors[0]["baseline_velocity"] == 10.0

    def test_multiple_monitors(self):
        monitor, *_ = _make_monitor()
        base_ms = 1_700_000_000_000.0
        monitor.on_tick(STOCK, _make_tick(100.0, base_ms))
        monitor.start_monitoring(STOCK, 100.0, 10.0)
        monitor.start_monitoring(STOCK, 101.0, 12.0)

        monitors = monitor.get_active_monitors(STOCK)
        assert len(monitors) == 2


# ── evaluate_survival 测试 ────────────────────────────────────────


class TestEvaluateSurvival:
    """测试突破生存评估"""

    @pytest.mark.asyncio
    async def test_fake_breakout_low_velocity_no_advance(self):
        """流速回落 + 价格未推进 → 假突破"""
        monitor, sm, tv, _ = _make_monitor(survival_seconds=3.0)
        base_ms = 1_700_000_000_000.0  # 合理的 Unix 毫秒时间戳

        # 初始 tick
        monitor.on_tick(STOCK, _make_tick(100.0, base_ms))
        monitor.start_monitoring(STOCK, 100.0, 10.0)

        # 3.5 秒后 tick，价格没有推进
        monitor.on_tick(STOCK, _make_tick(100.0, base_ms + 3500))

        # 流速低于 3 倍
        tv.get_window_count.return_value = 20  # 20/10 = 2x < 3x

        result = await monitor.evaluate_survival(STOCK)
        assert result is not None
        assert result.stock_code == STOCK
        assert result.breakout_price == 100.0
        sm.emit_to_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_true_breakout_high_velocity_and_advance(self):
        """流速维持 + 价格推进 → 真突破"""
        monitor, sm, tv, _ = _make_monitor(survival_seconds=3.0)
        base_ms = 1_700_000_000_000.0

        # 初始 tick
        monitor.on_tick(STOCK, _make_tick(100.0, base_ms))
        monitor.start_monitoring(STOCK, 100.0, 10.0)

        # 价格推进 3 Tick（>= 2 Tick 阈值）
        monitor.on_tick(STOCK, _make_tick(100.03, base_ms + 1000))
        # 3.5 秒后到期
        monitor.on_tick(STOCK, _make_tick(100.03, base_ms + 3500))

        # 流速维持 3 倍以上
        tv.get_window_count.return_value = 35  # 35/10 = 3.5x >= 3x

        result = await monitor.evaluate_survival(STOCK)
        assert result is not None
        assert result.stock_code == STOCK
        assert result.breakout_price == 100.0
        assert result.advance_ticks == 3
        sm.emit_to_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_not_expired_returns_none(self):
        """未到期时返回 None"""
        monitor, _, tv, _ = _make_monitor(survival_seconds=3.0)
        base_ms = 1_700_000_000_000.0

        monitor.on_tick(STOCK, _make_tick(100.0, base_ms))
        monitor.start_monitoring(STOCK, 100.0, 10.0)

        # 仅过了 2 秒
        monitor.on_tick(STOCK, _make_tick(100.02, base_ms + 2000))

        result = await monitor.evaluate_survival(STOCK)
        assert result is None
        # 监控仍然活跃
        assert len(monitor.get_active_monitors(STOCK)) == 1

    @pytest.mark.asyncio
    async def test_no_monitors_returns_none(self):
        """无活跃监控时返回 None"""
        monitor, *_ = _make_monitor()
        result = await monitor.evaluate_survival(STOCK)
        assert result is None


# ── on_tick 行为测试 ──────────────────────────────────────────────


class TestOnTick:
    """测试 on_tick 方法"""

    def test_updates_day_high(self):
        monitor, *_ = _make_monitor()
        base_ms = 1_700_000_000_000.0
        monitor.on_tick(STOCK, _make_tick(100.0, base_ms))
        assert monitor._get_state(STOCK).day_high == 100.0

        monitor.on_tick(STOCK, _make_tick(101.0, base_ms + 1000))
        assert monitor._get_state(STOCK).day_high == 101.0

        # 价格回落不影响日内高点
        monitor.on_tick(STOCK, _make_tick(99.0, base_ms + 2000))
        assert monitor._get_state(STOCK).day_high == 101.0

    def test_updates_highest_price_in_monitor(self):
        monitor, *_ = _make_monitor()
        base_ms = 1_700_000_000_000.0
        monitor.on_tick(STOCK, _make_tick(100.0, base_ms))
        monitor.start_monitoring(STOCK, 100.0, 10.0)

        monitor.on_tick(STOCK, _make_tick(100.05, base_ms + 500))
        monitors = monitor.get_active_monitors(STOCK)
        assert monitors[0]["highest_price"] == 100.05

    def test_triggers_breakout_on_resistance(self):
        """价格突破红色阻力线时自动启动监控"""
        monitor, _, tv, sf = _make_monitor()
        base_ms = 1_700_000_000_000.0
        tv.get_baseline_avg.return_value = 10.0

        # 设置阻力线
        sf.get_active_levels.return_value = [
            PriceLevelData(
                stock_code=STOCK,
                price=100.50,
                volume=5000,
                side=PriceLevelSide.RESISTANCE,
                action=PriceLevelAction.CREATE,
                timestamp="2024-01-01T10:00:00",
            )
        ]

        # 价格突破阻力线
        monitor.on_tick(STOCK, _make_tick(100.50, base_ms))
        monitors = monitor.get_active_monitors(STOCK)
        assert len(monitors) == 1
        assert monitors[0]["breakout_price"] == 100.50


# ── reset 测试 ────────────────────────────────────────────────────


class TestReset:
    """测试重置功能"""

    def test_reset_clears_state(self):
        monitor, *_ = _make_monitor()
        base_ms = 1_700_000_000_000.0
        monitor.on_tick(STOCK, _make_tick(100.0, base_ms))
        monitor.start_monitoring(STOCK, 100.0, 10.0)
        assert len(monitor.get_active_monitors(STOCK)) == 1

        monitor.reset(STOCK)
        assert len(monitor.get_active_monitors(STOCK)) == 0

    def test_reset_nonexistent_stock(self):
        """重置不存在的股票不报错"""
        monitor, *_ = _make_monitor()
        monitor.reset("NONEXISTENT")  # 不应抛异常


# ── 边界条件测试 ──────────────────────────────────────────────────


class TestEdgeCases:
    """边界条件测试"""

    @pytest.mark.asyncio
    async def test_velocity_exactly_at_threshold(self):
        """流速恰好等于 3 倍 → 需要同时满足价格推进才是真突破"""
        monitor, _, tv, _ = _make_monitor(survival_seconds=3.0)
        base_ms = 1_700_000_000_000.0

        monitor.on_tick(STOCK, _make_tick(100.0, base_ms))
        monitor.start_monitoring(STOCK, 100.0, 10.0)

        # 价格推进 2 Tick
        monitor.on_tick(STOCK, _make_tick(100.02, base_ms + 1000))
        monitor.on_tick(STOCK, _make_tick(100.02, base_ms + 3500))

        # 流速恰好 3 倍
        tv.get_window_count.return_value = 30  # 30/10 = 3.0x

        result = await monitor.evaluate_survival(STOCK)
        # 流速 >= 3x 且价格推进 >= 2 Tick → 真突破
        assert result is not None
        assert hasattr(result, "advance_ticks")

    @pytest.mark.asyncio
    async def test_price_advance_exactly_2_ticks(self):
        """价格恰好推进 2 Tick → 满足条件"""
        monitor, _, tv, _ = _make_monitor(survival_seconds=3.0)
        base_ms = 1_700_000_000_000.0

        monitor.on_tick(STOCK, _make_tick(100.0, base_ms))
        monitor.start_monitoring(STOCK, 100.0, 10.0)

        monitor.on_tick(STOCK, _make_tick(100.02, base_ms + 1000))
        monitor.on_tick(STOCK, _make_tick(100.02, base_ms + 3500))

        tv.get_window_count.return_value = 40  # 4x

        result = await monitor.evaluate_survival(STOCK)
        assert result is not None
        assert hasattr(result, "advance_ticks")
        assert result.advance_ticks == 2

    @pytest.mark.asyncio
    async def test_price_advance_only_1_tick(self):
        """价格仅推进 1 Tick → 不满足，假突破"""
        monitor, _, tv, _ = _make_monitor(survival_seconds=3.0)
        base_ms = 1_700_000_000_000.0

        monitor.on_tick(STOCK, _make_tick(100.0, base_ms))
        monitor.start_monitoring(STOCK, 100.0, 10.0)

        monitor.on_tick(STOCK, _make_tick(100.01, base_ms + 1000))
        monitor.on_tick(STOCK, _make_tick(100.01, base_ms + 3500))

        tv.get_window_count.return_value = 40  # 4x

        result = await monitor.evaluate_survival(STOCK)
        # 流速够但价格推进不够 → 假突破
        assert result is not None
        assert hasattr(result, "velocity_decay_ratio")

    @pytest.mark.asyncio
    async def test_zero_baseline_velocity(self):
        """基准流速为 0 时的处理"""
        monitor, _, tv, _ = _make_monitor(survival_seconds=3.0)
        base_ms = 1_700_000_000_000.0

        monitor.on_tick(STOCK, _make_tick(100.0, base_ms))
        monitor.start_monitoring(STOCK, 100.0, 0.0)

        monitor.on_tick(STOCK, _make_tick(100.02, base_ms + 3500))
        tv.get_window_count.return_value = 10

        result = await monitor.evaluate_survival(STOCK)
        # baseline=0 → velocity_ratio=0 → 假突破
        assert result is not None
        assert hasattr(result, "velocity_decay_ratio")
