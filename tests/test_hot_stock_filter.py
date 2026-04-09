#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HotStockFilter 单元测试

验证热门股票筛选器的核心逻辑：
- HotStockItem 数据类和 to_dict
- filter_hot_stocks 板块内筛选（含活跃度预筛选）
- get_all_hot_stocks 全板块遍历
- check_stock_activity 活跃度检查
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.analysis.heat.heat_score_engine import HeatScoreEngine
from simple_trade.services.market_data.hot_stock.hot_stock_filter import (
    ACTIVITY_THRESHOLDS,
    HotStockFilter,
    HotStockItem,
)


@pytest.fixture
def engine():
    return HeatScoreEngine()


@pytest.fixture
def hsf(engine):
    return HotStockFilter(score_engine=engine)


def _make_stock(code: str, name: str = "", market: str = "HK"):
    return {"stock_code": code, "stock_name": name or code, "market": market}


def _make_quote(
    change_pct: float = 5.0,
    volume_ratio: float = 2.0,
    turnover_rate: float = 3.0,
    last_price: float = 10.0,
    volume: int = 5_000_000,
):
    """构造满足港股活跃度条件的报价数据"""
    return {
        "change_pct": change_pct,
        "volume_ratio": volume_ratio,
        "turnover_rate": turnover_rate,
        "last_price": last_price,
        "cur_price": last_price,
        "volume": volume,
    }


# ── HotStockItem ────────────────────────────────────────────


class TestHotStockItem:
    def test_to_dict_contains_all_fields(self):
        item = HotStockItem(
            stock_code="HK.00700",
            stock_name="腾讯控股",
            market="HK",
            plate_code="BK001",
            plate_name="科技板块",
            last_price=350.0,
            change_pct=5.2,
            volume=1000000,
            volume_ratio=2.5,
            turnover_rate=3.1,
            heat_score=65.0,
        )
        d = item.to_dict()
        assert d["stock_code"] == "HK.00700"
        assert d["stock_name"] == "腾讯控股"
        assert d["market"] == "HK"
        assert d["plate_code"] == "BK001"
        assert d["heat_score"] == 65.0
        assert len(d) == 11  # 11 个字段

    def test_to_dict_roundtrip(self):
        item = HotStockItem(
            stock_code="US.AAPL", stock_name="Apple", market="US",
            plate_code="P1", plate_name="Tech", last_price=180.0,
            change_pct=2.0, volume=500000, volume_ratio=1.8,
            turnover_rate=1.5, heat_score=40.0,
        )
        d = item.to_dict()
        item2 = HotStockItem(**d)
        assert item == item2


# ── check_stock_activity ────────────────────────────────────


class TestCheckStockActivity:
    def test_hk_stock_passes(self):
        quote = {"volume": 600_000, "turnover_rate": 0.5, "cur_price": 2.0}
        assert HotStockFilter.check_stock_activity("HK.00700", quote) is True

    def test_hk_stock_low_volume_fails(self):
        quote = {"volume": 100_000, "turnover_rate": 0.5, "cur_price": 2.0}
        assert HotStockFilter.check_stock_activity("HK.00700", quote) is False

    def test_hk_stock_low_turnover_fails(self):
        quote = {"volume": 600_000, "turnover_rate": 0.05, "cur_price": 2.0}
        assert HotStockFilter.check_stock_activity("HK.00700", quote) is False

    def test_hk_stock_low_price_fails(self):
        quote = {"volume": 600_000, "turnover_rate": 0.5, "cur_price": 0.5}
        assert HotStockFilter.check_stock_activity("HK.00700", quote) is False

    def test_us_stock_passes(self):
        quote = {"volume": 5_000_000, "turnover_rate": 1.0}
        assert HotStockFilter.check_stock_activity("US.AAPL", quote) is True

    def test_us_stock_low_volume_fails(self):
        quote = {"volume": 1_000_000, "turnover_rate": 1.0}
        assert HotStockFilter.check_stock_activity("US.AAPL", quote) is False

    def test_us_no_price_check(self):
        """美股不检查价格门槛"""
        quote = {"volume": 5_000_000, "turnover_rate": 1.0, "cur_price": 0.01}
        assert HotStockFilter.check_stock_activity("US.AAPL", quote) is True

    def test_empty_quote_fails(self):
        assert HotStockFilter.check_stock_activity("HK.00700", {}) is False
        assert HotStockFilter.check_stock_activity("HK.00700", None) is False

    def test_custom_thresholds(self):
        quote = {"volume": 100, "turnover_rate": 0.01, "cur_price": 0.1}
        custom = {
            "min_volume_hk": 50, "min_turnover_rate_hk": 0.01, "min_price_hk": 0.1,
        }
        assert HotStockFilter.check_stock_activity("HK.00700", quote, custom) is True


