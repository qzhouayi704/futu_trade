#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""InflowRankingScorer 单测 —— 纯内存、无 I/O，覆盖：
单调性、缺失因子按剩余归一、每信号权重差异、penalty 乘法、veto 压制、
from_env 覆盖单权重、disabled 原样返回、全缺因子中性 50。
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.analysis.flow.inflow_ranking_scorer import (  # noqa: E402
    InflowRankingScorer,
    InflowRankingConfig,
)


def _scorer(enabled=True, **ov):
    cfg = InflowRankingConfig(enabled=enabled)
    for k, v in ov.items():
        setattr(cfg, k, v)
    return InflowRankingScorer(cfg)


# ---------- 1. 单调性：inflow 下仅 flow 更高 → rank_score 更高 ----------
def test_monotonic_flow_higher_scores_higher():
    s = _scorer()
    base_metrics = {"base": 50, "pos": 50, "flow": 40, "leader": 50}
    high_flow = dict(base_metrics, flow=90)
    lo = s.score_one(base_metrics, "inflow")
    hi = s.score_one(high_flow, "inflow")
    assert hi > lo


# ---------- 2. 缺失因子按剩余归一：缺 base 不崩，排序按存在因子 ----------
def test_missing_factor_renormalizes():
    s = _scorer()
    # 缺 base：其余因子 pos/flow/leader 归一（不用常数填 base）
    m_missing = {"pos": 50, "flow": 50, "leader": 50}       # 无 base → 应得 50
    assert abs(s.score_one(m_missing, "inflow") - 50.0) < 1e-6
    # 两只都缺 base，只差 flow 一个存在因子 → flow 高者分高
    a = {"pos": 50, "flow": 30, "leader": 50}
    b = {"pos": 50, "flow": 80, "leader": 50}
    assert s.score_one(b, "inflow") > s.score_one(a, "inflow")


# ---------- 3. 每信号权重不同：theme 只在 theme 信号生效 ----------
def test_per_signal_weights_theme_only_in_theme():
    s = _scorer()
    common = {"base": 50, "pos": 50, "flow": 50, "leader": 50}
    low_theme = dict(common, theme=0)
    high_theme = dict(common, theme=100)
    # inflow 下 theme 权重=0 → 两者同分（theme 不计入）
    assert abs(s.score_one(low_theme, "inflow") - s.score_one(high_theme, "inflow")) < 1e-6
    # theme 信号下 theme 权重>0 → 高 theme 分更高
    assert s.score_one(high_theme, "theme") > s.score_one(low_theme, "theme")


# ---------- 4. penalty_factor 乘法：pf=0.5 使分减半 ----------
def test_penalty_factor_halves():
    s = _scorer()
    m = {"base": 80, "pos": 80, "flow": 80, "leader": 80}
    full = s.score_one(m, "inflow")
    halved = s.score_one(dict(m, penalty_factor=0.5), "inflow")
    assert abs(full - 80.0) < 1e-6
    assert abs(halved - 40.0) < 1e-6


# ---------- 5. veto 压制：veto=True 排在同 metrics veto=False 之后 ----------
def test_veto_suppresses_ranking():
    s = _scorer()
    metrics = {"base": 70, "pos": 70, "flow": 70, "leader": 70}
    cands = [
        {"id": "vetoed", "metrics": dict(metrics, veto=True)},
        {"id": "clean", "metrics": dict(metrics, veto=False)},
    ]
    ranked = s.rank(cands, "inflow")
    assert ranked[0]["id"] == "clean"
    assert ranked[1]["id"] == "vetoed"
    assert ranked[1]["rank_score"] < ranked[0]["rank_score"]


# ---------- 6. from_env：SIGNAL_RANK_W_BASE_INFLOW=0 → inflow 下 base 不计入 ----------
def test_from_env_override_zeroes_base(monkeypatch):
    monkeypatch.setenv("SIGNAL_RANK_W_BASE_INFLOW", "0")
    cfg = InflowRankingConfig.from_env()
    s = InflowRankingScorer(cfg)
    # base=100 被置 0 权重后不影响；其余 pos/flow/leader 均 50 → 归一得 50
    m = {"base": 100, "pos": 50, "flow": 50, "leader": 50}
    assert abs(s.score_one(m, "inflow") - 50.0) < 1e-6
    assert cfg.weights["inflow"]["base"] == 0.0


# ---------- 7. disabled：enabled=False 时 rank 原样返回输入顺序 ----------
def test_disabled_returns_input_unchanged():
    s = _scorer(enabled=False)
    cands = [
        {"id": "a", "metrics": {"flow": 10}},
        {"id": "b", "metrics": {"flow": 90}},   # 若启用会被排到前面
    ]
    ranked = s.rank(cands, "inflow")
    assert ranked is cands
    assert [c["id"] for c in ranked] == ["a", "b"]
    assert "rank_score" not in cands[0]


# ---------- 8. 全缺因子 → 返回 50、不崩 ----------
def test_all_missing_returns_neutral_50():
    s = _scorer()
    assert s.score_one({}, "inflow") == 50.0
    # 未知 signal_type 回退 inflow，也不崩
    assert s.score_one({}, "unknown_signal") == 50.0


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        # 跳过需要 pytest fixture（如 monkeypatch）的用例
        if inspect.signature(fn).parameters:
            print(f"SKIP {fn.__name__} (needs fixture)")
            continue
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed} checked, {failed} failed")
    sys.exit(1 if failed else 0)
