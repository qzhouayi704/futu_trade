#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POCCalculator 属性测试

使用 hypothesis 验证 Price_Bin 累加不变量和 POC 计算正确性。

Feature: intraday-scalping-engine, Property 8: Price_Bin 累加不变量
Feature: intraday-scalping-engine, Property 9: POC 计算正确性
**Validates: Requirements 5.1, 5.2, 5.3, 5.4**
"""

import asyncio
import os
import sys
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume, strategies as st

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ),
)

from simple_trade.services.scalping.calculators.poc_calculator import (
    POCCalculator,
    _HK_TICK_SIZES,
)
from simple_trade.services.scalping.models import TickData, TickDirection


# ── hypothesis 策略 ──────────────────────────────────────────────

# 价格策略：使用整数分避免浮点精度问题，再转为浮点
price_cents_st = st.integers(min_value=1, max_value=1000000)

# 成交量策略
volume_st = st.integers(min_value=1, max_value=10**6)

# 股票代码
stock_code_st = st.just("HK.00700")

# 单笔 Tick 参数策略
tick_param_st = st.fixed_dictionaries({
    "price_cents": price_cents_st,
    "volume": volume_st,
})

# Tick 序列策略
tick_list_st = st.lists(tick_param_st, min_size=1, max_size=50)


# ── 辅助函数 ──────────────────────────────────────────────────────

def make_calculator() -> POCCalculator:
    """创建带 mock socket_manager 的 POCCalculator"""
    mock_sm = MagicMock()
    mock_sm.emit_to_all = AsyncMock()
    return POCCalculator(socket_manager=mock_sm)


def make_tick(price: float, volume: int, stock_code: str = "HK.00700") -> TickData:
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


def cents_to_price(cents: int) -> float:
    """整数分转浮点价格"""
    return cents / 100.0


def normalize_price_hk(price: float) -> str:
    """复制 POCCalculator 的港股价格归一化逻辑，用于测试期望值计算"""
    tick_size = 5.0
    for upper, ts in _HK_TICK_SIZES:
        if price < upper:
            tick_size = ts
            break
    bin_size = tick_size * 2
    normalized = round(price / bin_size) * bin_size
    return f"{normalized:.4f}"


# ── Property 8: Price_Bin 累加不变量 ─────────────────────────────
# Feature: intraday-scalping-engine, Property 8: Price_Bin 累加不变量
# **Validates: Requirements 5.1, 5.2**


class TestProperty8PriceBinAccumulationInvariant:
    """Property 8: 对于任意 Tick 序列，POCCalculator 中每个价位的
    累计成交量应等于该价位所有 Tick 成交量之和（按归一化后的 Bin 分组）。"""

    @given(ticks_params=tick_list_st)
    @settings(max_examples=200)
    def test_each_bin_volume_equals_sum_of_ticks(self, ticks_params: list[dict]):
        """每个 Price_Bin 的累计成交量应等于所有落入该 Bin 的 Tick 成交量之和"""
        calc = make_calculator()
        stock_code = "HK.00700"

        # 按归一化后的价格分组计算期望
        expected_bins: dict[float, int] = defaultdict(int)

        for params in ticks_params:
            price = cents_to_price(params["price_cents"])
            volume = params["volume"]
            tick = make_tick(price=price, volume=volume, stock_code=stock_code)
            calc.on_tick(stock_code, tick)
            # 使用归一化后的价格作为 key
            norm_price = float(normalize_price_hk(price))
            expected_bins[norm_price] += volume

        actual_profile = calc.get_volume_profile(stock_code)

        assert len(actual_profile) == len(expected_bins), (
            f"价位数量不一致: 期望 {len(expected_bins)}，实际 {len(actual_profile)}"
        )
        for price, expected_vol in expected_bins.items():
            assert price in actual_profile, f"价位 {price} 缺失"
            assert actual_profile[price] == expected_vol, (
                f"价位 {price} 成交量不一致: 期望 {expected_vol}，实际 {actual_profile[price]}"
            )

    @given(ticks_params=tick_list_st)
    @settings(max_examples=200)
    def test_total_volume_equals_sum_of_all_ticks(self, ticks_params: list[dict]):
        """所有 Price_Bin 的成交量总和应等于所有 Tick 成交量之和"""
        calc = make_calculator()
        stock_code = "HK.00700"

        total_expected = 0
        for params in ticks_params:
            price = cents_to_price(params["price_cents"])
            volume = params["volume"]
            tick = make_tick(price=price, volume=volume, stock_code=stock_code)
            calc.on_tick(stock_code, tick)
            total_expected += volume

        actual_profile = calc.get_volume_profile(stock_code)
        total_actual = sum(actual_profile.values())

        assert total_actual == total_expected, (
            f"总成交量不一致: 期望 {total_expected}，实际 {total_actual}"
        )

    @given(
        ticks_params_1=tick_list_st,
        ticks_params_2=tick_list_st,
    )
    @settings(max_examples=200)
    def test_reset_clears_bins_then_reaccumulates(
        self, ticks_params_1: list[dict], ticks_params_2: list[dict]
    ):
        """每日开盘重置后，Price_Bin 应从零开始重新累加"""
        calc = make_calculator()
        stock_code = "HK.00700"

        # 第一批 Tick
        for params in ticks_params_1:
            price = cents_to_price(params["price_cents"])
            tick = make_tick(price=price, volume=params["volume"], stock_code=stock_code)
            calc.on_tick(stock_code, tick)

        # 重置
        calc.reset(stock_code)
        assert calc.get_volume_profile(stock_code) == {}, "重置后 volume_profile 应为空"

        # 第二批 Tick，按归一化价格分组
        expected_bins: dict[float, int] = defaultdict(int)
        for params in ticks_params_2:
            price = cents_to_price(params["price_cents"])
            tick = make_tick(price=price, volume=params["volume"], stock_code=stock_code)
            calc.on_tick(stock_code, tick)
            norm_price = float(normalize_price_hk(price))
            expected_bins[norm_price] += params["volume"]

        actual_profile = calc.get_volume_profile(stock_code)
        for price, expected_vol in expected_bins.items():
            assert actual_profile.get(price, 0) == expected_vol, (
                f"重置后价位 {price} 成交量不一致: 期望 {expected_vol}，"
                f"实际 {actual_profile.get(price, 0)}"
            )


# ── Property 9: POC 计算正确性 ───────────────────────────────────
# Feature: intraday-scalping-engine, Property 9: POC 计算正确性
# **Validates: Requirements 5.3, 5.4**


class TestProperty9PocCalculationCorrectness:
    """Property 9: 对于任意非空的 Price_Bin 哈希表，计算得到的 POC 价格
    应等于成交量最大的 Price_Bin 对应的价格。若存在多个相同最大成交量的价位，
    POC 应为其中之一。"""

    @given(ticks_params=tick_list_st)
    @settings(max_examples=200)
    def test_poc_is_max_volume_bin(self, ticks_params: list[dict]):
        """POC 应为成交量最大的 Price_Bin 对应的价格"""
        calc = make_calculator()
        stock_code = "HK.00700"

        # 按归一化价格分组
        expected_bins: dict[float, int] = defaultdict(int)
        for params in ticks_params:
            price = cents_to_price(params["price_cents"])
            tick = make_tick(price=price, volume=params["volume"], stock_code=stock_code)
            calc.on_tick(stock_code, tick)
            norm_price = float(normalize_price_hk(price))
            expected_bins[norm_price] += params["volume"]

        result = asyncio.get_event_loop().run_until_complete(
            calc.calculate_poc(stock_code)
        )

        assert result is not None, "非空 Price_Bin 时 calculate_poc 不应返回 None"

        max_volume = max(expected_bins.values())
        max_prices = {p for p, v in expected_bins.items() if v == max_volume}

        assert result.poc_price in max_prices, (
            f"POC 价格 {result.poc_price} 不在最大成交量价位集合 {max_prices} 中"
        )
        assert result.poc_volume == max_volume, (
            f"POC 成交量不一致: 期望 {max_volume}，实际 {result.poc_volume}"
        )

    @given(ticks_params=tick_list_st)
    @settings(max_examples=200)
    def test_poc_change_triggers_push(self, ticks_params: list[dict]):
        """POC 变化时应通过 SocketManager 推送 POC_UPDATE 事件"""
        from simple_trade.websocket.events import SocketEvent

        mock_sm = MagicMock()
        mock_sm.emit_to_all = AsyncMock()
        calc = POCCalculator(socket_manager=mock_sm)
        stock_code = "HK.00700"

        for params in ticks_params:
            price = cents_to_price(params["price_cents"])
            tick = make_tick(price=price, volume=params["volume"], stock_code=stock_code)
            calc.on_tick(stock_code, tick)

        result = asyncio.get_event_loop().run_until_complete(
            calc.calculate_poc(stock_code)
        )

        # 首次计算 POC 一定会变化（last_poc_price 为 None）
        assert result is not None
        mock_sm.emit_to_all.assert_called_once()
        call_args = mock_sm.emit_to_all.call_args
        assert call_args[0][0] == SocketEvent.POC_UPDATE

    @given(
        price_cents=price_cents_st,
        volumes=st.lists(volume_st, min_size=2, max_size=20),
    )
    @settings(max_examples=200)
    def test_unchanged_poc_does_not_push_again(
        self, price_cents: int, volumes: list[int]
    ):
        """POC 未变化时不应重复推送"""
        mock_sm = MagicMock()
        mock_sm.emit_to_all = AsyncMock()
        calc = POCCalculator(socket_manager=mock_sm)
        stock_code = "HK.00700"
        price = cents_to_price(price_cents)

        # 所有 Tick 同一价位 → POC 始终不变
        for vol in volumes:
            tick = make_tick(price=price, volume=vol, stock_code=stock_code)
            calc.on_tick(stock_code, tick)

        # 第一次计算
        asyncio.get_event_loop().run_until_complete(calc.calculate_poc(stock_code))
        assert mock_sm.emit_to_all.call_count == 1

        # 再加同价位成交量，POC 不变
        tick = make_tick(price=price, volume=100, stock_code=stock_code)
        calc.on_tick(stock_code, tick)
        result = asyncio.get_event_loop().run_until_complete(
            calc.calculate_poc(stock_code)
        )

        # POC 未变化，不应再次推送
        assert result is None
        assert mock_sm.emit_to_all.call_count == 1

    @given(
        ticks_params=st.lists(tick_param_st, min_size=2, max_size=30),
    )
    @settings(max_examples=200)
    def test_volume_profile_in_poc_result_matches_bins(self, ticks_params: list[dict]):
        """POC 结果中的 volume_profile 应与实际 Price_Bin 一致"""
        calc = make_calculator()
        stock_code = "HK.00700"

        # volume_profile 的 key 是归一化后的 4 位小数字符串
        expected_bins: dict[str, int] = defaultdict(int)
        for params in ticks_params:
            price = cents_to_price(params["price_cents"])
            tick = make_tick(price=price, volume=params["volume"], stock_code=stock_code)
            calc.on_tick(stock_code, tick)
            norm_key = normalize_price_hk(price)
            expected_bins[norm_key] += params["volume"]

        result = asyncio.get_event_loop().run_until_complete(
            calc.calculate_poc(stock_code)
        )

        assert result is not None
        assert dict(result.volume_profile) == dict(expected_bins), (
            f"volume_profile 不一致:\n期望: {dict(expected_bins)}\n实际: {dict(result.volume_profile)}"
        )
