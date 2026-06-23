# -*- coding: utf-8 -*-
"""入场择时纯函数 judge_entry_timing 单测（无 DB / 无外部状态）。"""

from simple_trade.services.trading.entry_timing import (
    judge_entry_timing as j,
    EntryTimingThresholds,
    EntryTimingService,
)


def _svc_with_gains(gains):
    """构造 EntryTimingService 并预置 _all_gains 缓存，免 DB 测 market_regime。"""
    svc = EntryTimingService(db_manager=None)
    svc._gains_td = "2026-06-23"
    svc._gains = [(f"HK.{i:05d}", g) for i, g in enumerate(gains)]
    return svc


def test_green_dip_lower_range_cool_flow():
    light, label, _ = j(-0.006, 0.1, 0.2)
    assert light == "green"
    assert "低吸" in label


def test_green_strong_when_near_day_low():
    light, label, _ = j(-0.006, 0.0, 0.10)
    assert light == "green"
    assert "较优" in label


def test_red_spike_with_hot_flow():
    assert j(0.006, 0.4, 0.5)[0] == "red"


def test_red_spike_near_day_high():
    assert j(0.006, 0.1, 0.85)[0] == "red"


def test_neutral_dip_but_high_in_range():
    # 刚回调但价位仍贴近日内高 -> 不是低吸点
    assert j(-0.006, 0.1, 0.9)[0] == "neutral"


def test_neutral_dip_but_flow_overheated():
    # 刚回调但主动买盘过热 -> 观望
    assert j(-0.006, 0.4, 0.2)[0] == "neutral"


def test_neutral_flat_momentum():
    assert j(0.0, 0.1, 0.5)[0] == "neutral"


def test_neutral_missing_data():
    assert j(None, 0.1, 0.2)[0] == "neutral"
    assert j(-0.006, 0.1, None)[0] == "neutral"


def test_ofi_none_still_allows_green():
    # 单流缺失不应阻止低吸判定（仅价位+动量满足即可）
    assert j(-0.006, None, 0.2)[0] == "green"


def test_thresholds_are_tunable():
    th = EntryTimingThresholds(dip_mom=-0.01)
    # -0.6% 不再达到更严格的 -1.0% 回调门槛 -> 不再 green
    assert j(-0.006, 0.1, 0.2, th)[0] != "green"


# ---------- market_regime: 中位+均值+宽度 ----------

def test_regime_giveback_day_is_down_by_breadth():
    # 给回日：上涨股不过半(43↑57↓=0.43<=0.45) → down（即使中位/均值都没到 -0.5%）
    svc = _svc_with_gains([0.004] * 43 + [-0.004] * 57)
    r = svc.market_regime("2026-06-23")
    assert r["regime"] == "down"
    assert r["up_ratio"] == 0.43
    assert r["breadth"] == "43↑57↓"


def test_regime_down_by_mean_even_if_breadth_ok():
    # 上涨过半但均值被极端负值拖到 <=-0.5% → 仍 down
    svc = _svc_with_gains([0.002] * 60 + [-0.02] * 40)
    assert svc.market_regime("2026-06-23")["regime"] == "down"


def test_regime_up_day():
    svc = _svc_with_gains([0.01] * 80 + [-0.002] * 20)
    assert svc.market_regime("2026-06-23")["regime"] == "up"


def test_regime_flat_day():
    svc = _svc_with_gains([0.002] * 50 + [-0.002] * 50)
    assert svc.market_regime("2026-06-23")["regime"] == "flat"


def test_regime_unknown_when_too_few():
    svc = _svc_with_gains([0.01] * 5)
    assert svc.market_regime("2026-06-23")["regime"] == "unknown"
