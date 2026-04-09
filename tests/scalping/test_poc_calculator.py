#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POCCalculator 单元测试

验证日内控制点计算器的核心逻辑：
- Price_Bin 成交量累加
- POC 计算（成交量最大价位）
- 多个相同最大成交量时的处理
- POC 变化时推送、未变化时不推送
- volume_profile 获取
- 每日开盘重置
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

from simple_trade.services.scalping.calculators.poc_calculator import POCCalculator
from simple_trade.services.scalping.models import (
    PocUpdateData,
    TickData,
    TickDirection,
)
from simple_trade.websocket.events import SocketEvent


# ── 辅助函数 ──────────────────────────────────────────────


def make_tick(
    price: float = 10.0,
    volume: int = 200,
    stock_code: str = "HK.00700",
) -> TickData:
    """创建测试用 TickData"""
    return TickData(
        stock_code=stock_code,
        price=price,
        volume=volume,
        direction=TickDirection.NEUTRAL,
        timestamp=1700000000000.0,
        ask_price=price + 0.1,
        bid_price=price - 0.1,
    )


def make_calculator(update_interval: float = 5.0):
    """创建带 mock socket_manager 的 POCCalculator"""
    mock_sm = MagicMock()
    mock_sm.emit_to_all = AsyncMock()
    calc = POCCalculator(
        socket_manager=mock_sm,
        update_interval=update_interval,
    )
    return calc, mock_sm


# ── Price_Bin 累加测试 ────────────────────────────────────


class TestPriceBinAccumulation:
    """Price_Bin 成交量累加"""

    def test_single_tick_creates_bin(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        profile = calc.get_volume_profile("HK.00700")
        assert profile == {10.0: 200}

    def test_same_price_accumulates(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=300))
        profile = calc.get_volume_profile("HK.00700")
        assert profile == {10.0: 500}

    def test_different_prices_separate_bins(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        calc.on_tick("HK.00700", make_tick(price=10.5, volume=300))
        profile = calc.get_volume_profile("HK.00700")
        # 10.5 经港股 Tick Size 归一化后变为 10.48（tick=0.02, bin=0.04）
        assert profile == {10.0: 200, 10.48: 300}

    def test_multiple_stocks_independent(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200, stock_code="HK.00700"))
        calc.on_tick("US.AAPL", make_tick(price=150.0, volume=100, stock_code="US.AAPL"))
        assert calc.get_volume_profile("HK.00700") == {10.0: 200}
        assert calc.get_volume_profile("US.AAPL") == {150.0: 100}

    def test_empty_profile_for_unknown_stock(self):
        calc, _ = make_calculator()
        profile = calc.get_volume_profile("NONEXISTENT")
        assert profile == {}


# ── POC 计算测试 ──────────────────────────────────────────


