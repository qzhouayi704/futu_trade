#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LeaderStockIdentifier 属性测试

使用 hypothesis 验证龙头股识别器的核心正确性属性：
- Property 4: 龙头股严格条件满足性
- Property 9: 龙头股数据完整性
"""

import math
import os
import sys

import pytest
from hypothesis import given, settings, strategies as st, assume

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.analysis.heat.heat_score_engine import HeatScoreEngine
from simple_trade.services.market_data.hot_stock.hot_stock_filter import HotStockItem
from simple_trade.services.market_data.hot_stock.leader_stock_identifier import (
    LeaderStockIdentifier,
    LeaderStockItem,
)


# ── hypothesis 策略 ──────────────────────────────────────────────

# 涨跌幅（正值，龙头股通常是上涨的）
change_pct_st = st.floats(min_value=0.1, max_value=30.0, allow_nan=False, allow_infinity=False)

# 量比（覆盖低于和高于 2.0 的情况）
volume_ratio_st = st.floats(min_value=0.5, max_value=15.0, allow_nan=False, allow_infinity=False)

# 换手率
turnover_rate_st = st.floats(min_value=0.1, max_value=50.0, allow_nan=False, allow_infinity=False)

# 价格
price_st = st.floats(min_value=0.1, max_value=5000.0, allow_nan=False, allow_infinity=False)

# 成交量
volume_st = st.integers(min_value=100, max_value=10_000_000)

# 市值（覆盖达标和不达标的情况）
# 港股阈值 500_000_000，美股阈值 50_000_000
market_cap_st = st.floats(min_value=1_000_000, max_value=10_000_000_000, allow_nan=False, allow_infinity=False)

# 市场类型
market_st = st.sampled_from(["HK", "US"])


@st.composite
def hot_stock_item_strategy(draw, market=None, plate_code="PLATE_001", plate_name="测试板块"):
    """生成单个 HotStockItem"""
    idx = draw(st.integers(min_value=0, max_value=9999))
    m = market or draw(market_st)
    code = f"{m}.STOCK_{idx:04d}"

    engine = HeatScoreEngine()
    change = draw(change_pct_st)
    vr = draw(volume_ratio_st)
    tr = draw(turnover_rate_st)
    score = engine.calculate_base_score(change, vr, tr)

    return HotStockItem(
        stock_code=code,
        stock_name=f"Stock {idx}",
        market=m,
        plate_code=plate_code,
        plate_name=plate_name,
        last_price=draw(price_st),
        change_pct=change,
        volume=draw(volume_st),
        volume_ratio=vr,
        turnover_rate=tr,
        heat_score=score,
    )


@st.composite
def quote_for_stock_strategy(draw, stock_code, market):
    """为指定股票生成报价数据（含市值）"""
    return {
        "stock_code": stock_code,
        "market": market,
        "last_price": draw(price_st),
        "change_pct": draw(change_pct_st),
        "volume_ratio": draw(volume_ratio_st),
        "turnover_rate": draw(turnover_rate_st),
        "volume": draw(volume_st),
        "market_cap": draw(market_cap_st),
        "net_inflow_ratio": draw(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
        ),
    }


@st.composite
def kline_record_strategy(draw):
    """生成单条 K 线记录"""
    base_price = draw(st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
    # 开盘价
    open_price = base_price
    # 收盘价在开盘价附近波动
    close_price = base_price * draw(
        st.floats(min_value=0.9, max_value=1.15, allow_nan=False, allow_infinity=False)
    )
    high_price = max(open_price, close_price) * draw(
        st.floats(min_value=1.0, max_value=1.05, allow_nan=False, allow_infinity=False)
    )
    low_price = min(open_price, close_price) * draw(
        st.floats(min_value=0.95, max_value=1.0, allow_nan=False, allow_infinity=False)
    )

    return {
        "time_key": f"2025-01-{draw(st.integers(min_value=1, max_value=28)):02d}",
        "open_price": round(open_price, 2),
        "close_price": round(close_price, 2),
        "high_price": round(high_price, 2),
        "low_price": round(low_price, 2),
        "volume": draw(st.integers(min_value=1000, max_value=10_000_000)),
        "turnover": draw(st.floats(min_value=10000, max_value=1e9, allow_nan=False, allow_infinity=False)),
    }


@st.composite
def leader_test_data_strategy(draw):
    """生成完整的龙头股识别测试数据

    包含：热门股票列表、报价字典、K 线数据字典
    确保部分股票满足龙头条件（量比>2.0、市值达标）
    """
    market = draw(market_st)
    plate_code = "PLATE_001"
    plate_name = "测试板块"
    n_stocks = draw(st.integers(min_value=1, max_value=20))

    hot_stocks = []
    quotes_map = {}
    kline_data = {}

    for i in range(n_stocks):
        code = f"{market}.STOCK_{i:04d}"
        change = draw(change_pct_st)
        vr = draw(volume_ratio_st)
        tr = draw(turnover_rate_st)
        price = draw(price_st)

        engine = HeatScoreEngine()
        score = engine.calculate_base_score(change, vr, tr)

        hot_stocks.append(HotStockItem(
            stock_code=code,
            stock_name=f"Stock {i}",
            market=market,
            plate_code=plate_code,
            plate_name=plate_name,
            last_price=price,
            change_pct=change,
            volume=draw(volume_st),
            volume_ratio=vr,
            turnover_rate=tr,
            heat_score=score,
        ))

        # 生成报价（含市值）
        cap = draw(market_cap_st)
        quotes_map[code] = {
            "stock_code": code,
            "market": market,
            "last_price": price,
            "change_pct": change,
            "volume_ratio": vr,
            "turnover_rate": tr,
            "volume": hot_stocks[-1].volume,
            "market_cap": cap,
            "net_inflow_ratio": draw(
                st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
            ),
        }

        # 生成 K 线数据（1-30 条）
        n_klines = draw(st.integers(min_value=1, max_value=30))
        kline_data[code] = [draw(kline_record_strategy()) for _ in range(n_klines)]

    return hot_stocks, quotes_map, kline_data, plate_code, plate_name, market


# ── Property 4: 龙头股严格条件满足性 ────────────────────────────
# Feature: enhanced-heat-optimization, Property 4: 龙头股严格条件满足性
# **Validates: Requirements 3.3, 3.4, 9.1, 9.2**


class TestProperty4LeaderStockStrictConditions:
    """Property 4: 对于任意热门股票列表和 K 线数据，龙头股识别器返回的
    每只龙头股都应满足：涨幅排名在板块内 top 2、量比大于 2.0、
    市值达标（港股>5亿港元，美股>5000万美元）；返回数量应在 0-2 只范围内。"""

    @given(data=leader_test_data_strategy())
    @settings(max_examples=200)
    def test_leader_count_within_range(self, data):
        """返回数量应在 0-2 只范围内（max_per_plate 默认值为 2）"""
        hot_stocks, quotes_map, kline_data, plate_code, plate_name, market = data
        engine = HeatScoreEngine()
        identifier = LeaderStockIdentifier(score_engine=engine)

        result = identifier.identify_leaders(
            hot_stocks=hot_stocks,
            plate_code=plate_code,
            plate_name=plate_name,
            kline_data=kline_data,
            quotes_map=quotes_map,
            max_per_plate=2,
        )

        assert 0 <= len(result) <= 2, (
            f"返回数量 {len(result)} 不在 [0, 2] 范围内"
        )

    @given(data=leader_test_data_strategy())
    @settings(max_examples=200)
    def test_every_leader_volume_ratio_above_threshold(self, data):
        """每只龙头股的量比应大于 2.0"""
        hot_stocks, quotes_map, kline_data, plate_code, plate_name, market = data
        engine = HeatScoreEngine()
        identifier = LeaderStockIdentifier(score_engine=engine)

        result = identifier.identify_leaders(
            hot_stocks=hot_stocks,
            plate_code=plate_code,
            plate_name=plate_name,
            kline_data=kline_data,
            quotes_map=quotes_map,
            max_per_plate=2,
        )

        for item in result:
            assert item.volume_ratio > 2.0, (
                f"龙头股 {item.stock_code} 量比 {item.volume_ratio} 不大于 2.0"
            )

    @given(data=leader_test_data_strategy())
    @settings(max_examples=200)
    def test_every_leader_market_cap_meets_threshold(self, data):
        """每只龙头股的市值应达标：港股>5亿港元，美股>5000万美元"""
        hot_stocks, quotes_map, kline_data, plate_code, plate_name, market = data
        engine = HeatScoreEngine()
        identifier = LeaderStockIdentifier(score_engine=engine)

        result = identifier.identify_leaders(
            hot_stocks=hot_stocks,
            plate_code=plate_code,
            plate_name=plate_name,
            kline_data=kline_data,
            quotes_map=quotes_map,
            max_per_plate=2,
        )

        for item in result:
            quote = quotes_map.get(item.stock_code, {})
            cap = quote.get("market_cap", 0)
            if "HK" in market.upper():
                assert cap > 500_000_000, (
                    f"港股龙头 {item.stock_code} 市值 {cap} 不大于 5 亿港元"
                )
            elif "US" in market.upper():
                assert cap > 50_000_000, (
                    f"美股龙头 {item.stock_code} 市值 {cap} 不大于 5000 万美元"
                )

    @given(data=leader_test_data_strategy())
    @settings(max_examples=200)
    def test_every_leader_change_pct_in_top_candidates(self, data):
        """每只龙头股的涨幅应在市值过滤后的候选中排名靠前

        实现逻辑：先市值过滤，再按涨幅排序取 top candidate_count（默认 4），
        然后量比过滤。所以龙头股的涨幅应在市值过滤后的 top 4 中。
        """
        hot_stocks, quotes_map, kline_data, plate_code, plate_name, market = data
        engine = HeatScoreEngine()
        identifier = LeaderStockIdentifier(score_engine=engine)

        result = identifier.identify_leaders(
            hot_stocks=hot_stocks,
            plate_code=plate_code,
            plate_name=plate_name,
            kline_data=kline_data,
            quotes_map=quotes_map,
            max_per_plate=2,
        )

        if not result:
            return

        # 模拟市值过滤
        cap_filtered = []
        for stock in hot_stocks:
            quote = quotes_map.get(stock.stock_code, {})
            if identifier._check_market_cap(stock.stock_code, quote):
                cap_filtered.append(stock)

        # 按涨幅降序排序
        cap_filtered.sort(key=lambda x: x.change_pct, reverse=True)
        # 候选数量 = max_per_plate * candidate_multiplier = 2 * 2 = 4
        candidate_count = 2 * identifier.candidate_multiplier
        candidate_codes = {s.stock_code for s in cap_filtered[:candidate_count]}

        for item in result:
            assert item.stock_code in candidate_codes, (
                f"龙头股 {item.stock_code} 不在涨幅 top {candidate_count} 候选中"
            )


# ── Property 9: 龙头股数据完整性 ────────────────────────────────
# Feature: enhanced-heat-optimization, Property 9: 龙头股数据完整性
# **Validates: Requirements 6.1**


class TestProperty9LeaderStockDataIntegrity:
    """Property 9: 对于任意龙头股识别结果，to_dict() 返回的字典中
    price_position 字段应存在且为有效数值（非 NaN、非 None），
    值在 0-100 范围内。"""

    @given(data=leader_test_data_strategy())
    @settings(max_examples=200)
    def test_to_dict_price_position_exists_and_valid(self, data):
        """to_dict() 中 price_position 应存在、非 None、非 NaN、在 0-100 范围内"""
        hot_stocks, quotes_map, kline_data, plate_code, plate_name, market = data
        engine = HeatScoreEngine()
        identifier = LeaderStockIdentifier(score_engine=engine)

        result = identifier.identify_leaders(
            hot_stocks=hot_stocks,
            plate_code=plate_code,
            plate_name=plate_name,
            kline_data=kline_data,
            quotes_map=quotes_map,
            max_per_plate=2,
        )

        for item in result:
            d = item.to_dict()
            pp = d.get("price_position")

            # 字段必须存在
            assert "price_position" in d, (
                f"龙头股 {item.stock_code} to_dict() 缺少 price_position 字段"
            )

            # 非 None
            assert pp is not None, (
                f"龙头股 {item.stock_code} price_position 为 None"
            )

            # 非 NaN
            assert not math.isnan(pp), (
                f"龙头股 {item.stock_code} price_position 为 NaN"
            )

            # 在 0-100 范围内
            assert 0.0 <= pp <= 100.0, (
                f"龙头股 {item.stock_code} price_position={pp} 不在 [0, 100] 范围内"
            )

    @given(data=leader_test_data_strategy())
    @settings(max_examples=200)
    def test_to_dict_price_position_replaces_invalid_with_default(self, data):
        """当原始 price_position 为 -1（不可用）时，to_dict() 应替换为 50.0"""
        hot_stocks, quotes_map, kline_data, plate_code, plate_name, market = data
        engine = HeatScoreEngine()
        identifier = LeaderStockIdentifier(score_engine=engine)

        result = identifier.identify_leaders(
            hot_stocks=hot_stocks,
            plate_code=plate_code,
            plate_name=plate_name,
            kline_data=kline_data,
            quotes_map=quotes_map,
            max_per_plate=2,
        )

        for item in result:
            # 如果原始值为 -1（不可用），to_dict 应替换为 50.0
            if item.price_position < 0:
                d = item.to_dict()
                assert d["price_position"] == 50.0, (
                    f"龙头股 {item.stock_code} 原始 price_position={item.price_position}，"
                    f"to_dict() 应替换为 50.0，实际为 {d['price_position']}"
                )

    @given(
        price_position=st.one_of(
            st.just(None),
            st.just(-1.0),
            st.just(-0.5),
        )
    )
    @settings(max_examples=50)
    def test_leader_stock_item_to_dict_fixes_invalid_price_position(self, price_position):
        """直接构造 LeaderStockItem，验证 to_dict() 对无效 price_position 的修复"""
        item = LeaderStockItem(
            stock_code="HK.00700",
            stock_name="腾讯控股",
            market="HK",
            plate_code="PLATE_001",
            plate_name="互联网",
            last_price=350.0,
            change_pct=5.0,
            volume=1000000,
            volume_ratio=3.0,
            turnover_rate=2.5,
            price_position=price_position,
            heat_score=80.0,
            leader_score=75.0,
            leader_rank=1,
            consecutive_strong_days=3,
            market_cap=3_000_000_000_000,
        )

        d = item.to_dict()
        pp = d["price_position"]

        assert pp is not None, "price_position 不应为 None"
        assert not math.isnan(pp), "price_position 不应为 NaN"
        assert 0.0 <= pp <= 100.0, f"price_position={pp} 不在 [0, 100] 范围内"
        assert pp == 50.0, f"无效 price_position 应替换为 50.0，实际为 {pp}"
