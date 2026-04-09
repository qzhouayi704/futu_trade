#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
属性测试：热门股票列表按热度降序排列

Feature: fix-stock-monitor-api, Property 1: 热门股票列表按热度降序排列
**Validates: Requirements 1.2**

使用 hypothesis 生成随机股票数据，调用 filter_and_sort_stocks 排序逻辑，
验证返回结果按 heat_score 降序排列。
"""

import os
import sys

import pytest
from hypothesis import given, settings, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.routers.data.helpers.route_helpers import filter_and_sort_stocks


# ── hypothesis 策略 ──────────────────────────────────────────────

# 市场类型
market_st = st.sampled_from(["HK", "US"])

# 成交量（确保能通过过滤）
volume_st = st.integers(min_value=0, max_value=50_000_000)

# 价格
price_st = st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False)

# 换手率
turnover_rate_st = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)

# 成交额
turnover_st = st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False)


@st.composite
def stock_data_strategy(draw):
    """生成随机股票数据列表及对应的报价映射

    使用宽松的 filter_config（min_volume=0, enabled=False）确保股票不被过滤掉，
    使用空的 cached_heat_scores 让函数实时计算热度。
    """
    n_stocks = draw(st.integers(min_value=0, max_value=50))

    stocks_data = []
    quotes_map = {}

    for i in range(n_stocks):
        market = draw(market_st)
        code = f"{market}.TEST_{i:04d}"
        name = f"测试股票{i}"

        stocks_data.append({
            "id": i + 1,
            "code": code,
            "name": name,
            "market": market,
        })

        quotes_map[code] = {
            "volume": draw(volume_st),
            "last_price": draw(price_st),
            "turnover_rate": draw(turnover_rate_st),
            "turnover": draw(turnover_st),
        }

    return stocks_data, quotes_map


# 宽松的过滤配置，确保股票不被过滤掉
PERMISSIVE_FILTER_CONFIG = {
    "enabled": False,
    "min_volume": 0,
    "turnover_rate_weight": 0.4,
    "turnover_weight": 0.6,
    "turnover_rate_max_threshold": 5.0,
    "turnover_max_threshold": 50000000,
}

# 最低价格设为 0，不过滤任何股票
PERMISSIVE_MIN_PRICE = {"HK": 0, "US": 0}


# ── Property 1: 热门股票列表按热度降序排列 ──────────────────────
# Feature: fix-stock-monitor-api, Property 1: 热门股票列表按热度降序排列
# **Validates: Requirements 1.2**


class TestProperty1HotStockSortOrder:
    """Property 1: 对于任意 filter_and_sort_stocks 返回的股票列表，
    列表中每只股票的 heat_score 应大于或等于其后一只股票的 heat_score。"""

    @given(data=stock_data_strategy())
    @settings(max_examples=100)
    def test_result_sorted_by_heat_score_desc(self, data):
        """返回的股票列表应严格按 heat_score 降序排列"""
        stocks_data, quotes_map = data

        filtered_stocks, _ = filter_and_sort_stocks(
            stocks_data=stocks_data,
            quotes_map=quotes_map,
            cached_heat_scores={},
            filter_config=PERMISSIVE_FILTER_CONFIG,
            min_stock_price=PERMISSIVE_MIN_PRICE,
        )

        for i in range(len(filtered_stocks) - 1):
            current_score = filtered_stocks[i].get("heat_score", 0)
            next_score = filtered_stocks[i + 1].get("heat_score", 0)
            assert current_score >= next_score, (
                f"排序错误: 第{i}只股票 heat_score={current_score} "
                f"< 第{i+1}只股票 heat_score={next_score}"
            )

    @given(data=stock_data_strategy())
    @settings(max_examples=100)
    def test_sort_order_with_cached_heat_scores(self, data):
        """使用缓存热度分数时，返回结果仍按 heat_score 降序排列"""
        stocks_data, quotes_map = data

        # 为部分股票生成缓存热度分数
        cached_heat_scores = {}
        for i, stock in enumerate(stocks_data):
            if i % 2 == 0:  # 偶数索引的股票使用缓存热度
                cached_heat_scores[stock["code"]] = {
                    "heat_score": float(i * 10 + 5)
                }

        filtered_stocks, _ = filter_and_sort_stocks(
            stocks_data=stocks_data,
            quotes_map=quotes_map,
            cached_heat_scores=cached_heat_scores,
            filter_config=PERMISSIVE_FILTER_CONFIG,
            min_stock_price=PERMISSIVE_MIN_PRICE,
        )

        for i in range(len(filtered_stocks) - 1):
            current_score = filtered_stocks[i].get("heat_score", 0)
            next_score = filtered_stocks[i + 1].get("heat_score", 0)
            assert current_score >= next_score, (
                f"排序错误（含缓存热度）: 第{i}只股票 heat_score={current_score} "
                f"< 第{i+1}只股票 heat_score={next_score}"
            )

    @given(
        data=stock_data_strategy(),
        limit=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=100)
    def test_sort_order_with_limit(self, data, limit):
        """限制返回数量时，返回结果仍按 heat_score 降序排列且不超过 limit"""
        stocks_data, quotes_map = data

        filtered_stocks, _ = filter_and_sort_stocks(
            stocks_data=stocks_data,
            quotes_map=quotes_map,
            cached_heat_scores={},
            filter_config=PERMISSIVE_FILTER_CONFIG,
            min_stock_price=PERMISSIVE_MIN_PRICE,
            limit=limit,
        )

        # 验证数量不超过 limit
        assert len(filtered_stocks) <= limit, (
            f"返回数量 {len(filtered_stocks)} 超过 limit={limit}"
        )

        # 验证排序
        for i in range(len(filtered_stocks) - 1):
            current_score = filtered_stocks[i].get("heat_score", 0)
            next_score = filtered_stocks[i + 1].get("heat_score", 0)
            assert current_score >= next_score, (
                f"排序错误（limit={limit}）: 第{i}只股票 heat_score={current_score} "
                f"< 第{i+1}只股票 heat_score={next_score}"
            )