# ── filter_hot_stocks ───────────────────────────────────────


class TestFilterHotStocks:
    def test_empty_stocks(self, hsf):
        result = hsf.filter_hot_stocks("P1", "板块1", [], {})
        assert result == []

    def test_no_quotes(self, hsf):
        stocks = [_make_stock("HK.S1"), _make_stock("HK.S2")]
        result = hsf.filter_hot_stocks("P1", "板块1", stocks, {})
        assert result == []

    def test_basic_filtering(self, hsf):
        """涨幅高于均值且量比>1.5的股票应被选中"""
        stocks = [_make_stock("HK.S1"), _make_stock("HK.S2"), _make_stock("HK.S3")]
        quotes = {
            "HK.S1": _make_quote(change_pct=8.0, volume_ratio=3.0),
            "HK.S2": _make_quote(change_pct=2.0, volume_ratio=0.5),
            "HK.S3": _make_quote(change_pct=5.0, volume_ratio=2.0),
        }
        # 平均涨幅 = (8+2+5)/3 = 5.0
        # S1: 8>5 且 3>1.5 → 选中
        # S2: 2<5 → 不选
        # S3: 5=5 不大于 → 不选
        result = hsf.filter_hot_stocks("P1", "板块1", stocks, quotes)
        assert len(result) == 1
        assert result[0].stock_code == "HK.S1"

    def test_activity_filter_removes_inactive(self, hsf):
        """不满足活跃度条件的股票应被预筛选过滤"""
        stocks = [_make_stock("HK.S1"), _make_stock("HK.S2")]
        quotes = {
            "HK.S1": _make_quote(change_pct=10.0, volume_ratio=3.0, volume=600_000),
            "HK.S2": _make_quote(change_pct=1.0, volume_ratio=2.0, volume=100),  # 成交量太低
        }
        # S2 被活跃度筛选过滤，只剩 S1，平均涨幅=10.0，S1 不大于均值 → 无结果
        result = hsf.filter_hot_stocks("P1", "板块1", stocks, quotes)
        assert len(result) == 0

    def test_volume_ratio_threshold(self, hsf):
        """量比不超过1.5的股票不应被选中"""
        stocks = [_make_stock("HK.S1"), _make_stock("HK.S2")]
        quotes = {
            "HK.S1": _make_quote(change_pct=10.0, volume_ratio=1.5),
            "HK.S2": _make_quote(change_pct=1.0, volume_ratio=3.0),
        }
        # 平均涨幅 = 5.5, S1: 10>5.5 但量比=1.5不大于1.5 → 不选
        result = hsf.filter_hot_stocks("P1", "板块1", stocks, quotes)
        assert len(result) == 0

    def test_max_per_plate_limit(self, hsf):
        """返回数量不超过 max_per_plate"""
        stocks = [_make_stock(f"HK.S{i}") for i in range(20)]
        quotes = {
            f"HK.S{i}": _make_quote(change_pct=float(i + 1), volume_ratio=2.0)
            for i in range(20)
        }
        result = hsf.filter_hot_stocks(
            "P1", "板块1", stocks, quotes, max_per_plate=10
        )
        assert len(result) <= 10

    def test_sorted_by_heat_score_desc(self, hsf):
        """结果应按评分降序排列"""
        stocks = [_make_stock(f"HK.S{i}") for i in range(5)]
        quotes = {
            "HK.S0": _make_quote(change_pct=2.0, volume_ratio=2.0),
            "HK.S1": _make_quote(change_pct=6.0, volume_ratio=2.0, turnover_rate=5.0),
            "HK.S2": _make_quote(change_pct=8.0, volume_ratio=3.0, turnover_rate=8.0),
            "HK.S3": _make_quote(change_pct=10.0, volume_ratio=4.0, turnover_rate=10.0),
            "HK.S4": _make_quote(change_pct=1.0, volume_ratio=2.0),
        }
        # 平均涨幅 = (2+6+8+10+1)/5 = 5.4
        result = hsf.filter_hot_stocks("P1", "板块1", stocks, quotes)
        assert len(result) >= 2
        for i in range(len(result) - 1):
            assert result[i].heat_score >= result[i + 1].heat_score

    def test_plate_info_propagated(self, hsf):
        """板块信息应正确传递到结果中"""
        stocks = [_make_stock("HK.S1"), _make_stock("HK.S2")]
        quotes = {
            "HK.S1": _make_quote(change_pct=10.0, volume_ratio=3.0),
            "HK.S2": _make_quote(change_pct=1.0, volume_ratio=2.0),
        }
        result = hsf.filter_hot_stocks("BK_TECH", "科技板块", stocks, quotes)
        for item in result:
            assert item.plate_code == "BK_TECH"
            assert item.plate_name == "科技板块"

    def test_fewer_than_min_still_returned(self, hsf):
        """满足条件的股票不足 min_per_plate 时，返回所有满足条件的"""
        stocks = [_make_stock("HK.S1"), _make_stock("HK.S2")]
        quotes = {
            "HK.S1": _make_quote(change_pct=10.0, volume_ratio=3.0),
            "HK.S2": _make_quote(change_pct=1.0, volume_ratio=0.5),
        }
        result = hsf.filter_hot_stocks(
            "P1", "板块1", stocks, quotes, min_per_plate=5
        )
        assert len(result) == 1


