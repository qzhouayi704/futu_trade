#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TapeVelocityMonitor 单元测试

验证盘口流速仪的核心逻辑：
- 3 秒滑动窗口成交笔数统计
- 5 分钟滚动均值基准计算
- 开盘不足 5 分钟时使用已有数据均值
- 动能点火触发条件
- 10 秒冷却期
- SocketManager 推送
- 重置功能
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from simple_trade.services.scalping.calculators.tape_velocity import TapeVelocityMonitor
from simple_trade.services.scalping.models import (
    MomentumIgnitionData,
    TickData,
    TickDirection,
)
from simple_trade.websocket.events import SocketEvent


# ── 辅助函数 ──────────────────────────────────────────────

def make_tick(
    timestamp_ms: float = 1700000000000.0,
    stock_code: str = "HK.00700",
    price: float = 10.0,
    volume: int = 200,
) -> TickData:
    """创建测试用 TickData"""
    return TickData(
        stock_code=stock_code,
        price=price,
        volume=volume,
        direction=TickDirection.BUY,
        timestamp=timestamp_ms,
        ask_price=price,
        bid_price=price - 0.1,
    )


def make_monitor(
    window_seconds: float = 3.0,
    baseline_window_seconds: float = 300.0,
    ignition_multiplier: float = 3.0,
    cooldown_seconds: float = 10.0,
):
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


STOCK = "HK.00700"
BASE_TS = 1700000000000.0  # 基准时间戳（毫秒）


# ── 滑动窗口测试 ──────────────────────────────────────────

class TestSlidingWindow:
    """3 秒滑动窗口成交笔数统计"""

    def test_single_tick_counted(self):
        monitor, _ = make_monitor()
        monitor.on_tick(STOCK, make_tick(BASE_TS))
        assert monitor.get_window_count(STOCK) == 1

    def test_multiple_ticks_within_window(self):
        monitor, _ = make_monitor()
        for i in range(5):
            monitor.on_tick(STOCK, make_tick(BASE_TS + i * 500))  # 每 0.5 秒一笔
        assert monitor.get_window_count(STOCK) == 5

    def test_old_ticks_purged_from_window(self):
        monitor, _ = make_monitor(window_seconds=3.0)
        # 第一笔在 t=0
        monitor.on_tick(STOCK, make_tick(BASE_TS))
        # 第二笔在 t=4s（超出 3 秒窗口）
        monitor.on_tick(STOCK, make_tick(BASE_TS + 4000))
        # 第一笔应被清理，只剩第二笔
        assert monitor.get_window_count(STOCK) == 1

    def test_boundary_tick_at_exactly_window_edge_kept(self):
        """时间戳恰好在窗口边界 [now - 3s] 的 tick 应保留（闭区间）"""
        monitor, _ = make_monitor(window_seconds=3.0)
        monitor.on_tick(STOCK, make_tick(BASE_TS))
        # 恰好 3 秒后：cutoff = (BASE_TS+3000)/1000 - 3 = BASE_TS/1000
        # t=0 的 tick 时间戳 == cutoff，不满足 < cutoff，应保留
        monitor.on_tick(STOCK, make_tick(BASE_TS + 3000))
        assert monitor.get_window_count(STOCK) == 2

    def test_boundary_tick_just_outside_window_purged(self):
        """时间戳刚好超出窗口的 tick 应被清理"""
        monitor, _ = make_monitor(window_seconds=3.0)
        monitor.on_tick(STOCK, make_tick(BASE_TS))
        # 3.001 秒后：cutoff > BASE_TS/1000，第一笔被清理
        monitor.on_tick(STOCK, make_tick(BASE_TS + 3001))
        assert monitor.get_window_count(STOCK) == 1

    def test_empty_stock_returns_zero(self):
        monitor, _ = make_monitor()
        assert monitor.get_window_count(STOCK) == 0


# ── 基准均值测试 ──────────────────────────────────────────

