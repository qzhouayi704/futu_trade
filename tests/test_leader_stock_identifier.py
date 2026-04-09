#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LeaderStockIdentifier 单元测试

验证龙头股识别器的核心逻辑：
- LeaderStockItem 数据类和 to_dict（price_position 修复）
- 市值过滤（港股>5亿港元，美股>5000万美元）
- 量比过滤（>2.0）
- 连续强势天数计算
- 价格位置计算
- identify_leaders 龙头识别流程
- get_all_leaders 全板块汇总
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.analysis.heat.heat_score_engine import HeatScoreEngine
from simple_trade.services.market_data.hot_stock.hot_stock_filter import HotStockItem
from simple_trade.services.market_data.hot_stock.leader_stock_identifier import (
    LeaderStockIdentifier,
    LeaderStockItem,
)


@pytest.fixture
def engine():
    return HeatScoreEngine()


@pytest.fixture
def identifier(engine):
    return LeaderStockIdentifier(score_engine=engine)


def _make_hot_stock(
    code: str, name: str = "", market: str = "HK",
    plate_code: str = "P1", plate_name: str = "板块1",
    change_pct: float = 5.0, volume_ratio: float = 3.0,
    turnover_rate: float = 3.0, last_price: float = 10.0,
    volume: int = 100000, heat_score: float = 50.0,
) -> HotStockItem:
    return HotStockItem(
        stock_code=code, stock_name=name or code, market=market,
        plate_code=plate_code, plate_name=plate_name,
        last_price=last_price, change_pct=change_pct,
        volume=volume, volume_ratio=volume_ratio,
        turnover_rate=turnover_rate, heat_score=heat_score,
    )


def _make_quote(
    change_pct: float = 5.0, volume_ratio: float = 3.0,
    turnover_rate: float = 3.0, last_price: float = 10.0,
    volume: int = 100000, market: str = "HK",
    market_cap: float = 1_000_000_000,
):
    return {
        "change_pct": change_pct, "volume_ratio": volume_ratio,
        "turnover_rate": turnover_rate, "last_price": last_price,
        "volume": volume, "market": market, "market_cap": market_cap,
    }


def _make_kline(days: int = 5, base_open: float = 10.0, daily_gain: float = 0.5):
    """生成 K 线数据，每天涨 daily_gain"""
    records = []
    for i in range(days):
        o = base_open + i * daily_gain
        c = o + daily_gain  # 收盘 > 开盘 → 强势
        records.append({
            "time_key": f"2024-01-{days - i:02d}",
            "open_price": o, "close_price": c,
            "high_price": c + 0.5, "low_price": o - 0.5,
            "volume": 100000, "turnover": 1000000,
        })
    return records


# ── LeaderStockItem ─────────────────────────────────────────


class TestLeaderStockItem:
    def test_to_dict_valid_price_position(self):
        item = LeaderStockItem(
            stock_code="00700", stock_name="腾讯", market="HK",
            plate_code="P1", plate_name="科技", last_price=350.0,
            change_pct=5.0, volume=1000000, volume_ratio=3.0,
            turnover_rate=3.0, price_position=75.0, heat_score=60.0,
            leader_score=80.0, leader_rank=1,
            consecutive_strong_days=3, market_cap=3_000_000_000_000,
        )
        d = item.to_dict()
        assert d["price_position"] == 75.0
        assert d["leader_score"] == 80.0

    def test_to_dict_negative_price_position_fixed(self):
        """price_position 为 -1 时，to_dict 应返回 50.0"""
        item = LeaderStockItem(
            stock_code="00700", stock_name="腾讯", market="HK",
            plate_code="P1", plate_name="科技", last_price=350.0,
            change_pct=5.0, volume=1000000, volume_ratio=3.0,
            turnover_rate=3.0, price_position=-1.0, heat_score=60.0,
            leader_score=80.0, leader_rank=1,
            consecutive_strong_days=3, market_cap=3_000_000_000_000,
        )
        d = item.to_dict()
        assert d["price_position"] == 50.0

    def test_to_dict_none_price_position_fixed(self):
        """price_position 为 None 时，to_dict 应返回 50.0"""
        item = LeaderStockItem(
            stock_code="00700", stock_name="腾讯", market="HK",
            plate_code="P1", plate_name="科技", last_price=350.0,
            change_pct=5.0, volume=1000000, volume_ratio=3.0,
            turnover_rate=3.0, price_position=None, heat_score=60.0,
            leader_score=80.0, leader_rank=1,
            consecutive_strong_days=3, market_cap=3_000_000_000_000,
        )
        d = item.to_dict()
        assert d["price_position"] == 50.0


# ── _check_market_cap ───────────────────────────────────────


