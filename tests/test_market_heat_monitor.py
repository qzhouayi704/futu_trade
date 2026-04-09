#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MarketHeatMonitor 单元测试

验证改造后的市场热度监控器：
- calculate_market_heat: 基于实时报价计算市场热度
- get_hot_plates: 基于实时数据计算板块热度并排序
- 空数据降级策略
- recommend_position_ratio / detect_market_sentiment 保持不变
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.analysis.heat.heat_score_engine import HeatScoreEngine
from simple_trade.services.analysis.heat.market_heat_monitor import (
    MarketHeatMonitor,
)


@pytest.fixture
def engine():
    return HeatScoreEngine()


@pytest.fixture
def monitor(engine):
    return MarketHeatMonitor(db_manager=None, config={}, score_engine=engine)


# ── calculate_market_heat ───────────────────────────────────


class TestCalculateMarketHeat:
    def test_empty_quotes_returns_default(self, monitor):
        """空报价列表返回默认值 50.0（需求 2.3）"""
        assert monitor.calculate_market_heat([]) == 50.0
        assert monitor.calculate_market_heat(None) == 50.0

    def test_all_up_stocks(self, monitor):
        """全部上涨时热度应较高"""
        quotes = [
            {"change_pct": 5.0, "turnover_rate": 10.0},
            {"change_pct": 3.0, "turnover_rate": 8.0},
            {"change_pct": 2.0, "turnover_rate": 6.0},
        ]
        heat = monitor.calculate_market_heat(quotes)
        assert 0 <= heat <= 100
        assert heat > 50  # 全部上涨，热度应高于默认值

    def test_all_down_stocks(self, monitor):
        """全部下跌时热度应较低"""
        quotes = [
            {"change_pct": -5.0, "turnover_rate": 1.0},
            {"change_pct": -3.0, "turnover_rate": 0.5},
        ]
        heat = monitor.calculate_market_heat(quotes)
        assert 0 <= heat <= 100
        # 上涨比例=0，平均涨幅为负（归一化后=0），换手率低
        assert heat < 20

    def test_output_range(self, monitor):
        """输出始终在 0-100 范围内（需求 2.4）"""
        quotes = [
            {"change_pct": 50.0, "turnover_rate": 100.0},
            {"change_pct": -50.0, "turnover_rate": 0.0},
        ]
        heat = monitor.calculate_market_heat(quotes)
        assert 0 <= heat <= 100

    def test_weight_correctness(self, monitor):
        """验证权重 40%/30%/30%"""
        # 只有上涨比例贡献：全部上涨，涨幅=0，换手率=0
        # change_pct > 0 但值极小，归一化后接近 0
        quotes = [{"change_pct": 0.001, "turnover_rate": 0}]
        heat = monitor.calculate_market_heat(quotes)
        # up_ratio=1.0 → up_score=100, change_score≈0, turnover_score=0
        # score ≈ 100*0.4 = 40
        assert heat == pytest.approx(40.0, abs=1.0)

    def test_missing_fields_treated_as_zero(self, monitor):
        """缺失字段视为 0"""
        quotes = [{}]
        heat = monitor.calculate_market_heat(quotes)
        assert heat == 0.0  # 无上涨，无涨幅，无换手率

    def test_no_args_backward_compat(self, monitor):
        """无参数调用返回默认值（向后兼容）"""
        heat = monitor.calculate_market_heat()
        assert heat == 50.0


# ── get_hot_plates ──────────────────────────────────────────


def _make_plates_and_quotes():
    """构造测试用板块和报价数据"""
    plates = [
        {
            "plate_code": "P001",
            "plate_name": "科技板块",
            "stock_count": 3,
            "stocks": ["S001", "S002", "S003"],
        },
        {
            "plate_code": "P002",
            "plate_name": "金融板块",
            "stock_count": 2,
            "stocks": ["S004", "S005"],
        },
    ]
    quotes_map = {
        "S001": {"change_pct": 8.0, "turnover_rate": 15.0, "stock_name": "科技A"},
        "S002": {"change_pct": 5.0, "turnover_rate": 10.0, "stock_name": "科技B"},
        "S003": {"change_pct": -1.0, "turnover_rate": 3.0, "stock_name": "科技C"},
        "S004": {"change_pct": 1.0, "turnover_rate": 2.0, "stock_name": "金融A"},
        "S005": {"change_pct": -2.0, "turnover_rate": 1.0, "stock_name": "金融B"},
    }
    return plates, quotes_map