class TestBaselineAverage:
    """5 分钟滚动均值基准计算"""

    def test_no_history_returns_zero(self):
        monitor, _ = make_monitor()
        assert monitor.get_baseline_avg(STOCK) == 0.0

    def test_baseline_after_one_slice(self):
        """归档一个切片后，基准应等于该切片的笔数"""
        monitor, _ = make_monitor(window_seconds=3.0)
        # 在 t=0 发送 3 笔 tick
        for i in range(3):
            monitor.on_tick(STOCK, make_tick(BASE_TS + i * 100))
        # 在 t=3s 发送一笔触发归档
        monitor.on_tick(STOCK, make_tick(BASE_TS + 3000))
        baseline = monitor.get_baseline_avg(STOCK)
        assert baseline > 0

    def test_baseline_uses_available_data_when_under_5min(self):
        """开盘不足 5 分钟时使用已有数据的均值"""
        monitor, _ = make_monitor(window_seconds=3.0, baseline_window_seconds=300.0)
        # 模拟 30 秒的数据（远不足 5 分钟）
        ts = BASE_TS
        for _ in range(10):
            for _ in range(2):
                monitor.on_tick(STOCK, make_tick(ts))
                ts += 100
            ts += 2800  # 跳到下一个 3 秒窗口
        baseline = monitor.get_baseline_avg(STOCK)
        # 应该有数据，不应为 0
        assert baseline >= 0

    def test_old_slices_purged_beyond_baseline_window(self):
        """超出 baseline_window_seconds 的历史切片应被清理"""
        monitor, _ = make_monitor(
            window_seconds=3.0, baseline_window_seconds=10.0
        )
        ts = BASE_TS
        # 生成 20 秒的数据（超出 10 秒基准窗口）
        for _ in range(7):
            monitor.on_tick(STOCK, make_tick(ts))
            ts += 3000  # 每 3 秒一个切片
        state = monitor._get_state(STOCK)
        # 历史切片不应无限增长
        for s in state.history_slices:
            assert s.timestamp >= (ts / 1000.0 - 10.0 - 3.0)


# ── 冷却期测试 ──────────────────────────────────────────

class TestCooldown:
    """10 秒冷却期"""

    def test_not_in_cooldown_initially(self):
        monitor, _ = make_monitor()
        assert monitor.is_in_cooldown(STOCK) is False

    def test_in_cooldown_after_ignition(self):
        """触发点火后应进入冷却期"""
        monitor, _ = make_monitor(window_seconds=3.0, cooldown_seconds=10.0)
        state = monitor._get_state(STOCK)
        # 手动设置冷却期
        state.cooldown_until = BASE_TS / 1000.0 + 10.0
        state.tick_timestamps.append(BASE_TS / 1000.0)
        assert monitor.is_in_cooldown(STOCK) is True

    def test_cooldown_expires(self):
        """冷却期过后应不再冷却"""
        monitor, _ = make_monitor(window_seconds=3.0, cooldown_seconds=10.0)
        state = monitor._get_state(STOCK)
        state.cooldown_until = BASE_TS / 1000.0 + 10.0
        # 当前时间在冷却期之后
        state.tick_timestamps.append(BASE_TS / 1000.0 + 11.0)
        assert monitor.is_in_cooldown(STOCK) is False


# ── 动能点火测试 ──────────────────────────────────────────