class TestCheckMarketCap:
    def test_hk_above_threshold(self, identifier):
        quote = _make_quote(market="HK", market_cap=600_000_000)
        assert identifier._check_market_cap("00700", quote) is True

    def test_hk_at_threshold_excluded(self, identifier):
        """港股市值恰好等于 5 亿应被排除"""
        quote = _make_quote(market="HK", market_cap=500_000_000)
        assert identifier._check_market_cap("00700", quote) is False

    def test_hk_below_threshold(self, identifier):
        quote = _make_quote(market="HK", market_cap=100_000_000)
        assert identifier._check_market_cap("00700", quote) is False

    def test_us_above_threshold(self, identifier):
        quote = _make_quote(market="US", market_cap=60_000_000)
        assert identifier._check_market_cap("AAPL", quote) is True

    def test_us_at_threshold_excluded(self, identifier):
        """美股市值恰好等于 5000 万应被排除"""
        quote = _make_quote(market="US", market_cap=50_000_000)
        assert identifier._check_market_cap("AAPL", quote) is False

    def test_market_cap_none_excluded(self, identifier):
        """市值数据不可用时排除"""
        quote = {"market": "HK"}
        assert identifier._check_market_cap("00700", quote) is False

    def test_market_cap_zero_excluded(self, identifier):
        quote = _make_quote(market="HK", market_cap=0)
        assert identifier._check_market_cap("00700", quote) is False

    def test_no_market_cap_upper_limit(self, identifier):
        """不设市值上限"""
        quote = _make_quote(market="HK", market_cap=999_999_999_999)
        assert identifier._check_market_cap("00700", quote) is True

    def test_circulation_market_cap_fallback(self, identifier):
        """支持 circulation_market_cap 字段"""
        quote = {"market": "HK", "circulation_market_cap": 600_000_000}
        assert identifier._check_market_cap("00700", quote) is True


# ── _calculate_consecutive_strong_days ──────────────────────


class TestConsecutiveStrongDays:
    def test_all_strong(self, identifier):
        kline = _make_kline(days=5, daily_gain=0.5)
        result = identifier._calculate_consecutive_strong_days("S1", {"S1": kline})
        assert result == 5

    def test_no_kline_data(self, identifier):
        result = identifier._calculate_consecutive_strong_days("S1", {})
        assert result == 0

    def test_first_day_weak(self, identifier):
        """最近一天涨幅 <= 0，连续强势天数为 0"""
        kline = [
            {"time_key": "2024-01-05", "open_price": 10.0, "close_price": 9.5,
             "high_price": 10.5, "low_price": 9.0, "volume": 100000},
        ]
        result = identifier._calculate_consecutive_strong_days("S1", {"S1": kline})
        assert result == 0

    def test_partial_strong(self, identifier):
        """前 2 天强势，第 3 天弱势"""
        kline = [
            {"time_key": "2024-01-05", "open_price": 10.0, "close_price": 11.0,
             "high_price": 11.5, "low_price": 9.5, "volume": 100000},
            {"time_key": "2024-01-04", "open_price": 9.0, "close_price": 10.0,
             "high_price": 10.5, "low_price": 8.5, "volume": 100000},
            {"time_key": "2024-01-03", "open_price": 9.5, "close_price": 9.0,
             "high_price": 10.0, "low_price": 8.5, "volume": 100000},
        ]
        result = identifier._calculate_consecutive_strong_days("S1", {"S1": kline})
        assert result == 2


# ── _calculate_price_position ───────────────────────────────


class TestPricePosition:
    def test_normal_calculation(self, identifier):
        quote = {"last_price": 15.0}
        kline = [
            {"high_price": 20.0, "low_price": 10.0},
            {"high_price": 18.0, "low_price": 12.0},
        ]
        # (15 - 10) / (20 - 10) * 100 = 50.0
        result = identifier._calculate_price_position("S1", quote, kline)
        assert result == 50.0

    def test_max_equals_min(self, identifier):
        quote = {"last_price": 10.0}
        kline = [{"high_price": 10.0, "low_price": 10.0}]
        result = identifier._calculate_price_position("S1", quote, kline)
        assert result == 50.0

    def test_no_kline_returns_negative(self, identifier):
        result = identifier._calculate_price_position("S1", {"last_price": 10.0}, [])
        assert result == -1.0

    def test_no_price_returns_negative(self, identifier):
        kline = [{"high_price": 20.0, "low_price": 10.0}]
        result = identifier._calculate_price_position("S1", {}, kline)
        assert result == -1.0

    def test_at_high(self, identifier):
        quote = {"last_price": 20.0}
        kline = [{"high_price": 20.0, "low_price": 10.0}]
        result = identifier._calculate_price_position("S1", quote, kline)
        assert result == 100.0

    def test_at_low(self, identifier):
        quote = {"last_price": 10.0}
        kline = [{"high_price": 20.0, "low_price": 10.0}]
        result = identifier._calculate_price_position("S1", quote, kline)
        assert result == 0.0


# ── identify_leaders ────────────────────────────────────────


