#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from simple_trade.services.analysis.flow.inflow_market_gate import (
    InflowMarketGate,
    InflowMarketGateConfig,
)


def _quotes(up_count=60, total=100, market="HK", plate="半导体"):
    rows = []
    for i in range(total):
        change = 4.0 if i < up_count else -1.0
        rows.append({
            "code": f"{market}.{i:05d}",
            "last_price": 10.0 + change / 100,
            "prev_close": 10.0,
            "change_percent": change,
            "turnover": float(total - i) * 1_000_000,
            "plate_name": plate,
        })
    return rows


def _gate(**overrides):
    cfg = InflowMarketGateConfig(
        enabled=True,
        hot_turnover_percentile=0.80,
        extreme_hot_turnover_percentile=0.90,
        normal_market_breadth=0.55,
        weak_market_breadth=0.40,
        normal_plate_breadth=0.55,
        weak_plate_breadth=0.50,
        extreme_plate_breadth=0.70,
        normal_relative_strength_pct=0.0,
        weak_relative_strength_pct=2.50,
        extreme_relative_strength_pct=2.50,
        min_universe_size=20,
        min_plate_size=5,
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
    assert top["risk_mode"] == "NORMAL"
    assert top["required_confirmations"] == 2

    # 同样上涨，但成交额排名在后80%，不是热门股。
    cold = contexts["HK.00050"]
    assert cold["eligible"] is False
    assert cold["is_hot"] is False


def test_weak_market_uses_plate_and_relative_strength_instead_of_hard_block():
    quotes = _quotes(up_count=50)
    for i, quote in enumerate(quotes):
        quote["plate_name"] = "半导体" if i < 10 else "其他"
        if i < 7:
            quote["change_percent"] = 1.0
        elif i < 10:
            quote["change_percent"] = -1.0
    quotes[0]["change_percent"] = 4.0
    top = _gate().evaluate(quotes)["HK.00000"]
    assert top["is_hot"] is True
    assert top["eligible"] is True
    assert top["risk_mode"] == "WEAK"
    assert top["plate_breadth"] == 0.7
    assert top["relative_strength_pct"] == 3.0


def test_weak_market_without_plate_is_blocked():
    quotes = _quotes(up_count=50, plate="")
    top = _gate().evaluate(quotes)["HK.00000"]
    assert top["risk_mode"] == "WEAK"
    assert top["eligible"] is False
    assert "板块样本不足" in top["reason"]


def test_normal_market_also_requires_plate_breadth():
    quotes = _quotes(up_count=60)
    for i, quote in enumerate(quotes):
        quote["plate_name"] = "半导体" if i < 10 else "其他"
        if 5 <= i < 10:
            quote["change_percent"] = -1.0
    top = _gate().evaluate(quotes)["HK.00000"]
    assert top["risk_mode"] == "NORMAL"
    assert top["plate_breadth"] == 0.5
    assert top["eligible"] is False
    assert "正常市场板块宽度不足" in top["reason"]


def test_extreme_market_requires_top10_and_three_confirmations():
    quotes = _quotes(up_count=30)
    for i, quote in enumerate(quotes):
        quote["plate_name"] = "AI" if i < 10 else "其他"
        if i < 7:
            quote["change_percent"] = 1.0
    quotes[0]["change_percent"] = 4.0
    contexts = _gate().evaluate(quotes)
    assert contexts["HK.00000"]["eligible"] is True
    assert contexts["HK.00000"]["risk_mode"] == "EXTREME"
    assert contexts["HK.00000"]["required_confirmations"] == 3
    assert contexts["HK.00010"]["is_hot"] is False


def test_hot_stock_does_not_need_to_be_up_3_percent():
    quotes = _quotes(up_count=60)
    for i in range(5):
        quotes[i]["plate_name"] = "低位启动"
        quotes[i]["change_percent"] = 0.5
    for i in range(5, len(quotes)):
        quotes[i]["plate_name"] = "其他"
    top = _gate().evaluate(quotes)["HK.00000"]
    assert top["is_hot"] is True
    assert top["eligible"] is True


def test_market_breadth_is_calculated_independently():
    quotes = _quotes(up_count=12, total=20, market="HK")
    quotes += _quotes(up_count=8, total=20, market="US")
    contexts = _gate().evaluate(quotes)
    assert contexts["HK.00000"]["market_breadth"] == 0.6
    assert contexts["HK.00000"]["eligible"] is True
    assert contexts["US.00000"]["market_breadth"] == 0.4
    assert contexts["US.00000"]["risk_mode"] == "WEAK"


def test_disabled_gate_is_fail_open_for_rollback():
    context = _gate(enabled=False).evaluate(_quotes(up_count=1))["HK.00099"]
    assert context["eligible"] is True
    assert "已关闭" in context["reason"]