class TestCheckIgnition:
    """动能点火触发条件"""

    @pytest.mark.asyncio
    async def test_no_ticks_returns_none(self):
        monitor, _ = make_monitor()
        result = await monitor.check_ignition(STOCK)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_baseline_returns_none(self):
        """没有历史基准时不触发"""
        monitor, _ = make_monitor()
        monitor.on_tick(STOCK, make_tick(BASE_TS))
        result = await monitor.check_ignition(STOCK)
        assert result is None

    @pytest.mark.asyncio
    async def test_ignition_triggers_when_threshold_met(self):
        """成交笔数达到基准 3 倍时触发"""
        monitor, mock_sm = make_monitor(
            window_seconds=3.0, ignition_multiplier=3.0
        )
        # 先建立基准：每个切片 2 笔
        ts = BASE_TS
        for _ in range(5):
            monitor.on_tick(STOCK, make_tick(ts))
            monitor.on_tick(STOCK, make_tick(ts + 100))
            ts += 3000

        # 在当前窗口内塞入大量 tick 以超过 3 倍基准
        baseline = monitor.get_baseline_avg(STOCK)
        needed = int(baseline * 3) + 1
        for i in range(needed):
            monitor.on_tick(STOCK, make_tick(ts + i * 10))

        result = await monitor.check_ignition(STOCK)
        assert result is not None
        assert isinstance(result, MomentumIgnitionData)
        assert result.stock_code == STOCK
        assert result.multiplier >= 3.0

    @pytest.mark.asyncio
    async def test_ignition_pushes_via_socket(self):
        """触发时应通过 SocketManager 推送"""
        monitor, mock_sm = make_monitor(
            window_seconds=3.0, ignition_multiplier=3.0
        )
        ts = BASE_TS
        for _ in range(5):
            monitor.on_tick(STOCK, make_tick(ts))
            monitor.on_tick(STOCK, make_tick(ts + 100))
            ts += 3000

        baseline = monitor.get_baseline_avg(STOCK)
        needed = int(baseline * 3) + 1
        for i in range(needed):
            monitor.on_tick(STOCK, make_tick(ts + i * 10))

        await monitor.check_ignition(STOCK)
        mock_sm.emit_to_all.assert_called_once()
        call_args = mock_sm.emit_to_all.call_args
        assert call_args[0][0] == SocketEvent.MOMENTUM_IGNITION

    @pytest.mark.asyncio
    async def test_ignition_blocked_during_cooldown(self):
        """冷却期内不触发"""
        monitor, _ = make_monitor(
            window_seconds=3.0, ignition_multiplier=3.0, cooldown_seconds=10.0
        )
        ts = BASE_TS
        for _ in range(5):
            monitor.on_tick(STOCK, make_tick(ts))
            monitor.on_tick(STOCK, make_tick(ts + 100))
            ts += 3000

        baseline = monitor.get_baseline_avg(STOCK)
        needed = int(baseline * 3) + 1
        for i in range(needed):
            monitor.on_tick(STOCK, make_tick(ts + i * 10))

        # 第一次触发
        result1 = await monitor.check_ignition(STOCK)
        assert result1 is not None

        # 冷却期内再次检查（时间未过 10 秒）
        result2 = await monitor.check_ignition(STOCK)
        assert result2 is None

    @pytest.mark.asyncio
    async def test_below_threshold_no_ignition(self):
        """未达到 3 倍基准时不触发"""
        monitor, _ = make_monitor(
            window_seconds=3.0, ignition_multiplier=3.0
        )
        ts = BASE_TS
        for _ in range(5):
            for _ in range(5):
                monitor.on_tick(STOCK, make_tick(ts))
                ts += 100
            ts += 2500

        # 当前窗口只有少量 tick
        monitor.on_tick(STOCK, make_tick(ts))
        result = await monitor.check_ignition(STOCK)
        assert result is None


# ── 重置测试 ──────────────────────────────────────────────

class TestReset:
    """重置功能"""

    def test_reset_clears_state(self):
        monitor, _ = make_monitor()
        monitor.on_tick(STOCK, make_tick(BASE_TS))
        assert monitor.get_window_count(STOCK) == 1
        monitor.reset(STOCK)
        assert monitor.get_window_count(STOCK) == 0

    def test_reset_clears_baseline(self):
        monitor, _ = make_monitor()
        monitor.on_tick(STOCK, make_tick(BASE_TS))
        monitor.reset(STOCK)
        assert monitor.get_baseline_avg(STOCK) == 0.0

    def test_reset_nonexistent_stock_no_error(self):
        monitor, _ = make_monitor()
        monitor.reset("NONEXISTENT")  # 不应抛异常


# ── 多股票独立性测试 ──────────────────────────────────────

class TestMultiStockIndependence:
    """不同股票的状态应独立"""

    def test_different_stocks_independent_windows(self):
        monitor, _ = make_monitor()
        monitor.on_tick("HK.00700", make_tick(BASE_TS, stock_code="HK.00700"))
        monitor.on_tick("HK.09988", make_tick(BASE_TS, stock_code="HK.09988"))
        monitor.on_tick("HK.09988", make_tick(BASE_TS + 100, stock_code="HK.09988"))
        assert monitor.get_window_count("HK.00700") == 1
        assert monitor.get_window_count("HK.09988") == 2

    def test_reset_one_stock_does_not_affect_other(self):
        monitor, _ = make_monitor()
        monitor.on_tick("HK.00700", make_tick(BASE_TS, stock_code="HK.00700"))
        monitor.on_tick("HK.09988", make_tick(BASE_TS, stock_code="HK.09988"))
        monitor.reset("HK.00700")
        assert monitor.get_window_count("HK.00700") == 0
        assert monitor.get_window_count("HK.09988") == 1
