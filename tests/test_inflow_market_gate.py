#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from simple_trade.services.analysis.flow.inflow_market_gate import (
    InflowMarketGate,
    InflowMarketGateConfig,
)


def _quotes(up_count=60, total=100, market="HK"):
    rows = []
    for i in range(total):
        change = 4.0 if i < up_count else -1.0
        rows.append({
            "code": f"{market}.{i:05d}",
            "last_price": 10.0 + change / 100,
            "prev_close": 10.0,
            "change_percent": change,
            "turnover": float(total - i) * 1_000_000,
        })
    return rows


def _gate(**overrides):
    cfg = InflowMarketGateConfig(
        enabled=True,
        hot_turnover_percentile=0.80,
        hot_min_change_pct=3.0,
        min_market_breadth=0.55,
        min_universe_size=20,
    )
    values = {**cfg.__dict__, **overrides}
    return InflowMarketGate(InflowMarketGateConfig(**values))


def test_hot_top20_and_breadth_pass():
    contexts = _gate().evaluate(_quotes(up_count=60))
    top = contexts["HK.00000"]
    assert top["eligible"] is True
    assert top["is_hot"] is True
    assert top["market_breadth"] == 0.6
    assert top["market_universe_size"] == 100

    # 同样上涨，但成交额排名在后80%，不是热门股。
    cold = contexts["HK.00050"]
    assert cold["eligible"] is False
    assert cold["is_hot"] is False


def test_breadth_below_55_blocks_even_hottest_stock():
    top = _gate().evaluate(_quotes(up_count=54))["HK.00000"]
    assert top["is_hot"] is True
    assert top["eligible"] is False
    assert "市场宽度不足" in top["reason"]


def test_market_breadth_is_calculated_independently():
    quotes = _quotes(up_count=12, total=20, market="HK")
    quotes += _quotes(up_count=8, total=20, market="US")
    contexts = _gate().evaluate(quotes)
    assert contexts["HK.00000"]["market_breadth"] == 0.6
    assert contexts["HK.00000"]["eligible"] is True
    assert contexts["US.00000"]["market_breadth"] == 0.4
    assert contexts["US.00000"]["eligible"] is False


def test_disabled_gate_is_fail_open_for_rollback():
    context = _gate(enabled=False).evaluate(_quotes(up_count=1))["HK.00099"]
    assert context["eligible"] is True
    assert "已关闭" in context["reason"]