class TestGetHotPlates:
    def test_empty_plates_returns_empty(self, monitor):
        """空板块数据返回空列表"""
        assert monitor.get_hot_plates([], {}) == []
        assert monitor.get_hot_plates(None, {}) == []

    def test_returns_required_fields(self, monitor):
        """返回数据包含所有必需字段（需求 1.4）"""
        plates, quotes_map = _make_plates_and_quotes()
        result = monitor.get_hot_plates(plates, quotes_map)

        required_fields = {
            "plate_code", "plate_name", "stock_count",
            "avg_change_pct", "up_ratio", "hot_stock_count",
            "leading_stock_name", "heat_score",
        }
        for plate in result:
            assert required_fields.issubset(plate.keys())

    def test_sorted_by_heat_score_desc(self, monitor):
        """按热度分降序排列（需求 1.1）"""
        plates, quotes_map = _make_plates_and_quotes()
        result = monitor.get_hot_plates(plates, quotes_map)

        scores = [p["heat_score"] for p in result]
        assert scores == sorted(scores, reverse=True)

    def test_plate_with_no_quotes_gets_zero(self, monitor):
        """无报价数据的板块热度分为 0（需求 1.5）"""
        plates = [
            {
                "plate_code": "P_EMPTY",
                "plate_name": "空板块",
                "stock_count": 5,
                "stocks": ["NONE1", "NONE2"],
            }
        ]
        result = monitor.get_hot_plates(plates, {})
        assert len(result) == 1
        assert result[0]["heat_score"] == 0.0
        assert result[0]["avg_change_pct"] == 0.0
        assert result[0]["leading_stock_name"] == ""

    def test_hot_stock_count_threshold(self, monitor):
        """大涨股数量：涨幅 > 3%（需求 1.3）"""
        plates, quotes_map = _make_plates_and_quotes()
        result = monitor.get_hot_plates(plates, quotes_map)

        # 科技板块：S001(8%) 和 S002(5%) 涨幅>3%，hot_stock_count=2
        tech_plate = next(p for p in result if p["plate_code"] == "P001")
        assert tech_plate["hot_stock_count"] == 2

        # 金融板块：无股票涨幅>3%
        fin_plate = next(p for p in result if p["plate_code"] == "P002")
        assert fin_plate["hot_stock_count"] == 0

    def test_leading_stock_name(self, monitor):
        """领涨股为涨幅最高的股票"""
        plates, quotes_map = _make_plates_and_quotes()
        result = monitor.get_hot_plates(plates, quotes_map)

        tech_plate = next(p for p in result if p["plate_code"] == "P001")
        assert tech_plate["leading_stock_name"] == "科技A"  # 涨幅 8%

    def test_up_ratio_calculation(self, monitor):
        """涨跌比计算正确"""
        plates, quotes_map = _make_plates_and_quotes()
        result = monitor.get_hot_plates(plates, quotes_map)

        # 科技板块：2/3 上涨
        tech_plate = next(p for p in result if p["plate_code"] == "P001")
        assert tech_plate["up_ratio"] == pytest.approx(2 / 3, abs=0.01)

        # 金融板块：1/2 上涨
        fin_plate = next(p for p in result if p["plate_code"] == "P002")
        assert fin_plate["up_ratio"] == pytest.approx(0.5, abs=0.01)

    def test_top_n_limit(self, monitor):
        """top_n 限制返回数量"""
        plates, quotes_map = _make_plates_and_quotes()
        result = monitor.get_hot_plates(plates, quotes_map, top_n=1)
        assert len(result) == 1

    def test_no_args_backward_compat(self, monitor):
        """无参数调用返回空列表（向后兼容）"""
        result = monitor.get_hot_plates()
        assert result == []


# ── recommend_position_ratio（保持不变）──────────────────────


class TestRecommendPositionRatio:
    def test_hot_market(self, monitor):
        assert monitor.recommend_position_ratio(85) == 0.8

    def test_normal_market(self, monitor):
        assert monitor.recommend_position_ratio(65) == 0.6

    def test_cold_market(self, monitor):
        assert monitor.recommend_position_ratio(45) == 0.4

    def test_very_cold_market(self, monitor):
        assert monitor.recommend_position_ratio(15) == 0.2


# ── detect_market_sentiment（保持不变）──────────────────────


class TestDetectMarketSentiment:
    def test_sentiments(self, monitor):
        assert monitor.detect_market_sentiment(90) == "极度活跃"
        assert monitor.detect_market_sentiment(70) == "活跃"
        assert monitor.detect_market_sentiment(50) == "正常"
        assert monitor.detect_market_sentiment(30) == "冷淡"
        assert monitor.detect_market_sentiment(10) == "极度冷淡"
