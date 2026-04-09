#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeltaCalculator 单元测试

验证多空净动量计算器的核心逻辑：
- Lee-Ready 简化版算法方向分类
- Tick Test 回退判定
- 小成交量过滤
- 周期累加与 flush
- 历史记录管理
- 重置功能
- SocketManager 推送
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from simple_trade.services.scalping.calculators.delta_calculator import DeltaCalculator
from simple_trade.services.scalping.models import (
    DeltaUpdateData,
    TickData,
    TickDirection,
)
from simple_trade.websocket.events import SocketEvent


# ── 辅助函数 ──────────────────────────────────────────────

def make_tick(
    price: float = 10.0,
    volume: int = 200,
    ask_price: float = 10.0,
    bid_price: float = 9.9,
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


def make_calculator(min_volume: int = 100, period_seconds: int = 10):
    """创建带 mock socket_manager 的 DeltaCalculator"""
    mock_sm = MagicMock()
    mock_sm.emit_to_all = AsyncMock()
    calc = DeltaCalculator(
        socket_manager=mock_sm,
        min_volume=min_volume,
        period_seconds=period_seconds,
    )
    return calc, mock_sm


# ── Lee-Ready 方向分类测试 ────────────────────────────────

class TestDirectionClassification:
    """Lee-Ready 简化版算法方向分类"""

    def test_price_at_ask_is_buy(self):
        calc, _ = make_calculator()
        tick = make_tick(price=10.0, ask_price=10.0, bid_price=9.9)
        calc.on_tick("HK.00700", tick)
        state = calc._get_state("HK.00700")
        assert state.current_period.delta == 200  # 正值 = 买入

    def test_price_at_bid_is_sell(self):
        calc, _ = make_calculator()
        tick = make_tick(price=9.9, ask_price=10.0, bid_price=9.9)
        calc.on_tick("HK.00700", tick)
        state = calc._get_state("HK.00700")
        assert state.current_period.delta == -200  # 负值 = 卖出

    def test_price_closer_to_ask_is_buy(self):
        calc, _ = make_calculator()
        # ask=10.0, bid=9.0, mid=9.5, price=9.8 更接近 ask
        tick = make_tick(price=9.8, ask_price=10.0, bid_price=9.0)
        calc.on_tick("HK.00700", tick)
        state = calc._get_state("HK.00700")
        assert state.current_period.delta == 200

    def test_price_closer_to_bid_is_sell(self):
        calc, _ = make_calculator()
        # ask=10.0, bid=9.0, mid=9.5, price=9.2 更接近 bid
        tick = make_tick(price=9.2, ask_price=10.0, bid_price=9.0)
        calc.on_tick("HK.00700", tick)
        state = calc._get_state("HK.00700")
        assert state.current_period.delta == -200

    def test_price_at_midpoint_no_history_is_neutral(self):
        """正好在中间且无 last_direction → NEUTRAL，不计入 delta"""
        calc, _ = make_calculator()
        # ask=10.0, bid=9.0, mid=9.5
        tick = make_tick(price=9.5, volume=200, ask_price=10.0, bid_price=9.0)
        calc.on_tick("HK.00700", tick)
        state = calc._get_state("HK.00700")
        assert state.current_period.delta == 0.0
        assert state.current_period.volume == 0  # NEUTRAL 不计入 volume

    def test_price_at_midpoint_with_last_buy_follows_buy(self):
        """正好在中间，last_direction=BUY → 跟随买入"""
        calc, _ = make_calculator()
        # 先建立 last_direction = BUY
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=100, ask_price=10.0, bid_price=9.0))
        # 再发一笔正好在中间的
        calc.on_tick("HK.00700", make_tick(price=9.5, volume=300, ask_price=10.0, bid_price=9.0))
        state = calc._get_state("HK.00700")
        # 100 (第一笔买入) + 300 (第二笔跟随买入) = 400
        assert state.current_period.delta == 400

    def test_price_at_midpoint_with_last_sell_follows_sell(self):
        """正好在中间，last_direction=SELL → 跟随卖出"""
        calc, _ = make_calculator()
        # 先建立 last_direction = SELL
        calc.on_tick("HK.00700", make_tick(price=9.0, volume=100, ask_price=10.0, bid_price=9.0))
        # 再发一笔正好在中间的
        calc.on_tick("HK.00700", make_tick(price=9.5, volume=300, ask_price=10.0, bid_price=9.0))
        state = calc._get_state("HK.00700")
        # -100 (第一笔卖出) + -300 (第二笔跟随卖出) = -400
        assert state.current_period.delta == -400


# ── 成交量过滤测试 ────────────────────────────────────────

class TestVolumeFilter:
    """成交量 < min_volume 的 Tick 过滤"""

    def test_volume_below_threshold_ignored(self):
        calc, _ = make_calculator(min_volume=100)
        tick = make_tick(price=10.0, volume=99)
        calc.on_tick("HK.00700", tick)
        state = calc._get_state("HK.00700")
        assert state.current_period.delta == 0.0
        assert state.current_period.tick_count == 0

    def test_volume_at_threshold_accepted(self):
        calc, _ = make_calculator(min_volume=100)
        tick = make_tick(price=10.0, volume=100)
        calc.on_tick("HK.00700", tick)
        state = calc._get_state("HK.00700")
        assert state.current_period.delta == 100
        assert state.current_period.tick_count == 1


