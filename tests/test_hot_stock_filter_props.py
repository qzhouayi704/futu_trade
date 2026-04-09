#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HotStockFilter 属性测试

使用 hypothesis 验证热门股票筛选器的核心正确性属性：
- Property 3: 热门股票筛选条件满足性

对于任意板块及其股票报价数据，热门股票筛选器返回的每只股票都应满足：
涨幅大于该板块平均涨幅，且量比大于 1.5；返回数量应在 0-10 只范围内。
"""

import os
import sys

import pytest
from hypothesis import given, settings, strategies as st, assume

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.analysis.heat.heat_score_engine import HeatScoreEngine
from simple_trade.services.market_data.hot_stock.hot_stock_filter import (
    HotStockFilter,
    HotStockItem,
)


# ── hypothesis 策略 ──────────────────────────────────────────────

# 涨跌幅
change_pct_st = st.floats(min_value=-30.0, max_value=30.0, allow_nan=False, allow_infinity=False)

# 量比（0 到 10）
volume_ratio_st = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)

# 换手率（港股阈值 0.1%，生成范围覆盖阈值上下）
turnover_rate_st = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)

# 价格（港股阈值 1.0 元，生成范围覆盖阈值上下）
price_st = st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False)

# 成交量（港股阈值 50 万，生成范围覆盖阈值上下）
volume_st = st.integers(min_value=0, max_value=10_000_000)


@st.composite
def quote_strategy(draw):
    """生成单个股票的报价数据（港股格式）"""
    price = draw(price_st)
    return {
        "change_pct": draw(change_pct_st),
        "volume_ratio": draw(volume_ratio_st),
        "turnover_rate": draw(turnover_rate_st),
        "last_price": price,
        "cur_price": price,
        "volume": draw(volume_st),
    }


@st.composite
def plate_data_strategy(draw):
    """生成一个板块的股票列表和对应的报价数据

    使用 HK. 前缀，港股活跃度阈值较低（50万成交量、0.1%换手率、1元价格），
    生成的数据有合理概率通过活跃度筛选。
    """
    n_stocks = draw(st.integers(min_value=1, max_value=30))

    stocks = []
    quotes_map = {}
    for i in range(n_stocks):
        code = f"HK.STOCK_{i:04d}"
        stocks.append({
            "stock_code": code,
            "stock_name": f"Stock {i}",
            "market": "HK",
        })
        quotes_map[code] = draw(quote_strategy())

    return stocks, quotes_map


# ── Property 3: 热门股票筛选条件满足性 ──────────────────────────
# Feature: enhanced-heat-optimization, Property 3: 热门股票筛选条件满足性
# **Validates: Requirements 3.2**


class TestProperty3HotStockFilterConditions:
    """Property 3: 对于任意板块及其股票报价数据，热门股票筛选器返回的
    每只股票都应满足：涨幅大于该板块平均涨幅，且量比大于 1.5；
    返回数量应在 0-10 只范围内。"""

    @given(data=plate_data_strategy())
    @settings(max_examples=200)
    def test_every_hot_stock_change_pct_above_avg(self, data):
        """每只热门股票的涨幅应大于板块平均涨幅（活跃股票的平均涨幅）"""
        stocks, quotes_map = data
        engine = HeatScoreEngine()
        hsf = HotStockFilter(score_engine=engine)

        result = hsf.filter_hot_stocks(
            plate_code="TEST_PLATE",
            plate_name="测试板块",
            stocks=stocks,
            quotes_map=quotes_map,
        )

        if not result:
            return  # 没有满足条件的股票，属性自然成立

        # 计算板块平均涨幅（与实现一致：只计算通过活跃度筛选的股票）
        active_change_pcts = [
            quotes_map[s["stock_code"]].get("change_pct", 0.0)
            for s in stocks
            if s["stock_code"] in quotes_map
            and HotStockFilter.check_stock_activity(s["stock_code"], quotes_map[s["stock_code"]])
        ]
        assume(len(active_change_pcts) > 0)
        avg_change = sum(active_change_pcts) / len(active_change_pcts)

        for item in result:
            assert item.change_pct > avg_change, (
                f"股票 {item.stock_code} 涨幅 {item.change_pct} "
                f"不大于板块平均涨幅 {avg_change}"
            )

    @given(data=plate_data_strategy())
    @settings(max_examples=200)
    def test_every_hot_stock_volume_ratio_above_threshold(self, data):
        """每只热门股票的量比应大于 1.5"""
        stocks, quotes_map = data
        engine = HeatScoreEngine()
        hsf = HotStockFilter(score_engine=engine)

        result = hsf.filter_hot_stocks(
            plate_code="TEST_PLATE",
            plate_name="测试板块",
            stocks=stocks,
            quotes_map=quotes_map,
        )

        for item in result:
            assert item.volume_ratio > 1.5, (
                f"股票 {item.stock_code} 量比 {item.volume_ratio} 不大于 1.5"
            )

    @given(data=plate_data_strategy())
    @settings(max_examples=200)
    def test_result_count_within_range(self, data):
        """返回数量应在 0-10 只范围内（max_per_plate 默认值为 10）"""
        stocks, quotes_map = data
        engine = HeatScoreEngine()
        hsf = HotStockFilter(score_engine=engine)

        result = hsf.filter_hot_stocks(
            plate_code="TEST_PLATE",
            plate_name="测试板块",
            stocks=stocks,
            quotes_map=quotes_map,
        )

        assert 0 <= len(result) <= 10, (
            f"返回数量 {len(result)} 不在 [0, 10] 范围内"
        )

    @given(data=plate_data_strategy())
    @settings(max_examples=200)
    def test_result_sorted_by_heat_score_desc(self, data):
        """返回结果应按 heat_score 降序排列"""
        stocks, quotes_map = data
        engine = HeatScoreEngine()
        hsf = HotStockFilter(score_engine=engine)

        result = hsf.filter_hot_stocks(
            plate_code="TEST_PLATE",
            plate_name="测试板块",
            stocks=stocks,
            quotes_map=quotes_map,
        )

        for i in range(len(result) - 1):
            assert result[i].heat_score >= result[i + 1].heat_score, (
                f"排序错误: 第{i}只 heat_score={result[i].heat_score} "
                f"< 第{i+1}只 heat_score={result[i+1].heat_score}"
            )

    @given(
        data=plate_data_strategy(),
        max_count=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=200)
    def test_result_respects_custom_max_per_plate(self, data, max_count):
        """自定义 max_per_plate 时，返回数量不超过该值"""
        stocks, quotes_map = data
        engine = HeatScoreEngine()
        hsf = HotStockFilter(score_engine=engine)

        result = hsf.filter_hot_stocks(
            plate_code="TEST_PLATE",
            plate_name="测试板块",
            stocks=stocks,
            quotes_map=quotes_map,
            max_per_plate=max_count,
        )

        assert len(result) <= max_count, (
            f"返回数量 {len(result)} 超过 max_per_plate={max_count}"
        )
