#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MarketHeatMonitor 属性测试

使用 hypothesis 验证市场热度监控器的核心正确性属性：
- Property 1: 板块热度排序正确性
- Property 2: 市场热度范围不变量
"""

import os
import sys

import pytest
from hypothesis import given, settings, strategies as st, assume

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.analysis.heat.heat_score_engine import HeatScoreEngine
from simple_trade.services.analysis.heat.market_heat_monitor import MarketHeatMonitor


# ── hypothesis 策略 ──────────────────────────────────────────────

# 涨跌幅（港美股无涨停板，范围可以较大）
change_pct_st = st.floats(
    min_value=-30.0, max_value=30.0, allow_nan=False, allow_infinity=False
)

# 换手率
turnover_rate_st = st.floats(
    min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False
)

# 资金净流入占比
net_inflow_st = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)

# 股票名称
stock_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L",)), min_size=1, max_size=6
)


def quote_strategy():
    """生成单条报价数据"""
    return st.fixed_dictionaries({
        "change_pct": change_pct_st,
        "turnover_rate": turnover_rate_st,
        "stock_name": stock_name_st,
        "net_inflow_ratio": net_inflow_st,
    })


def plate_strategy():
    """生成单个板块数据（含 1-20 只股票）"""
    return st.integers(min_value=1, max_value=20).flatmap(
        lambda n: st.tuples(
            st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=2, max_size=6),
            st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=1, max_size=8),
            st.just(n),
            st.lists(quote_strategy(), min_size=n, max_size=n),
        )
    )


def plates_with_quotes_strategy():
    """生成 1-10 个板块及其对应的 quotes_map"""
    return st.lists(plate_strategy(), min_size=1, max_size=10).map(
        _build_plates_and_quotes
    )


def _build_plates_and_quotes(plate_tuples):
    """将生成的板块元组转换为 plates 列表和 quotes_map 字典"""
    plates = []
    quotes_map = {}

    for idx, (code_suffix, name, stock_count, quotes) in enumerate(plate_tuples):
        plate_code = f"PL{idx:03d}{code_suffix}"
        stock_codes = [f"{plate_code}_S{j:03d}" for j in range(stock_count)]

        plates.append({
            "plate_code": plate_code,
            "plate_name": f"板块{name}",
            "stock_count": stock_count,
            "stocks": stock_codes,
        })

        for j, code in enumerate(stock_codes):
            quotes_map[code] = quotes[j]

    return plates, quotes_map


# ── Property 1: 板块热度排序正确性 ──────────────────────────────
# Feature: enhanced-heat-optimization, Property 1: 板块热度排序正确性
# **Validates: Requirements 1.1, 1.2, 1.4**

REQUIRED_PLATE_FIELDS = {
    "plate_code", "plate_name", "stock_count",
    "avg_change_pct", "up_ratio", "hot_stock_count",
    "leading_stock_name", "heat_score",
}


class TestProperty1PlateHeatSorting:
    """Property 1: 对于任意板块列表和实时报价数据，返回的热门板块列表
    应按板块热度分降序排列，且每个板块数据包含全部必需字段。"""

    @given(data=plates_with_quotes_strategy())
    @settings(max_examples=200)
    def test_hot_plates_sorted_descending(self, data):
        """热门板块应按 heat_score 降序排列"""
        plates, quotes_map = data
        monitor = MarketHeatMonitor(db_manager=None, config={})

        result = monitor.get_hot_plates(plates, quotes_map, top_n=len(plates))

        # 验证降序排列
        for i in range(len(result) - 1):
            assert result[i]["heat_score"] >= result[i + 1]["heat_score"], (
                f"板块排序错误: index {i} heat_score={result[i]['heat_score']} "
                f"< index {i+1} heat_score={result[i+1]['heat_score']}"
            )

    @given(data=plates_with_quotes_strategy())
    @settings(max_examples=200)
    def test_hot_plates_contain_required_fields(self, data):
        """每个板块数据应包含全部必需字段"""
        plates, quotes_map = data
        monitor = MarketHeatMonitor(db_manager=None, config={})

        result = monitor.get_hot_plates(plates, quotes_map, top_n=len(plates))

        for plate_data in result:
            missing = REQUIRED_PLATE_FIELDS - set(plate_data.keys())
            assert not missing, (
                f"板块 {plate_data.get('plate_code', '?')} 缺少字段: {missing}"
            )

    @given(data=plates_with_quotes_strategy())
    @settings(max_examples=200)
    def test_hot_plates_heat_score_matches_formula(self, data):
        """板块热度分应与评分引擎 calculate_plate_heat 的计算结果一致"""
        plates, quotes_map = data
        monitor = MarketHeatMonitor(db_manager=None, config={})
        engine = monitor.score_engine

        result = monitor.get_hot_plates(plates, quotes_map, top_n=len(plates))

        for plate_data in result:
            # 找到原始板块数据
            original = next(
                (p for p in plates if p["plate_code"] == plate_data["plate_code"]),
                None,
            )
            assert original is not None

            # 收集板块内报价
            stock_codes = original.get("stocks", [])
            plate_quotes = [quotes_map[c] for c in stock_codes if c in quotes_map]

            if not plate_quotes:
                assert plate_data["heat_score"] == 0.0
                continue

            total = len(plate_quotes)
            up_count = sum(1 for q in plate_quotes if q.get("change_pct", 0) > 0)
            up_ratio = up_count / total
            avg_change = sum(q.get("change_pct", 0) for q in plate_quotes) / total
            big_rise_count = sum(1 for q in plate_quotes if q.get("change_pct", 0) > 3.0)
            big_rise_ratio = big_rise_count / total
            inflows = [q.get("net_inflow_ratio", 0) for q in plate_quotes]
            net_inflow = max(sum(inflows) / len(inflows), 0.0)

            expected = engine.calculate_plate_heat(
                up_ratio=round(up_ratio, 4),
                avg_change_pct=round(avg_change, 2),
                big_rise_ratio=big_rise_ratio,
                net_inflow_ratio=net_inflow,
            )

            assert plate_data["heat_score"] == pytest.approx(expected, abs=1e-6), (
                f"板块 {plate_data['plate_code']}: "
                f"actual={plate_data['heat_score']}, expected={expected}"
            )


# ── Property 2: 市场热度范围不变量 ──────────────────────────────
# Feature: enhanced-heat-optimization, Property 2: 市场热度范围不变量
# **Validates: Requirements 2.1, 2.2, 2.4**


class TestProperty2MarketHeatRange:
    """Property 2: 对于任意非空的实时报价数据列表，市场热度分数
    应在 0-100 范围内（含边界）。"""

    @given(quotes=st.lists(quote_strategy(), min_size=1, max_size=100))
    @settings(max_examples=200)
    def test_market_heat_in_range(self, quotes):
        """市场热度应在 [0, 100] 范围内"""
        monitor = MarketHeatMonitor(db_manager=None, config={})
        heat = monitor.calculate_market_heat(quotes)

        assert 0.0 <= heat <= 100.0, (
            f"市场热度 {heat} 超出 [0, 100] 范围，"
            f"输入 {len(quotes)} 条报价"
        )

    @given(quotes=st.lists(quote_strategy(), min_size=1, max_size=100))
    @settings(max_examples=200)
    def test_market_heat_based_on_three_dimensions(self, quotes):
        """市场热度应等于上涨比例×40% + 平均涨幅归一化×30% + 平均换手率归一化×30%"""
        monitor = MarketHeatMonitor(db_manager=None, config={})
        engine = monitor.score_engine

        actual = monitor.calculate_market_heat(quotes)

        # 手动计算三个维度
        total = len(quotes)
        up_count = sum(1 for q in quotes if q.get("change_pct", 0) > 0)
        up_score = (up_count / total) * 100

        avg_change = sum(q.get("change_pct", 0) for q in quotes) / total
        change_score = engine.normalize(avg_change, cap=10)

        avg_turnover = sum(q.get("turnover_rate", 0) for q in quotes) / total
        turnover_score = engine.normalize(avg_turnover, cap=20)

        expected = round(
            min(max(up_score * 0.4 + change_score * 0.3 + turnover_score * 0.3, 0), 100),
            2,
        )

        assert actual == pytest.approx(expected, abs=1e-6), (
            f"市场热度公式不一致: actual={actual}, expected={expected}"
        )

    def test_empty_quotes_returns_default(self):
        """空报价列表应返回默认值 50.0"""
        monitor = MarketHeatMonitor(db_manager=None, config={})

        assert monitor.calculate_market_heat(None) == 50.0
        assert monitor.calculate_market_heat([]) == 50.0
