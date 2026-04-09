#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scalping 事件数据模型属性测试

使用 hypothesis 验证所有 Pydantic 数据模型的序列化往返一致性。

Feature: intraday-scalping-engine, Property 14: 事件数据模型序列化往返一致性
**Validates: Requirements 11.3**
"""

import os
import sys

import pytest
from hypothesis import given, settings, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from simple_trade.services.scalping.models import (
    DeltaUpdateData,
    MomentumIgnitionData,
    PriceLevelAction,
    PriceLevelData,
    PriceLevelSide,
    PocUpdateData,
    ScalpingSignalData,
    ScalpingSignalType,
)


# ── hypothesis 策略 ──────────────────────────────────────────────

# 股票代码
stock_code_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=".-"),
    min_size=1,
    max_size=20,
)

# ISO 格式时间戳字符串
timestamp_str_st = st.from_regex(
    r"2024-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]",
    fullmatch=True,
)

# 有限浮点数（用于价格、delta 等）
finite_float = st.floats(
    min_value=-1e9, max_value=1e9, allow_nan=False, allow_infinity=False
)

# 正浮点数（用于价格）
positive_float = st.floats(
    min_value=0.01, max_value=1e9, allow_nan=False, allow_infinity=False
)

# 非负整数（用于成交量）
non_negative_int = st.integers(min_value=0, max_value=10**9)

# 正整数
positive_int = st.integers(min_value=1, max_value=10**9)

# 周期秒数（10 或 60）
period_seconds_st = st.sampled_from([10, 60])


# ── 模型生成策略 ─────────────────────────────────────────────────

def delta_update_data_st():
    """生成随机 DeltaUpdateData 实例"""
    return st.builds(
        DeltaUpdateData,
        stock_code=stock_code_st,
        delta=finite_float,
        volume=non_negative_int,
        timestamp=timestamp_str_st,
        period_seconds=period_seconds_st,
    )


def momentum_ignition_data_st():
    """生成随机 MomentumIgnitionData 实例"""
    return st.builds(
        MomentumIgnitionData,
        stock_code=stock_code_st,
        current_count=positive_int,
        baseline_avg=positive_float,
        multiplier=positive_float,
        timestamp=timestamp_str_st,
    )


def price_level_data_st():
    """生成随机 PriceLevelData 实例"""
    return st.builds(
        PriceLevelData,
        stock_code=stock_code_st,
        price=positive_float,
        volume=positive_int,
        side=st.sampled_from(list(PriceLevelSide)),
        action=st.sampled_from(list(PriceLevelAction)),
        timestamp=timestamp_str_st,
    )


def poc_update_data_st():
    """生成随机 PocUpdateData 实例"""
    return st.builds(
        PocUpdateData,
        stock_code=stock_code_st,
        poc_price=positive_float,
        poc_volume=positive_int,
        volume_profile=st.dictionaries(
            keys=st.from_regex(r"[0-9]{1,6}\.[0-9]{1,2}", fullmatch=True),
            values=positive_int,
            min_size=1,
            max_size=10,
        ),
        timestamp=timestamp_str_st,
    )


def scalping_signal_data_st():
    """生成随机 ScalpingSignalData 实例"""
    return st.builds(
        ScalpingSignalData,
        stock_code=stock_code_st,
        signal_type=st.sampled_from(list(ScalpingSignalType)),
        trigger_price=positive_float,
        support_price=st.one_of(st.none(), positive_float),
        conditions=st.lists(
            st.text(min_size=1, max_size=50),
            min_size=1,
            max_size=5,
        ),
        timestamp=timestamp_str_st,
    )


# ── Property 14: 事件数据模型序列化往返一致性 ────────────────────
# Feature: intraday-scalping-engine, Property 14: 事件数据模型序列化往返一致性
# **Validates: Requirements 11.3**


class TestProperty14SerializationRoundTrip:
    """Property 14: 对于任意有效的 Scalping 事件数据模型实例，
    将其序列化为 JSON 后再反序列化，应产生与原始实例等价的对象。"""

    @given(data=delta_update_data_st())
    @settings(max_examples=200)
    def test_delta_update_data_round_trip(self, data: DeltaUpdateData):
        """DeltaUpdateData 序列化往返一致性"""
        json_str = data.model_dump_json()
        restored = DeltaUpdateData.model_validate_json(json_str)
        assert restored == data, (
            f"DeltaUpdateData 往返不一致:\n原始: {data}\n还原: {restored}"
        )

    @given(data=momentum_ignition_data_st())
    @settings(max_examples=200)
    def test_momentum_ignition_data_round_trip(self, data: MomentumIgnitionData):
        """MomentumIgnitionData 序列化往返一致性"""
        json_str = data.model_dump_json()
        restored = MomentumIgnitionData.model_validate_json(json_str)
        assert restored == data, (
            f"MomentumIgnitionData 往返不一致:\n原始: {data}\n还原: {restored}"
        )

    @given(data=price_level_data_st())
    @settings(max_examples=200)
    def test_price_level_data_round_trip(self, data: PriceLevelData):
        """PriceLevelData 序列化往返一致性"""
        json_str = data.model_dump_json()
        restored = PriceLevelData.model_validate_json(json_str)
        assert restored == data, (
            f"PriceLevelData 往返不一致:\n原始: {data}\n还原: {restored}"
        )

    @given(data=poc_update_data_st())
    @settings(max_examples=200)
    def test_poc_update_data_round_trip(self, data: PocUpdateData):
        """PocUpdateData 序列化往返一致性"""
        json_str = data.model_dump_json()
        restored = PocUpdateData.model_validate_json(json_str)
        assert restored == data, (
            f"PocUpdateData 往返不一致:\n原始: {data}\n还原: {restored}"
        )

    @given(data=scalping_signal_data_st())
    @settings(max_examples=200)
    def test_scalping_signal_data_round_trip(self, data: ScalpingSignalData):
        """ScalpingSignalData 序列化往返一致性"""
        json_str = data.model_dump_json()
        restored = ScalpingSignalData.model_validate_json(json_str)
        assert restored == data, (
            f"ScalpingSignalData 往返不一致:\n原始: {data}\n还原: {restored}"
        )
