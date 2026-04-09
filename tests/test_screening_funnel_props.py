#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
筛选漏斗属性测试

验证筛选流程各级数量单调递减：
- Property 10: 筛选漏斗单调递减
"""

import os
import sys

import pytest
from hypothesis import given, settings, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.analysis.heat.heat_score_engine import HeatScoreEngine
from simple_trade.services.market_data.hot_stock.hot_stock_filter import (
    HotStockFilter,
)
from simple_trade.services.market_data.hot_stock.leader_stock_identifier import (
    LeaderStockIdentifier,
)


# ── hypothesis 策略 ──────────────────────────────────────────────

market_st = st.sampled_from(["HK", "US"])

price_st = st.floats(
    min_value=0.1, max_value=5000.0, allow_nan=False, allow_infinity=False
)
change_pct_st = st.floats(
    min_value=-10.0, max_value=30.0, allow_nan=False, allow_infinity=False
)
volume_ratio_st = st.floats(
    min_value=0.1, max_value=15.0, allow_nan=False, allow_infinity=False
)
turnover_rate_st = st.floats(
    min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False
)
volume_st = st.integers(min_value=0, max_value=10_000_000)
market_cap_st = st.floats(
    min_value=1_000_000, max_value=10_000_000_000,
    allow_nan=False, allow_infinity=False,
)


@st.composite
def stock_with_quote_strategy(draw, market, plate_code, idx):
    """生成一只股票及其报价数据

    部分股票无报价（模拟不活跃），部分成交量为 0。
    """
    code = f"{market}.STOCK_{idx:04d}"
    has_quote = draw(st.booleans())  # 约 50% 有报价

    stock = {
        "stock_code": code,
        "stock_name": f"Stock {idx}",
        "market": market,
    }

    if not has_quote:
        return stock, None

    vol = draw(volume_st)
    quote = {
        "stock_code": code,
        "market": market,
        "last_price": draw(price_st),
        "change_pct": draw(change_pct_st),
        "volume_ratio": draw(volume_ratio_st),
        "turnover_rate": draw(turnover_rate_st),
        "volume": vol,
        "market_cap": draw(market_cap_st),
        "net_inflow_ratio": draw(
            st.floats(min_value=0.0, max_value=1.0,
                       allow_nan=False, allow_infinity=False)
        ),
    }
    return stock, quote


@st.composite
def kline_record_strategy(draw):
    """生成单条 K 线记录"""
    base = draw(st.floats(
        min_value=1.0, max_value=1000.0,
        allow_nan=False, allow_infinity=False,
    ))
    close = base * draw(st.floats(
        min_value=0.9, max_value=1.15,
        allow_nan=False, allow_infinity=False,
    ))
    return {
        "time_key": f"2025-01-{draw(st.integers(min_value=1, max_value=28)):02d}",
        "open_price": round(base, 2),
        "close_price": round(close, 2),
        "high_price": round(max(base, close) * 1.02, 2),
        "low_price": round(min(base, close) * 0.98, 2),
        "volume": draw(st.integers(min_value=1000, max_value=10_000_000)),
        "turnover": draw(st.floats(
            min_value=10000, max_value=1e9,
            allow_nan=False, allow_infinity=False,
        )),
    }


@st.composite
def screening_funnel_data_strategy(draw):
    """生成完整的筛选漏斗测试数据

    模拟 1-3 个板块，每板块 5-20 只股票。
    部分股票无报价（不活跃），部分成交量为 0。
    """
    market = draw(market_st)
    n_plates = draw(st.integers(min_value=1, max_value=3))

    plates_data = []
    quotes_map = {}
    kline_data = {}
    all_stocks_flat = []  # 所有股票（含无报价的）

    stock_idx = 0
    for p in range(n_plates):
        plate_code = f"PLATE_{p:03d}"
        plate_name = f"板块{p}"
        n_stocks = draw(st.integers(min_value=5, max_value=20))

        plate_stocks = []
        for _ in range(n_stocks):
            stock, quote = draw(
                stock_with_quote_strategy(market, plate_code, stock_idx)
            )
            plate_stocks.append(stock)
            all_stocks_flat.append(stock)

            if quote is not None:
                quotes_map[stock["stock_code"]] = quote
                # 为有报价的股票生成 K 线
                n_klines = draw(st.integers(min_value=0, max_value=10))
                if n_klines > 0:
                    kline_data[stock["stock_code"]] = [
                        draw(kline_record_strategy()) for _ in range(n_klines)
                    ]

            stock_idx += 1

        plates_data.append({
            "plate_code": plate_code,
            "plate_name": plate_name,
            "stocks": plate_stocks,
        })

    return plates_data, quotes_map, kline_data, market, all_stocks_flat


def _count_active_stocks(
    plates_data: list, quotes_map: dict
) -> int:
    """统计活跃股票数：有报价且成交量 > 0"""
    active = set()
    for plate in plates_data:
        for stock in plate.get("stocks", []):
            code = stock["stock_code"]
            quote = quotes_map.get(code)
            if quote and quote.get("volume", 0) > 0:
                active.add(code)
    return len(active)


# ── Property 10: 筛选漏斗单调递减 ───────────────────────────────
# Feature: enhanced-heat-optimization, Property 10: 筛选漏斗单调递减
# **Validates: Requirements 8.3**


class TestProperty10ScreeningFunnelMonotonic:
    """Property 10: 对于任意筛选流程执行结果，各级筛选的数量统计应满足：
    活跃股票数 >= 热门股票数 >= 龙头股数。"""

    @given(data=screening_funnel_data_strategy())
    @settings(max_examples=200)
    def test_total_gte_active(self, data):
        """全部股票数 >= 活跃股票数"""
        plates_data, quotes_map, _, _, all_stocks_flat = data

        total_count = len(all_stocks_flat)
        active_count = _count_active_stocks(plates_data, quotes_map)

        assert total_count >= active_count, (
            f"total({total_count}) < active({active_count})"
        )

    @given(data=screening_funnel_data_strategy())
    @settings(max_examples=200)
    def test_active_gte_hot(self, data):
        """活跃股票数 >= 热门股票数"""
        plates_data, quotes_map, _, _, _ = data

        engine = HeatScoreEngine()
        hot_filter = HotStockFilter(score_engine=engine)

        active_count = _count_active_stocks(plates_data, quotes_map)
        hot_stocks_by_plate = hot_filter.get_all_hot_stocks(
            plates_data, quotes_map
        )
        hot_count = sum(len(v) for v in hot_stocks_by_plate.values())

        assert active_count >= hot_count, (
            f"active({active_count}) < hot({hot_count})"
        )

    @given(data=screening_funnel_data_strategy())
    @settings(max_examples=200)
    def test_hot_gte_leader(self, data):
        """热门股票数 >= 龙头股数"""
        plates_data, quotes_map, kline_data, _, _ = data

        engine = HeatScoreEngine()
        hot_filter = HotStockFilter(score_engine=engine)
        identifier = LeaderStockIdentifier(score_engine=engine)

        hot_stocks_by_plate = hot_filter.get_all_hot_stocks(
            plates_data, quotes_map
        )
        hot_count = sum(len(v) for v in hot_stocks_by_plate.values())

        leaders = identifier.get_all_leaders(
            hot_stocks_by_plate=hot_stocks_by_plate,
            kline_data=kline_data,
            quotes_map=quotes_map,
        )
        leader_count = len(leaders)

        assert hot_count >= leader_count, (
            f"hot({hot_count}) < leader({leader_count})"
        )

    @given(data=screening_funnel_data_strategy())
    @settings(max_examples=200)
    def test_full_funnel_monotonic(self, data):
        """完整漏斗：total >= active >= hot >= leader"""
        plates_data, quotes_map, kline_data, _, all_stocks_flat = data

        engine = HeatScoreEngine()
        hot_filter = HotStockFilter(score_engine=engine)
        identifier = LeaderStockIdentifier(score_engine=engine)

        total_count = len(all_stocks_flat)
        active_count = _count_active_stocks(plates_data, quotes_map)

        hot_stocks_by_plate = hot_filter.get_all_hot_stocks(
            plates_data, quotes_map
        )
        hot_count = sum(len(v) for v in hot_stocks_by_plate.values())

        leaders = identifier.get_all_leaders(
            hot_stocks_by_plate=hot_stocks_by_plate,
            kline_data=kline_data,
            quotes_map=quotes_map,
        )
        leader_count = len(leaders)

        assert total_count >= active_count >= hot_count >= leader_count, (
            f"漏斗不单调递减: total={total_count}, active={active_count}, "
            f"hot={hot_count}, leader={leader_count}"
        )
