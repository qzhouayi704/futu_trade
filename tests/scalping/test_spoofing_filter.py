#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SpoofingFilter 单元测试

验证防撤单陷阱过滤器的核心逻辑：
- 巨单检测（挂单量超过历史均值 × 倍数）
- 巨单生命周期（存活时间区间判定）
- 事件推送（CREATE / REMOVE / BREAK）
- 活跃阻力/支撑线管理
- 重置功能
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from simple_trade.services.scalping.detectors.spoofing_filter import SpoofingFilter
from simple_trade.services.scalping.models import (
    OrderBookData,
    OrderBookLevel,
    PriceLevelAction,
    PriceLevelSide,
)
from simple_trade.websocket.events import SocketEvent


# ── 辅助函数 ──────────────────────────────────────────────

STOCK = "HK.00700"
TICK_SIZE = 0.01


def make_level(price: float, volume: int, order_count: int = 1) -> OrderBookLevel:
    return OrderBookLevel(price=price, volume=volume, order_count=order_count)


def make_order_book(
    stock_code: str = STOCK,
    ask_levels: list[OrderBookLevel] | None = None,
    bid_levels: list[OrderBookLevel] | None = None,
    timestamp_s: float = 1000.0,
) -> OrderBookData:
    """创建测试用 OrderBookData，timestamp_s 为秒，内部转毫秒"""
    if ask_levels is None:
        ask_levels = [make_level(10.05, 100), make_level(10.06, 100)]
    if bid_levels is None:
        bid_levels = [make_level(10.04, 100), make_level(10.03, 100)]
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
):
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


# ── 辅助：构建历史基线 ──────────────────────────────────────

async def _build_baseline(sf, stock_code: str, ask_vol: int, bid_vol: int, count: int = 10):
    """发送多次正常挂单量的 OrderBook 来建立历史均值基线"""
    for i in range(count):
        ob = make_order_book(
            stock_code=stock_code,
            ask_levels=[make_level(10.05, ask_vol), make_level(10.06, ask_vol)],
            bid_levels=[make_level(10.04, bid_vol), make_level(10.03, bid_vol)],
            timestamp_s=100.0 + i,
        )
        await sf.on_order_book(stock_code, ob)


# ── 巨单检测 ──────────────────────────────────────────────