# ── get_all_hot_stocks ──────────────────────────────────────


class TestGetAllHotStocks:
    def test_empty_plates(self, hsf):
        result = hsf.get_all_hot_stocks([], {})
        assert result == {}

    def test_multiple_plates(self, hsf):
        plates = [
            {
                "plate_code": "P1",
                "plate_name": "板块1",
                "stocks": [_make_stock("HK.S1"), _make_stock("HK.S2")],
            },
            {
                "plate_code": "P2",
                "plate_name": "板块2",
                "stocks": [_make_stock("HK.S3"), _make_stock("HK.S4")],
            },
        ]
        quotes = {
            "HK.S1": _make_quote(change_pct=10.0, volume_ratio=3.0),
            "HK.S2": _make_quote(change_pct=1.0, volume_ratio=2.0),
            "HK.S3": _make_quote(change_pct=8.0, volume_ratio=2.5),
            "HK.S4": _make_quote(change_pct=2.0, volume_ratio=0.5),
        }
        result = hsf.get_all_hot_stocks(plates, quotes)
        assert "P1" in result
        assert "P2" in result
        assert result["P1"][0].stock_code == "HK.S1"
        assert result["P2"][0].stock_code == "HK.S3"

    def test_plate_with_no_qualifying_stocks_excluded(self, hsf):
        """没有满足条件股票的板块不应出现在结果中"""
        plates = [
            {
                "plate_code": "P1",
                "plate_name": "板块1",
                "stocks": [_make_stock("HK.S1"), _make_stock("HK.S2")],
            },
        ]
        quotes = {
            "HK.S1": _make_quote(change_pct=5.0, volume_ratio=2.0),
            "HK.S2": _make_quote(change_pct=5.0, volume_ratio=2.0),
        }
        result = hsf.get_all_hot_stocks(plates, quotes)
        assert "P1" not in result

    def test_plate_with_empty_stocks_skipped(self, hsf):
        plates = [{"plate_code": "P1", "plate_name": "板块1", "stocks": []}]
        result = hsf.get_all_hot_stocks(plates, {})
        assert result == {}
