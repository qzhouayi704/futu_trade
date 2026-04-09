#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kline_utils 单元测试 + 属性测试"""

import pytest
from dataclasses import dataclass
from hypothesis import given, settings
from hypothesis import strategies as st

from simple_trade.services.advisor.kline_utils import (
    extract_field,
    extract_closes,
    extract_volumes,
    FIELD_INDEX_MAP,
)


# ==================== 辅助：模拟对象属性格式 ====================

@dataclass
class FakeKline:
    """模拟带属性的 K线对象"""
    date: str = "2024-01-01"
    open: float = 0.0
    close: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0


# ==================== 单元测试 ====================

class TestExtractField:
    """extract_field 单元测试"""

    def test_dict_format(self):
        kline = {'close': 10.5, 'volume': 1000}
        assert extract_field(kline, 'close') == 10.5
        assert extract_field(kline, 'volume') == 1000.0

    def test_object_format(self):
        kline = FakeKline(close=20.3, volume=500)
        assert extract_field(kline, 'close') == 20.3
        assert extract_field(kline, 'volume') == 500.0

    def test_list_format(self):
        # [date, open, close, high, low, volume]
        kline = ['2024-01-01', 9.0, 10.5, 11.0, 8.5, 2000]
        assert extract_field(kline, 'close', 2) == 10.5
        assert extract_field(kline, 'volume', 5) == 2000.0

    def test_tuple_format(self):
        kline = ('2024-01-01', 9.0, 10.5, 11.0, 8.5, 2000)
        assert extract_field(kline, 'close', 2) == 10.5

    def test_list_auto_index(self):
        """不传 index 时自动从 FIELD_INDEX_MAP 查找"""
        kline = ['2024-01-01', 9.0, 10.5, 11.0, 8.5, 2000]
        assert extract_field(kline, 'close') == 10.5
        assert extract_field(kline, 'volume') == 2000.0

    def test_missing_field_returns_zero(self):
        assert extract_field({}, 'close') == 0.0
        assert extract_field([], 'close') == 0.0

    def test_unsupported_type_returns_zero(self):
        assert extract_field(42, 'close') == 0.0
        assert extract_field(None, 'close') == 0.0

    def test_list_index_out_of_range(self):
        kline = [1, 2]  # 太短
        assert extract_field(kline, 'volume', 5) == 0.0


class TestExtractCloses:
    """extract_closes 单元测试"""

    def test_dict_klines(self):
        klines = [{'close': 10.0}, {'close': 11.0}, {'close': 12.0}]
        assert extract_closes(klines, 2) == [11.0, 12.0]

    def test_object_klines(self):
        klines = [FakeKline(close=10.0), FakeKline(close=11.0)]
        assert extract_closes(klines, 2) == [10.0, 11.0]

    def test_list_klines(self):
        klines = [
            ['2024-01-01', 9.0, 10.0, 11.0, 8.0, 100],
            ['2024-01-02', 10.0, 12.0, 13.0, 9.0, 200],
        ]
        assert extract_closes(klines, 2) == [10.0, 12.0]

    def test_count_exceeds_length(self):
        klines = [{'close': 5.0}]
        assert extract_closes(klines, 10) == [5.0]

    def test_empty_klines(self):
        assert extract_closes([], 5) == []


class TestExtractVolumes:
    """extract_volumes 单元测试"""

    def test_dict_klines(self):
        klines = [{'volume': 100}, {'volume': 200}, {'volume': 300}]
        assert extract_volumes(klines, 2) == [200.0, 300.0]

    def test_object_klines(self):
        klines = [FakeKline(volume=100), FakeKline(volume=200)]
        assert extract_volumes(klines, 1) == [200.0]

    def test_list_klines(self):
        klines = [
            ['2024-01-01', 9.0, 10.0, 11.0, 8.0, 1000],
            ['2024-01-02', 10.0, 12.0, 13.0, 9.0, 2000],
        ]
        assert extract_volumes(klines, 2) == [1000.0, 2000.0]

    def test_empty_klines(self):
        assert extract_volumes([], 3) == []


# ==================== 属性测试 ====================

# 策略：生成合理范围的浮点数（避免 NaN/Inf）
reasonable_float = st.floats(
    min_value=-1e6, max_value=1e6,
    allow_nan=False, allow_infinity=False,
)

# 策略：生成 dict 格式 K线
dict_kline_st = st.fixed_dictionaries({
    'date': st.just('2024-01-01'),
    'open': reasonable_float,
    'close': reasonable_float,
    'high': reasonable_float,
    'low': reasonable_float,
    'volume': reasonable_float,
})

# 策略：生成对象格式 K线
object_kline_st = st.builds(
    FakeKline,
    close=reasonable_float,
    volume=reasonable_float,
    open=reasonable_float,
    high=reasonable_float,
    low=reasonable_float,
)

# 策略：生成 list 格式 K线
list_kline_st = st.tuples(
    st.just('2024-01-01'),  # date
    reasonable_float,        # open
    reasonable_float,        # close
    reasonable_float,        # high
    reasonable_float,        # low
    reasonable_float,        # volume
).map(list)