# ── 周期累加与 flush 测试 ─────────────────────────────────

class TestFlushPeriod:
    """周期累加与 flush"""

    @pytest.mark.asyncio
    async def test_flush_returns_delta_update(self):
        calc, mock_sm = make_calculator(period_seconds=10)
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        calc.on_tick("HK.00700", make_tick(price=9.9, volume=100, bid_price=9.9))

        result = await calc.flush_period("HK.00700")
        assert result is not None
        assert result.stock_code == "HK.00700"
        assert result.delta == 100  # 200 - 100
        assert result.volume == 300
        assert result.period_seconds == 10

    @pytest.mark.asyncio
    async def test_flush_empty_period_returns_none(self):
        calc, _ = make_calculator()
        result = await calc.flush_period("HK.00700")
        assert result is None

    @pytest.mark.asyncio
    async def test_flush_resets_accumulator(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        await calc.flush_period("HK.00700")

        state = calc._get_state("HK.00700")
        assert state.current_period.delta == 0.0
        assert state.current_period.volume == 0
        assert state.current_period.tick_count == 0

    @pytest.mark.asyncio
    async def test_flush_pushes_via_socket_manager(self):
        calc, mock_sm = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        await calc.flush_period("HK.00700")

        mock_sm.emit_to_all.assert_called_once()
        call_args = mock_sm.emit_to_all.call_args
        assert call_args[0][0] == SocketEvent.DELTA_UPDATE

    @pytest.mark.asyncio
    async def test_flush_saves_to_history(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        await calc.flush_period("HK.00700")

        history = calc.get_recent_deltas("HK.00700")
        assert len(history) == 1
        assert history[0].delta == 200


# ── 历史记录与 get_recent_deltas 测试 ─────────────────────

class TestRecentDeltas:

    @pytest.mark.asyncio
    async def test_get_recent_deltas_respects_count(self):
        calc, _ = make_calculator()
        for i in range(5):
            calc.on_tick("HK.00700", make_tick(price=10.0, volume=100))
            await calc.flush_period("HK.00700")

        result = calc.get_recent_deltas("HK.00700", count=3)
        assert len(result) == 3

    def test_get_recent_deltas_empty(self):
        calc, _ = make_calculator()
        result = calc.get_recent_deltas("HK.00700")
        assert result == []


# ── 重置测试 ──────────────────────────────────────────────

class TestReset:

    def test_reset_clears_state(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        calc.reset("HK.00700")

        state = calc._get_state("HK.00700")
        assert state.current_period.delta == 0.0
        assert state.current_period.tick_count == 0

    def test_reset_clears_last_direction(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        assert "HK.00700" in calc._last_direction

        calc.reset("HK.00700")
        assert "HK.00700" not in calc._last_direction

    def test_reset_nonexistent_stock_no_error(self):
        calc, _ = make_calculator()
        calc.reset("NONEXISTENT")  # 不应抛异常


# ── last_direction 状态维护测试 ────────────────────────────

class TestLastDirection:

    def test_last_direction_updated_on_buy(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, ask_price=10.0, bid_price=9.0))
        assert calc._last_direction["HK.00700"] == TickDirection.BUY

    def test_last_direction_updated_on_sell(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=9.0, ask_price=10.0, bid_price=9.0))
        assert calc._last_direction["HK.00700"] == TickDirection.SELL

    def test_neutral_does_not_overwrite_last_direction(self):
        """NEUTRAL 不应覆盖 last_direction"""
        calc, _ = make_calculator()
        # 先建立 BUY
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=100, ask_price=10.0, bid_price=9.0))
        assert calc._last_direction["HK.00700"] == TickDirection.BUY

        # 发一笔 NEUTRAL（中间且无法判定 → 但因为有 last_direction 所以会跟随 BUY）
        # 这里不会产生 NEUTRAL，因为有 last_direction
        # 要测试 NEUTRAL 不覆盖，需要第一笔就是中间且无 last_direction
        calc2, _ = make_calculator()
        calc2.on_tick("HK.00700", make_tick(price=9.5, volume=100, ask_price=10.0, bid_price=9.0))
        # 无 last_direction → NEUTRAL，不应写入 last_direction
        assert "HK.00700" not in calc2._last_direction

    def test_different_stocks_have_independent_last_direction(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, ask_price=10.0, bid_price=9.0, stock_code="HK.00700"))
        calc.on_tick("US.AAPL", make_tick(price=9.0, ask_price=10.0, bid_price=9.0, stock_code="US.AAPL"))

        assert calc._last_direction["HK.00700"] == TickDirection.BUY
        assert calc._last_direction["US.AAPL"] == TickDirection.SELL