class TestIdentifyLeaders:
    def test_empty_hot_stocks(self, identifier):
        result = identifier.identify_leaders([], "P1", "板块1")
        assert result == []

    def test_all_market_cap_fail(self, identifier):
        """所有股票市值不达标时返回空列表"""
        stocks = [_make_hot_stock("S1"), _make_hot_stock("S2")]
        quotes = {
            "S1": _make_quote(market_cap=100_000_000),  # 低于 5 亿
            "S2": _make_quote(market_cap=200_000_000),
        }
        result = identifier.identify_leaders(stocks, "P1", "板块1", quotes_map=quotes)
        assert result == []

    def test_all_volume_ratio_fail(self, identifier):
        """所有股票量比不达标时返回空列表"""
        stocks = [
            _make_hot_stock("S1", volume_ratio=1.5),
            _make_hot_stock("S2", volume_ratio=1.8),
        ]
        quotes = {
            "S1": _make_quote(market_cap=1_000_000_000, volume_ratio=1.5),
            "S2": _make_quote(market_cap=1_000_000_000, volume_ratio=1.8),
        }
        result = identifier.identify_leaders(stocks, "P1", "板块1", quotes_map=quotes)
        assert result == []

    def test_successful_identification(self, identifier):
        """正常识别龙头股"""
        stocks = [
            _make_hot_stock("S1", change_pct=10.0, volume_ratio=4.0),
            _make_hot_stock("S2", change_pct=8.0, volume_ratio=3.0),
            _make_hot_stock("S3", change_pct=6.0, volume_ratio=2.5),
        ]
        quotes = {
            "S1": _make_quote(change_pct=10.0, market_cap=1_000_000_000),
            "S2": _make_quote(change_pct=8.0, market_cap=800_000_000),
            "S3": _make_quote(change_pct=6.0, market_cap=600_000_000),
        }
        result = identifier.identify_leaders(
            stocks, "P1", "板块1", quotes_map=quotes, max_per_plate=2
        )
        assert 0 < len(result) <= 2
        # 应按龙头评分降序
        if len(result) == 2:
            assert result[0].leader_score >= result[1].leader_score

    def test_max_per_plate_respected(self, identifier):
        """返回数量不超过 max_per_plate"""
        stocks = [
            _make_hot_stock(f"S{i}", change_pct=10.0 - i, volume_ratio=3.0)
            for i in range(5)
        ]
        quotes = {
            f"S{i}": _make_quote(market_cap=1_000_000_000)
            for i in range(5)
        }
        result = identifier.identify_leaders(
            stocks, "P1", "板块1", quotes_map=quotes, max_per_plate=2
        )
        assert len(result) <= 2

    def test_leader_rank_assigned(self, identifier):
        """龙头排名应正确赋值"""
        stocks = [
            _make_hot_stock("S1", change_pct=10.0, volume_ratio=4.0),
            _make_hot_stock("S2", change_pct=8.0, volume_ratio=3.0),
        ]
        quotes = {
            "S1": _make_quote(market_cap=1_000_000_000),
            "S2": _make_quote(market_cap=800_000_000),
        }
        result = identifier.identify_leaders(
            stocks, "P1", "板块1", quotes_map=quotes, max_per_plate=2
        )
        for idx, item in enumerate(result, start=1):
            assert item.leader_rank == idx

    def test_strict_conditions_no_compromise(self, identifier):
        """不满足严格条件时返回空列表，不降低标准"""
        stocks = [_make_hot_stock("S1", volume_ratio=1.0)]  # 量比不达标
        quotes = {"S1": _make_quote(market_cap=1_000_000_000)}
        result = identifier.identify_leaders(stocks, "P1", "板块1", quotes_map=quotes)
        assert result == []


# ── get_all_leaders ─────────────────────────────────────────


class TestGetAllLeaders:
    def test_empty_input(self, identifier):
        result = identifier.get_all_leaders({})
        assert result == []

    def test_multiple_plates(self, identifier):
        hot_by_plate = {
            "P1": [
                _make_hot_stock("S1", plate_code="P1", plate_name="板块1",
                                change_pct=10.0, volume_ratio=4.0),
            ],
            "P2": [
                _make_hot_stock("S2", plate_code="P2", plate_name="板块2",
                                change_pct=8.0, volume_ratio=3.0),
            ],
        }
        quotes = {
            "S1": _make_quote(market_cap=1_000_000_000),
            "S2": _make_quote(market_cap=800_000_000),
        }
        result = identifier.get_all_leaders(hot_by_plate, quotes_map=quotes, max_total=10)
        assert len(result) <= 10
        # 全局按龙头评分降序
        for i in range(len(result) - 1):
            assert result[i].leader_score >= result[i + 1].leader_score

    def test_max_total_respected(self, identifier):
        hot_by_plate = {}
        for p in range(5):
            plate_code = f"P{p}"
            hot_by_plate[plate_code] = [
                _make_hot_stock(
                    f"S{p}_{i}", plate_code=plate_code,
                    plate_name=f"板块{p}", change_pct=10.0 - i,
                    volume_ratio=3.0,
                )
                for i in range(3)
            ]
        quotes = {
            f"S{p}_{i}": _make_quote(market_cap=1_000_000_000)
            for p in range(5) for i in range(3)
        }
        result = identifier.get_all_leaders(hot_by_plate, quotes_map=quotes, max_total=3)
        assert len(result) <= 3