class TestCalculatePoc:
    """POC 计算正确性"""

    @pytest.mark.asyncio
    async def test_single_price_is_poc(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=500))
        result = await calc.calculate_poc("HK.00700")
        assert result is not None
        assert result.poc_price == 10.0
        assert result.poc_volume == 500

    @pytest.mark.asyncio
    async def test_highest_volume_is_poc(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        calc.on_tick("HK.00700", make_tick(price=10.5, volume=800))
        calc.on_tick("HK.00700", make_tick(price=11.0, volume=300))
        result = await calc.calculate_poc("HK.00700")
        assert result is not None
        # 10.5 归一化为 10.48
        assert result.poc_price == 10.48
        assert result.poc_volume == 800

    @pytest.mark.asyncio
    async def test_accumulated_volume_determines_poc(self):
        """多笔同价位累加后成为 POC"""
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        calc.on_tick("HK.00700", make_tick(price=10.5, volume=300))
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=400))
        # 10.0: 600, 10.5: 300
        result = await calc.calculate_poc("HK.00700")
        assert result is not None
        assert result.poc_price == 10.0
        assert result.poc_volume == 600

    @pytest.mark.asyncio
    async def test_equal_max_volume_poc_is_one_of_them(self):
        """多个价位成交量相同时，POC 应为其中之一"""
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=500))
        calc.on_tick("HK.00700", make_tick(price=10.5, volume=500))
        result = await calc.calculate_poc("HK.00700")
        assert result is not None
        assert result.poc_price in (10.0, 10.48)
        assert result.poc_volume == 500

    @pytest.mark.asyncio
    async def test_empty_bins_returns_none(self):
        calc, _ = make_calculator()
        result = await calc.calculate_poc("HK.00700")
        assert result is None

    @pytest.mark.asyncio
    async def test_volume_profile_in_result(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        calc.on_tick("HK.00700", make_tick(price=10.5, volume=300))
        result = await calc.calculate_poc("HK.00700")
        assert result is not None
        # volume_profile key 是归一化后的价格字符串
        assert result.volume_profile == {"10.0000": 200, "10.4800": 300}


# ── POC 变化推送测试 ──────────────────────────────────────


class TestPocPush:
    """POC 变化时推送、未变化时不推送"""

    @pytest.mark.asyncio
    async def test_first_poc_pushes(self):
        calc, mock_sm = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        result = await calc.calculate_poc("HK.00700")
        assert result is not None
        mock_sm.emit_to_all.assert_called_once()
        call_args = mock_sm.emit_to_all.call_args
        assert call_args[0][0] == SocketEvent.POC_UPDATE

    @pytest.mark.asyncio
    async def test_unchanged_poc_does_not_push(self):
        calc, mock_sm = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        await calc.calculate_poc("HK.00700")
        mock_sm.emit_to_all.reset_mock()

        # 再加同价位成交量，POC 仍是 10.0
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=100))
        result = await calc.calculate_poc("HK.00700")
        assert result is None
        mock_sm.emit_to_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_changed_poc_pushes_again(self):
        calc, mock_sm = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        await calc.calculate_poc("HK.00700")
        mock_sm.emit_to_all.reset_mock()

        # 新价位成交量超过旧 POC → POC 变化
        calc.on_tick("HK.00700", make_tick(price=10.5, volume=500))
        result = await calc.calculate_poc("HK.00700")
        assert result is not None
        assert result.poc_price == 10.48
        mock_sm.emit_to_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_socket_error_does_not_raise(self):
        """SocketManager 推送失败不应抛异常"""
        calc, mock_sm = make_calculator()
        mock_sm.emit_to_all = AsyncMock(side_effect=Exception("连接断开"))
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        result = await calc.calculate_poc("HK.00700")
        # 即使推送失败，仍返回结果
        assert result is not None


# ── 重置测试 ──────────────────────────────────────────────


class TestReset:
    """每日开盘重置"""

    def test_reset_clears_bins(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        calc.reset("HK.00700")
        assert calc.get_volume_profile("HK.00700") == {}

    @pytest.mark.asyncio
    async def test_reset_clears_last_poc(self):
        """重置后 POC 应重新推送"""
        calc, mock_sm = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        await calc.calculate_poc("HK.00700")
        mock_sm.emit_to_all.reset_mock()

        calc.reset("HK.00700")
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200))
        result = await calc.calculate_poc("HK.00700")
        # 重置后同价位也应推送（因为 last_poc_price 已清除）
        assert result is not None
        mock_sm.emit_to_all.assert_called_once()

    def test_reset_nonexistent_stock_no_error(self):
        calc, _ = make_calculator()
        calc.reset("NONEXISTENT")  # 不应抛异常

    def test_reset_only_affects_target_stock(self):
        calc, _ = make_calculator()
        calc.on_tick("HK.00700", make_tick(price=10.0, volume=200, stock_code="HK.00700"))
        calc.on_tick("US.AAPL", make_tick(price=150.0, volume=100, stock_code="US.AAPL"))
        calc.reset("HK.00700")
        assert calc.get_volume_profile("HK.00700") == {}
        assert calc.get_volume_profile("US.AAPL") == {150.0: 100}
