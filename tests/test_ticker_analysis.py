#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐笔成交分析 - 核心单元测试

测试 ticker_dimensions.py 中 4 个维度分析函数的边界情况和具体示例，
以及 CombinedAnalyzer 的矛盾检测和降级逻辑。
"""

import pytest

from simple_trade.services.market_data.ticker_analysis.ticker_dimensions import (
    analyze_active_buy_sell,
    analyze_big_order_ratio,
)
from simple_trade.services.market_data.ticker_analysis.ticker_dimensions_ext import (
    analyze_trade_rhythm,
    analyze_volume_clusters,
)
from simple_trade.services.market_data.ticker_analysis.ticker_service import (
    TickerRecord,
)
from simple_trade.services.market_data.ticker_analysis.combined_analyzer import (
    CombinedAnalyzer,
)


# ==================== 辅助函数 ====================


def _make_record(
    direction="BUY",
    price=100.0,
    volume=100,
    turnover=10000.0,
    time="2024-01-01 10:00:00",
):
    """创建测试用 TickerRecord"""
    return TickerRecord(
        time=time, price=price, volume=volume,
        turnover=turnover, direction=direction,
    )


# ==================== 1. 空成交记录列表 ====================


class TestEmptyRecords:
    """空成交记录列表：所有 4 个维度返回 signal='neutral', score=0"""

    def test_active_buy_sell_empty(self):
        result = analyze_active_buy_sell([])
        assert result.signal == "neutral"
        assert result.score == 0.0

    def test_big_order_ratio_empty(self):
        result = analyze_big_order_ratio([], min_order_amount=100000)
        assert result.signal == "neutral"
        assert result.score == 0.0

    def test_volume_clusters_empty(self):
        result = analyze_volume_clusters([], current_price=100.0)
        assert result.signal == "neutral"
        assert result.score == 0.0
        assert result.details["clusters"] == []

    def test_trade_rhythm_empty(self):
        result = analyze_trade_rhythm([])
        assert result.signal == "neutral"
        assert result.score == 0.0
        assert result.details["pattern"] == "平稳"


# ==================== 2. 全部为 BUY 的记录 ====================


class TestAllBuyRecords:
    """全部为 BUY 的记录：analyze_active_buy_sell 评分应为正值"""

    def test_all_buy_positive_score(self):
        records = [_make_record(direction="BUY") for _ in range(10)]
        result = analyze_active_buy_sell(records)
        assert result.score > 0, f"全部 BUY 记录评分应为正值，实际: {result.score}"
        assert result.details["buy_count"] == 10
        assert result.details["sell_count"] == 0


# ==================== 3. 全部为 SELL 的记录 ====================


class TestAllSellRecords:
    """全部为 SELL 的记录：analyze_active_buy_sell 评分应为负值"""

    def test_all_sell_negative_score(self):
        records = [_make_record(direction="SELL") for _ in range(10)]
        result = analyze_active_buy_sell(records)
        assert result.score < 0, f"全部 SELL 记录评分应为负值，实际: {result.score}"
        assert result.details["sell_count"] == 10
        assert result.details["buy_count"] == 0


# ==================== 4. sell_turnover 为零（全部 BUY） ====================


class TestZeroSellTurnover:
    """sell_turnover 为零时，力量比返回 10.0"""

    def test_buy_sell_ratio_cap(self):
        records = [_make_record(direction="BUY", turnover=50000.0) for _ in range(5)]
        result = analyze_active_buy_sell(records)
        assert result.details["sell_turnover"] == 0.0
        assert result.details["buy_sell_ratio"] == 10.0


# ==================== 5. 只有 1 笔成交 ====================


class TestSingleRecord:
    """只有 1 笔成交：analyze_volume_clusters 密集区只有 1 个"""

    def test_single_record_one_cluster(self):
        records = [_make_record(price=150.0)]
        result = analyze_volume_clusters(records, current_price=100.0)
        assert result.details["cluster_count"] == 1
        assert len(result.details["clusters"]) == 1


# ==================== 6. 所有成交同一价格 ====================


class TestSamePriceRecords:
    """所有成交同一价格：analyze_volume_clusters 密集区只有 1 个"""

    def test_same_price_one_cluster(self):
        records = [_make_record(price=100.0) for _ in range(20)]
        result = analyze_volume_clusters(records, current_price=100.0)
        assert result.details["cluster_count"] == 1
        assert len(result.details["clusters"]) == 1


# ==================== 7. 只有 1 个时间窗口 ====================


class TestSingleTimeWindow:
    """所有记录同一分钟：节奏为'平稳'，变化率为 0"""

    def test_single_window_stable(self):
        records = [
            _make_record(time="2024-01-01 10:00:01"),
            _make_record(time="2024-01-01 10:00:30"),
            _make_record(time="2024-01-01 10:00:59"),
        ]
        result = analyze_trade_rhythm(records)
        assert result.details["pattern"] == "平稳"
        assert result.details["change_rate"] == 0.0
        assert result.details["window_count"] == 1


# ==================== 8. 矛盾检测 ====================


class TestContradictionDetection:
    """CombinedAnalyzer._check_contradiction 矛盾检测"""

    def test_contradiction_true(self):
        """ob_score=30, ticker_score=-20：符号相反且绝对值均 > 10 → True"""
        assert CombinedAnalyzer._check_contradiction(30, -20) is True

    def test_contradiction_false_low_ob(self):
        """ob_score=5, ticker_score=-20：ob_score 绝对值 <= 10 → False"""
        assert CombinedAnalyzer._check_contradiction(5, -20) is False

    def test_contradiction_false_same_sign(self):
        """同号不矛盾"""
        assert CombinedAnalyzer._check_contradiction(30, 20) is False

    def test_contradiction_false_zero(self):
        """零值不矛盾"""
        assert CombinedAnalyzer._check_contradiction(0, -20) is False