# 策略：生成 tuple 格式 K线
tuple_kline_st = st.tuples(
    st.just('2024-01-01'),
    reasonable_float,
    reasonable_float,
    reasonable_float,
    reasonable_float,
    reasonable_float,
)


class TestKlinePropertyExtractField:
    """Property 3: K线数据提取格式兼容性 - extract_field

    **Validates: Requirements 4.2, 4.3**
    """

    @given(close=reasonable_float, volume=reasonable_float)
    @settings(max_examples=100)
    def test_dict_close_equals_original(self, close, volume):
        """dict 格式提取的 close 应与原始值相等"""
        kline = {'close': close, 'volume': volume}
        assert extract_field(kline, 'close') == float(close)

    @given(close=reasonable_float, volume=reasonable_float)
    @settings(max_examples=100)
    def test_object_close_equals_original(self, close, volume):
        """对象格式提取的 close 应与原始值相等"""
        kline = FakeKline(close=close, volume=volume)
        assert extract_field(kline, 'close') == float(close)

    @given(close=reasonable_float, volume=reasonable_float)
    @settings(max_examples=100)
    def test_list_close_equals_original(self, close, volume):
        """list 格式提取的 close 应与原始值相等"""
        kline = ['2024-01-01', 0.0, close, 0.0, 0.0, volume]
        assert extract_field(kline, 'close') == float(close)

    @given(close=reasonable_float, volume=reasonable_float)
    @settings(max_examples=100)
    def test_all_formats_consistent(self, close, volume):
        """三种格式提取同一字段的结果应一致"""
        dict_k = {'close': close, 'volume': volume}
        obj_k = FakeKline(close=close, volume=volume)
        list_k = ['2024-01-01', 0.0, close, 0.0, 0.0, volume]

        dict_close = extract_field(dict_k, 'close')
        obj_close = extract_field(obj_k, 'close')
        list_close = extract_field(list_k, 'close')

        assert dict_close == obj_close == list_close

        dict_vol = extract_field(dict_k, 'volume')
        obj_vol = extract_field(obj_k, 'volume')
        list_vol = extract_field(list_k, 'volume')

        assert dict_vol == obj_vol == list_vol


class TestKlinePropertyExtractBatch:
    """Property 3: K线数据提取格式兼容性 - extract_closes / extract_volumes

    **Validates: Requirements 4.2, 4.3**
    """

    @given(klines=st.lists(dict_kline_st, min_size=1, max_size=30),
           count=st.integers(min_value=1, max_value=30))
    @settings(max_examples=100)
    def test_extract_closes_dict_matches_source(self, klines, count):
        """extract_closes 从 dict K线提取的值应与源数据一致"""
        closes = extract_closes(klines, count)
        expected = [float(k['close']) for k in klines[-count:]]
        assert closes == expected

    @given(klines=st.lists(list_kline_st, min_size=1, max_size=30),
           count=st.integers(min_value=1, max_value=30))
    @settings(max_examples=100)
    def test_extract_closes_list_matches_source(self, klines, count):
        """extract_closes 从 list K线提取的值应与源数据一致"""
        closes = extract_closes(klines, count)
        expected = [float(k[2]) for k in klines[-count:]]
        assert closes == expected

    @given(klines=st.lists(dict_kline_st, min_size=1, max_size=30),
           count=st.integers(min_value=1, max_value=30))
    @settings(max_examples=100)
    def test_extract_volumes_dict_matches_source(self, klines, count):
        """extract_volumes 从 dict K线提取的值应与源数据一致"""
        volumes = extract_volumes(klines, count)
        expected = [float(k['volume']) for k in klines[-count:]]
        assert volumes == expected

    @given(klines=st.lists(list_kline_st, min_size=1, max_size=30),
           count=st.integers(min_value=1, max_value=30))
    @settings(max_examples=100)
    def test_extract_volumes_list_matches_source(self, klines, count):
        """extract_volumes 从 list K线提取的值应与源数据一致"""
        volumes = extract_volumes(klines, count)
        expected = [float(k[5]) for k in klines[-count:]]
        assert volumes == expected

    @given(
        close=reasonable_float,
        volume=reasonable_float,
    )
    @settings(max_examples=100)
    def test_three_formats_batch_consistent(self, close, volume):
        """三种格式的 K线列表，extract_closes 和 extract_volumes 结果一致"""
        dict_klines = [{'close': close, 'volume': volume}]
        obj_klines = [FakeKline(close=close, volume=volume)]
        list_klines = [['2024-01-01', 0.0, close, 0.0, 0.0, volume]]

        assert (
            extract_closes(dict_klines, 1)
            == extract_closes(obj_klines, 1)
            == extract_closes(list_klines, 1)
        )
        assert (
            extract_volumes(dict_klines, 1)
            == extract_volumes(obj_klines, 1)
            == extract_volumes(list_klines, 1)
        )