class TestLargeOrderDetection:
    """巨单检测阈值测试"""

    @pytest.mark.asyncio
    async def test_volume_below_threshold_not_tracked(self):
        """挂单量未达阈值时不应被跟踪"""
        sf, mock_sm = make_filter()
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=10)
        # 发送一个挂单量 = 400（< 100 * 5 = 500）的快照
        ob = make_order_book(
            ask_levels=[make_level(10.05, 400), make_level(10.06, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(STOCK, ob)
        assert sf._tracked.get(STOCK, {}).get(10.05) is None

    @pytest.mark.asyncio
    async def test_volume_at_threshold_tracked(self):
        """挂单量恰好达到阈值时应被跟踪"""
        sf, mock_sm = make_filter()
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=10)
        # 发送一个挂单量 = 500（= 100 * 5）的快照
        ob = make_order_book(
            ask_levels=[make_level(10.05, 500), make_level(10.06, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(STOCK, ob)
        tracked = sf._tracked.get(STOCK, {}).get(10.05)
        assert tracked is not None
        assert tracked.initial_volume == 500

    @pytest.mark.asyncio
    async def test_volume_above_threshold_tracked(self):
        """挂单量超过阈值时应被跟踪"""
        sf, mock_sm = make_filter()
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=10)
        ob = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(STOCK, ob)
        tracked = sf._tracked.get(STOCK, {}).get(10.05)
        assert tracked is not None
        assert tracked.side == PriceLevelSide.RESISTANCE

    @pytest.mark.asyncio
    async def test_bid_side_large_order_is_support(self):
        """Bid 侧巨单应标记为支撑"""
        sf, mock_sm = make_filter()
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=10)
        ob = make_order_book(
            bid_levels=[make_level(10.04, 1000), make_level(10.03, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(STOCK, ob)
        tracked = sf._tracked.get(STOCK, {}).get(10.04)
        assert tracked is not None
        assert tracked.side == PriceLevelSide.SUPPORT

    @pytest.mark.asyncio
    async def test_custom_volume_multiplier(self):
        """自定义 volume_multiplier 参数验证"""
        sf, mock_sm = make_filter(volume_multiplier=10.0)
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=10)
        # 500 < 100 * 10 = 1000，不应被跟踪
        ob = make_order_book(
            ask_levels=[make_level(10.05, 500), make_level(10.06, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(STOCK, ob)
        assert sf._tracked.get(STOCK, {}).get(10.05) is None


# ── 巨单生命周期 ──────────────────────────────────────────

class TestLargeOrderLifecycle:
    """巨单生命周期状态转换测试"""

    @pytest.mark.asyncio
    async def test_silent_removal_before_min_survive(self):
        """存活未达 survive_seconds_min 时被撤销 → 静默移除，不生成事件"""
        sf, mock_sm = make_filter()
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=10)
        # t=120: 巨单出现
        ob1 = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(STOCK, ob1)
        mock_sm.emit_to_all.reset_mock()
        # t=121: 巨单消失（存活 1s < 3s）
        ob2 = make_order_book(
            ask_levels=[make_level(10.05, 50), make_level(10.06, 100)],
            timestamp_s=121.0,
        )
        await sf.on_order_book(STOCK, ob2)
        # 不应推送任何事件
        mock_sm.emit_to_all.assert_not_called()
        # 跟踪记录应被移除
        assert 10.05 not in sf._tracked.get(STOCK, {})

    @pytest.mark.asyncio
    async def test_create_event_after_max_survive(self):
        """存活超过 survive_seconds_max → 推送 PRICE_LEVEL_CREATE 事件"""
        sf, mock_sm = make_filter()
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=10)
        # t=120: 巨单出现
        ob1 = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(STOCK, ob1)
        mock_sm.emit_to_all.reset_mock()
        # t=126: 巨单仍在（存活 6s > 5s）
        ob2 = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            timestamp_s=126.0,
        )
        await sf.on_order_book(STOCK, ob2)
        # 应推送 CREATE 事件
        mock_sm.emit_to_all.assert_called_once()
        call_args = mock_sm.emit_to_all.call_args
        assert call_args[0][0] == SocketEvent.PRICE_LEVEL_CREATE
        data = call_args[0][1]
        assert data["price"] == 10.05
        assert data["action"] == "create"

    @pytest.mark.asyncio
    async def test_create_event_only_once(self):
        """CREATE 事件只推送一次"""
        sf, mock_sm = make_filter()
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=10)
        ob1 = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(STOCK, ob1)
        mock_sm.emit_to_all.reset_mock()
        # t=126: 第一次超过 max → CREATE
        ob2 = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            timestamp_s=126.0,
        )
        await sf.on_order_book(STOCK, ob2)
        assert mock_sm.emit_to_all.call_count == 1
        mock_sm.emit_to_all.reset_mock()
        # t=130: 仍然存活 → 不应再次推送
        ob3 = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            timestamp_s=130.0,
        )
        await sf.on_order_book(STOCK, ob3)
        mock_sm.emit_to_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_event_when_close_and_cancelled(self):
        """价格靠近时被撤销 → 推送 PRICE_LEVEL_REMOVE 事件"""
        sf, mock_sm = make_filter(proximity_ticks=5, tick_size=0.01)
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=10)
        # t=120: 巨单出现在 10.05（ask 侧）
        ob1 = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            bid_levels=[make_level(10.04, 100), make_level(10.03, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(STOCK, ob1)
        mock_sm.emit_to_all.reset_mock()
        # t=124: 巨单消失（存活 4s，在 min-max 区间内）
        # mid_price = (10.05 + 10.04) / 2 = 10.045
        # distance = |10.05 - 10.045| = 0.005 < 5 * 0.01 = 0.05 → 靠近
        ob2 = make_order_book(
            ask_levels=[make_level(10.05, 50), make_level(10.06, 100)],
            bid_levels=[make_level(10.04, 100), make_level(10.03, 100)],
            timestamp_s=124.0,
        )
        await sf.on_order_book(STOCK, ob2)
        mock_sm.emit_to_all.assert_called_once()
        call_args = mock_sm.emit_to_all.call_args
        assert call_args[0][0] == SocketEvent.PRICE_LEVEL_REMOVE

    @pytest.mark.asyncio
    async def test_break_event_when_consumed(self):
        """巨单被市场成交吃透 → 推送 PRICE_LEVEL_BREAK 事件"""
        sf, mock_sm = make_filter()
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=10)
        # t=120: 巨单出现
        ob1 = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            bid_levels=[make_level(10.04, 100), make_level(10.03, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(STOCK, ob1)
        # t=121: 挂单量逐步减少（模拟被吃）
        ob_mid = make_order_book(
            ask_levels=[make_level(10.05, 400), make_level(10.06, 100)],
            bid_levels=[make_level(10.04, 100), make_level(10.03, 100)],
            timestamp_s=121.0,
        )
        await sf.on_order_book(STOCK, ob_mid)
        mock_sm.emit_to_all.reset_mock()
        # t=124: 挂单量归零（存活 4s，在区间内，且 last_volume=400 < 1000*0.5=500）
        ob2 = make_order_book(
            ask_levels=[make_level(10.05, 0), make_level(10.06, 100)],
            bid_levels=[make_level(10.04, 100), make_level(10.03, 100)],
            timestamp_s=124.0,
        )
        await sf.on_order_book(STOCK, ob2)
        mock_sm.emit_to_all.assert_called_once()
        call_args = mock_sm.emit_to_all.call_args
        assert call_args[0][0] == SocketEvent.PRICE_LEVEL_BREAK


# ── 活跃阻力/支撑线管理 ──────────────────────────────────

class TestActiveLevels:
    """活跃阻力/支撑线管理测试"""

    @pytest.mark.asyncio
    async def test_get_active_levels_empty(self):
        sf, _ = make_filter()
        assert sf.get_active_levels(STOCK) == []

    @pytest.mark.asyncio
    async def test_get_active_levels_after_create(self):
        """CREATE 事件后应出现在活跃列表中"""
        sf, mock_sm = make_filter()
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=10)
        ob1 = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(STOCK, ob1)
        ob2 = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            timestamp_s=126.0,
        )
        await sf.on_order_book(STOCK, ob2)
        levels = sf.get_active_levels(STOCK)
        assert len(levels) == 1
        assert levels[0].price == 10.05
        assert levels[0].side == PriceLevelSide.RESISTANCE

    @pytest.mark.asyncio
    async def test_active_level_removed_after_break(self):
        """BREAK 事件后应从活跃列表中移除"""
        sf, mock_sm = make_filter()
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=10)
        # 创建并确认巨单
        ob1 = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(STOCK, ob1)
        ob2 = make_order_book(
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            timestamp_s=126.0,
        )
        await sf.on_order_book(STOCK, ob2)
        assert len(sf.get_active_levels(STOCK)) == 1
        # 模拟被吃透
        ob_mid = make_order_book(
            ask_levels=[make_level(10.05, 400), make_level(10.06, 100)],
            timestamp_s=127.0,
        )
        await sf.on_order_book(STOCK, ob_mid)
        ob3 = make_order_book(
            ask_levels=[make_level(10.05, 0), make_level(10.06, 100)],
            timestamp_s=128.0,
        )
        await sf.on_order_book(STOCK, ob3)
        assert len(sf.get_active_levels(STOCK)) == 0


# ── 重置功能 ──────────────────────────────────────────────

class TestReset:
    @pytest.mark.asyncio
    async def test_reset_clears_all_state(self):
        sf, _ = make_filter()
        await _build_baseline(sf, STOCK, ask_vol=100, bid_vol=100, count=5)
        sf.reset(STOCK)
        assert sf._histories.get(STOCK) is None
        assert sf._tracked.get(STOCK) is None
        assert sf._active_levels.get(STOCK) is None

    def test_reset_nonexistent_stock_no_error(self):
        sf, _ = make_filter()
        sf.reset("NONEXISTENT")  # 不应抛异常


# ── 边界条件 ──────────────────────────────────────────────

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_order_book(self):
        """空 OrderBook 不应崩溃"""
        sf, _ = make_filter()
        ob = OrderBookData(
            stock_code=STOCK, ask_levels=[], bid_levels=[], timestamp=1000000.0
        )
        await sf.on_order_book(STOCK, ob)  # 不应抛异常

    @pytest.mark.asyncio
    async def test_independent_stocks(self):
        """不同股票的跟踪状态应独立"""
        sf, _ = make_filter()
        stock_a = "HK.00700"
        stock_b = "US.AAPL"
        await _build_baseline(sf, stock_a, ask_vol=100, bid_vol=100, count=10)
        await _build_baseline(sf, stock_b, ask_vol=200, bid_vol=200, count=10)
        # stock_a 出现巨单
        ob = make_order_book(
            stock_code=stock_a,
            ask_levels=[make_level(10.05, 1000), make_level(10.06, 100)],
            timestamp_s=120.0,
        )
        await sf.on_order_book(stock_a, ob)
        assert 10.05 in sf._tracked.get(stock_a, {})
        assert sf._tracked.get(stock_b, {}).get(10.05) is None
