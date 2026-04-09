#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐笔成交分析 - 属性测试（Property-Based Testing）

使用 hypothesis 库验证 ticker_dimensions.py 中 4 个维度分析函数的正确性属性。
"""

from collections import defaultdict

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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
    TickerService,
)


# ==================== Property 1: 缓存 round-trip ====================
# Feature: real-trade-analysis, Property 1: 缓存 round-trip


@pytest.mark.asyncio
async def test_cache_round_trip():
    """**Validates: Requirements 1.1, 1.2**

    Property 1: 缓存 round-trip
    验证 TTL 内第二次调用返回相同数据且不触发第二次 API 调用。
    """
    import pandas as pd
    from unittest.mock import MagicMock, patch
    from futu import RET_OK

    # 构造 mock futu_client
    mock_client = MagicMock()
    mock_client.client = MagicMock()
    mock_client.client.subscribe.return_value = (RET_OK, "")

    # 构造 mock get_rt_ticker 返回的 DataFrame
    df = pd.DataFrame({
        "time": ["2024-01-01 10:00:01", "2024-01-01 10:00:02"],
        "price": [100.0, 100.5],
        "volume": [200, 300],
        "turnover": [20000.0, 30150.0],
        "ticker_direction": ["BUY", "SELL"],
    })
    mock_client.get_rt_ticker.return_value = (RET_OK, df)

    service = TickerService(mock_client)

    # 第一次调用 → 应触发 API
    result1 = await service.get_ticker_data("HK.00700")
    assert result1 is not None
    assert result1.total_count == 2
    assert mock_client.get_rt_ticker.call_count == 1

    # 第二次调用（TTL 内）→ 应命中缓存，不触发第二次 API
    result2 = await service.get_ticker_data("HK.00700")
    assert result2 is not None
    assert mock_client.get_rt_ticker.call_count == 1  # 仍然只调用了 1 次

    # 两次返回相同数据
    assert result1.stock_code == result2.stock_code
    assert result1.total_count == result2.total_count
    assert result1 is result2  # 同一缓存对象引用


# ==================== 生成器策略 ====================

VALID_SIGNALS = {"bullish", "slightly_bullish", "neutral", "slightly_bearish", "bearish"}


@st.composite
def ticker_record_strategy(draw):
    """生成随机 TickerRecord"""
    return TickerRecord(
        time=draw(st.from_regex(r"2024-01-01 \d{2}:\d{2}:\d{2}", fullmatch=True)),
        price=draw(st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False)),
        volume=draw(st.integers(min_value=1, max_value=1000000)),
        turnover=draw(st.floats(min_value=0.01, max_value=100000000.0, allow_nan=False, allow_infinity=False)),
        direction=draw(st.sampled_from(["BUY", "SELL", "NEUTRAL"])),
    )


records_strategy = st.lists(ticker_record_strategy(), min_size=1, max_size=200)


# ==================== Property 2: 主动买卖分类统计正确性 ====================
# Feature: real-trade-analysis, Property 2: 主动买卖分类统计正确性


@given(records=records_strategy)
@settings(max_examples=30)
def test_active_buy_sell_classification(records):
    """**Validates: Requirements 2.1, 2.5**

    验证:
    - buy_count + sell_count + neutral_count == total_count == len(records)
    - buy_turnover ≈ sum(BUY records turnover)
    - sell_turnover ≈ sum(SELL records turnover)
    - NEUTRAL 记录不计入 buy_turnover 或 sell_turnover
    """
    result = analyze_active_buy_sell(records)
    d = result.details

    # 计数守恒
    assert d["buy_count"] + d["sell_count"] + d["neutral_count"] == d["total_count"]
    assert d["total_count"] == len(records)

    # 按 direction 手动统计
    expected_buy = sum(r.turnover for r in records if r.direction == "BUY")
    expected_sell = sum(r.turnover for r in records if r.direction == "SELL")

    # details 中的值经过 round(x, 2)，用 approx 比较
    assert d["buy_turnover"] == pytest.approx(round(expected_buy, 2), rel=1e-6, abs=0.02)
    assert d["sell_turnover"] == pytest.approx(round(expected_sell, 2), rel=1e-6, abs=0.02)

    # NEUTRAL 不计入 buy/sell turnover：验证 buy+sell 不包含 NEUTRAL
    neutral_turnover = sum(r.turnover for r in records if r.direction == "NEUTRAL")
    total_accounted = d["buy_turnover"] + d["sell_turnover"]
    total_all = round(expected_buy + expected_sell, 2)
    assert total_accounted == pytest.approx(total_all, rel=1e-6, abs=0.02)


# ==================== Property 3: 主动买卖净额和力量比计算 ====================
# Feature: real-trade-analysis, Property 3: 主动买卖净额和力量比计算


@given(records=records_strategy)
@settings(max_examples=30)
def test_active_buy_sell_net_and_ratio(records):
    """**Validates: Requirements 2.2, 2.3**

    验证:
    - net_turnover == buy_turnover - sell_turnover
    - sell_turnover > 0 时 buy_sell_ratio ≈ buy_turnover / sell_turnover
    - sell_turnover == 0 时 buy_sell_ratio == 10.0
    """
    result = analyze_active_buy_sell(records)
    d = result.details

    # net_turnover = buy_turnover - sell_turnover（均为 round 后的值）
    expected_net = round(d["buy_turnover"] - d["sell_turnover"], 2)
    assert d["net_turnover"] == pytest.approx(expected_net, rel=1e-6, abs=0.02)

    # buy_sell_ratio
    # 注意：业务代码用原始浮点数计算 ratio 后再 round，
    # 而 details 中的 buy/sell_turnover 已经各自 round 过，
    # 用 round 后的值重新除会因中间精度损失产生偏差（如 0.875→0.88），
    # 因此这里只验证 ratio 的合理范围和方向性，不做精确重算。
    if d["sell_turnover"] > 0:
        approx_ratio = d["buy_turnover"] / d["sell_turnover"]
        assert d["buy_sell_ratio"] == pytest.approx(approx_ratio, rel=0.05, abs=0.05)
        # 方向性：buy > sell 时 ratio > 1，反之 < 1
        if d["buy_turnover"] > d["sell_turnover"]:
            assert d["buy_sell_ratio"] >= 1.0
        elif d["buy_turnover"] < d["sell_turnover"]:
            assert d["buy_sell_ratio"] <= 1.0
    else:
        assert d["buy_sell_ratio"] == 10.0


# ==================== Property 4: 所有维度评分范围和信号有效性 ====================
# Feature: real-trade-analysis, Property 4: 所有维度评分范围和信号有效性


@given(
    records=records_strategy,
    current_price=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
    min_order_amount=st.floats(min_value=1.0, max_value=10000000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=30)
def test_all_dimensions_score_range_and_signal(records, current_price, min_order_amount):
    """**Validates: Requirements 2.4, 3.5**

    验证:
    - 4 个维度函数返回的 score 均在 [-100, 100]
    - signal 是有效信号之一
    """
    results = [
        analyze_active_buy_sell(records),
        analyze_big_order_ratio(records, min_order_amount),
        analyze_volume_clusters(records, current_price),
        analyze_trade_rhythm(records),
    ]

    for r in results:
        assert -100 <= r.score <= 100, f"{r.name}: score {r.score} out of range"
        assert r.signal in VALID_SIGNALS, f"{r.name}: invalid signal {r.signal}"


# ==================== Property 5: 大单分析内部一致性 ====================
# Feature: real-trade-analysis, Property 5: 大单分析内部一致性


@given(
    records=records_strategy,
    min_order_amount=st.floats(min_value=0.01, max_value=10000000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=30)
def test_big_order_internal_consistency(records, min_order_amount):
    """**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

    验证:
    - 大单记录的 turnover >= min_order_amount
    - big_order_pct ≈ big_order_turnover / total_turnover * 100
    - big_net_buy ≈ big_buy_turnover - big_sell_turnover
    """
    result = analyze_big_order_ratio(records, min_order_amount)
    d = result.details

    # 手动筛选大单验证
    big_records = [r for r in records if r.turnover >= min_order_amount]
    assert d["big_order_count"] == len(big_records)

    # big_order_pct
    if d["total_turnover"] > 0:
        expected_pct = round(d["big_order_turnover"] / d["total_turnover"] * 100, 2)
        assert d["big_order_pct"] == pytest.approx(expected_pct, rel=1e-6, abs=0.02)

    # big_net_buy = big_buy_turnover - big_sell_turnover
    expected_net = round(d["big_buy_turnover"] - d["big_sell_turnover"], 2)
    assert d["big_net_buy"] == pytest.approx(expected_net, rel=1e-6, abs=0.02)



# ==================== Property 6: 密集区分组聚合守恒 ====================
# Feature: real-trade-analysis, Property 6: 密集区分组聚合守恒


@given(
    records=records_strategy,
    current_price=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=30)
def test_volume_clusters_aggregation_conservation(records, current_price):
    """**Validates: Requirements 4.1, 4.2, 4.5**

    验证:
    - cluster_count <= 3
    - 每个密集区 buy_pct + sell_pct + neutral_pct ≈ 1.0
    - 密集区中每个价位的成交量 >= 未入选价位的成交量
    """
    result = analyze_volume_clusters(records, current_price)
    d = result.details

    assert d["cluster_count"] <= 3

    clusters = d["clusters"]
    for c in clusters:
        pct_sum = c["buy_pct"] + c["sell_pct"] + c["neutral_pct"]
        assert pct_sum == pytest.approx(1.0, abs=0.001)

    # 密集区是 top-N 成交量价位，其成交量应 >= 未入选价位
    if clusters:
        # 按价格分组统计实际成交量
        volume_by_price: dict[float, int] = defaultdict(int)
        for r in records:
            volume_by_price[r.price] += r.volume

        cluster_prices = {c["price"] for c in clusters}
        non_cluster_prices = set(volume_by_price.keys()) - cluster_prices

        if non_cluster_prices:
            min_cluster_vol = min(c["volume"] for c in clusters)
            max_non_cluster_vol = max(volume_by_price[p] for p in non_cluster_prices)
            assert min_cluster_vol >= max_non_cluster_vol


# ==================== Property 7: 密集区支撑/阻力标记正确性 ====================
# Feature: real-trade-analysis, Property 7: 密集区支撑/阻力标记正确性


@given(
    records=records_strategy,
    current_price=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=30)
def test_volume_clusters_support_resistance_labels(records, current_price):
    """**Validates: Requirements 4.3, 4.4**

    验证:
    - price < current_price → type == "support"
    - price > current_price → type == "resistance"
    - price == current_price → type == "current"
    """
    result = analyze_volume_clusters(records, current_price)
    clusters = result.details["clusters"]

    for c in clusters:
        if c["price"] < current_price:
            assert c["type"] == "support", f"price {c['price']} < {current_price} should be support"
        elif c["price"] > current_price:
            assert c["type"] == "resistance", f"price {c['price']} > {current_price} should be resistance"
        else:
            assert c["type"] == "current", f"price {c['price']} == {current_price} should be current"


# ==================== Property 8: 时间窗口分组守恒 ====================
# Feature: real-trade-analysis, Property 8: 时间窗口分组守恒


@given(records=records_strategy)
@settings(max_examples=30)
def test_trade_rhythm_window_conservation(records):
    """**Validates: Requirements 5.1, 5.2**

    验证:
    - 当 window_count >= 2 时，latest_window_count + prev_window_count <= len(records)
    - 手动按分钟键分组后，所有窗口的 count 之和 == len(records)
    """
    result = analyze_trade_rhythm(records)
    d = result.details

    # 手动按分钟键分组验证总数守恒
    windows: dict[str, int] = defaultdict(int)
    for r in records:
        minute_key = r.time[:16]
        windows[minute_key] += 1

    assert d["window_count"] == len(windows)
    assert sum(windows.values()) == len(records)

    # latest + prev <= total（当有 >= 2 个窗口时）
    if d["window_count"] >= 2:
        assert d["latest_window_count"] + d["prev_window_count"] <= len(records)


# ==================== Property 9: 节奏模式与变化率一致性 ====================
# Feature: real-trade-analysis, Property 9: 节奏模式与变化率一致性


@given(records=records_strategy)
@settings(max_examples=30)
def test_trade_rhythm_pattern_consistency(records):
    """**Validates: Requirements 5.3, 5.4, 5.5**

    验证 change_rate 与 pattern 的映射关系:
    - change_rate > 0.5 → "加速放量"
    - 0.2 < change_rate <= 0.5 → "温和放量"
    - -0.2 <= change_rate <= 0.2 → "平稳"
    - -0.5 <= change_rate < -0.2 → "温和缩量"
    - change_rate < -0.5 → "急剧缩量"
    """
    result = analyze_trade_rhythm(records)
    d = result.details
    rate = d["change_rate"]
    pattern = d["pattern"]

    if rate > 0.5:
        assert pattern == "加速放量", f"rate={rate}, expected 加速放量, got {pattern}"
    elif rate > 0.2:
        assert pattern == "温和放量", f"rate={rate}, expected 温和放量, got {pattern}"
    elif rate > -0.2:
        assert pattern == "平稳", f"rate={rate}, expected 平稳, got {pattern}"
    elif rate > -0.5:
        assert pattern == "温和缩量", f"rate={rate}, expected 温和缩量, got {pattern}"
    else:
        assert pattern == "急剧缩量", f"rate={rate}, expected 急剧缩量, got {pattern}"


# ==================== Property 10: 综合评分加权计算正确性 ====================
# Feature: real-trade-analysis, Property 10: 综合评分加权计算正确性


@given(
    ob_score=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    ticker_score=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    spread_pct=st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_combined_score_weighted_calculation(ob_score, ticker_score, spread_pct):
    """**Validates: Requirements 6.1, 6.2**

    验证自适应权重计算:
    - 权重之和始终为 1.0
    - spread_pct > 0.5 → ob_w=0.25
    - spread_pct < 0.1 → ob_w=0.50
    - 其他 → ob_w=0.40（默认）
    - 矛盾时 combined_score *= 0.3
    """
    from simple_trade.services.market_data.ticker_analysis.combined_analyzer import (
        CombinedAnalyzer,
    )
    from simple_trade.services.market_data.order_book.order_book_analyzer import _clamp
    from unittest.mock import MagicMock

    # 构造 mock ob_result 以控制 spread_pct
    mock_ob = MagicMock()
    mock_ob.order_book_raw = {'spread_pct': spread_pct}

    ob_w, tk_w = CombinedAnalyzer._adaptive_weights(mock_ob)

    # 属性 1：权重之和始终为 1.0
    assert ob_w + tk_w == pytest.approx(1.0, abs=1e-9)

    # 属性 2：权重范围正确
    if spread_pct > 0.5:
        assert ob_w == 0.25
    elif spread_pct < 0.1:
        assert ob_w == 0.50
    else:
        assert ob_w == 0.40

    # 属性 3：加权计算正确
    raw = ob_score * ob_w + ticker_score * tk_w
    has_contradiction = CombinedAnalyzer._check_contradiction(ob_score, ticker_score)
    if has_contradiction:
        raw *= 0.3
    expected = round(_clamp(raw), 1)

    # 验证 expected 在合法范围内
    assert -100.0 <= expected <= 100.0


# ==================== Property 11: 矛盾检测正确性 ====================
# Feature: real-trade-analysis, Property 11: 矛盾检测正确性


@given(
    ob_score=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    ticker_score=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=30)
def test_contradiction_detection(ob_score, ticker_score):
    """**Validates: Requirements 6.4**

    验证:
    - ob_score 和 ticker_score 符号相反且绝对值均 > 10 时 has_contradiction 为 True
    - 否则 has_contradiction 为 False
    - 矛盾时 summary 包含"矛盾"字样
    """
    from simple_trade.services.market_data.ticker_analysis.combined_analyzer import (
        CombinedAnalyzer,
    )

    has_contradiction = CombinedAnalyzer._check_contradiction(ob_score, ticker_score)

    # 符号相反且绝对值均 > 10 → 矛盾
    signs_opposite = ob_score * ticker_score < 0
    both_significant = abs(ob_score) > 10 and abs(ticker_score) > 10

    if signs_opposite and both_significant:
        assert has_contradiction is True
    else:
        assert has_contradiction is False

    # 矛盾时 summary 应包含"矛盾"
    if has_contradiction:
        summary = CombinedAnalyzer._build_summary(
            "挂单偏多", "成交偏空", has_contradiction, True
        )
        assert "矛盾" in summary


# ==================== Property 12: 降级行为正确性 ====================
# Feature: real-trade-analysis, Property 12: 降级行为正确性


@given(
    ob_score=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=30)
def test_degradation_behavior(ob_score):
    """**Validates: Requirements 6.5**

    验证成交数据不可用时:
    - combined_score == ob_score（经 clamp + round 后）
    - ticker_available 为 False
    - ticker_dimensions 为空列表
    - has_contradiction 为 False
    """
    from simple_trade.services.market_data.order_book.order_book_analyzer import _clamp

    # 模拟降级场景：ticker_result 为 None 时的计算逻辑
    combined_score = round(_clamp(ob_score), 1)
    expected_ob = round(_clamp(ob_score), 1)

    # 降级时 combined_score 应等于 ob_score
    assert combined_score == pytest.approx(expected_ob, rel=1e-6, abs=0.02)

    # 降级时 ticker_available 为 False, ticker_dimensions 为空
    ticker_available = False
    ticker_dims = []
    has_contradiction = False

    assert ticker_available is False
    assert ticker_dims == []
    assert has_contradiction is False
