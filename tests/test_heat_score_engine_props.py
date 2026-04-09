#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HeatScoreEngine 属性测试

使用 hypothesis 验证评分引擎的核心正确性属性：
- Property 5: 评分引擎归一化不变量
- Property 6: 基础评分公式一致性
- Property 7: 龙头评分公式一致性
"""

import os
import sys

import pytest
from hypothesis import given, settings, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.analysis.heat.heat_score_engine import (
    HeatScoreEngine,
    ScoreCaps,
)


# ── hypothesis 策略 ──────────────────────────────────────────────

# 非负浮点数（用于归一化输入）
non_negative_float = st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False)

# 正浮点数（用于 cap 值）
positive_float = st.floats(min_value=0.01, max_value=1e4, allow_nan=False, allow_infinity=False)

# 涨跌幅（可为负）
change_pct_st = st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False)

# 量比
volume_ratio_st = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)

# 换手率
turnover_rate_st = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)

# 板块内排名（正整数）
rank_st = st.integers(min_value=1, max_value=500)

# 板块大小（正整数）
plate_size_st = st.integers(min_value=1, max_value=500)

# 连续强势天数
consecutive_days_st = st.integers(min_value=0, max_value=30)

# 资金净流入占比
net_inflow_st = st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False)


@pytest.fixture
def engine():
    return HeatScoreEngine()


# ── Property 5: 评分引擎归一化不变量 ────────────────────────────
# Feature: enhanced-heat-optimization, Property 5: 评分引擎归一化不变量
# **Validates: Requirements 4.4**


class TestProperty5NormalizationInvariant:
    """Property 5: 对于任意非负的输入值，normalize 输出在 0-100，
    calculate_base_score 和 calculate_leader_score 输出也在 0-100。"""

    @given(value=non_negative_float, cap=positive_float)
    @settings(max_examples=200)
    def test_normalize_output_range(self, value, cap):
        """normalize 对任意非负 value 和正 cap，输出应在 [0, 100]"""
        engine = HeatScoreEngine()
        result = engine.normalize(value, cap)
        assert 0.0 <= result <= 100.0, f"normalize({value}, {cap}) = {result}, 超出 [0, 100]"

    @given(
        change_pct=change_pct_st,
        volume_ratio=volume_ratio_st,
        turnover_rate=turnover_rate_st,
    )
    @settings(max_examples=200)
    def test_base_score_output_range(self, change_pct, volume_ratio, turnover_rate):
        """calculate_base_score 对任意输入，输出应在 [0, 100]"""
        engine = HeatScoreEngine()
        score = engine.calculate_base_score(change_pct, volume_ratio, turnover_rate)
        assert 0.0 <= score <= 100.0, (
            f"calculate_base_score({change_pct}, {volume_ratio}, {turnover_rate}) = {score}"
        )

    @given(
        change_pct=change_pct_st,
        volume_ratio=volume_ratio_st,
        turnover_rate=turnover_rate_st,
        rank_in_plate=rank_st,
        plate_size=plate_size_st,
        consecutive_strong_days=consecutive_days_st,
        net_inflow_ratio=net_inflow_st,
    )
    @settings(max_examples=200)
    def test_leader_score_output_range(
        self, change_pct, volume_ratio, turnover_rate,
        rank_in_plate, plate_size, consecutive_strong_days, net_inflow_ratio,
    ):
        """calculate_leader_score 对任意输入，输出应在 [0, 100]"""
        engine = HeatScoreEngine()
        score = engine.calculate_leader_score(
            change_pct, volume_ratio, turnover_rate,
            rank_in_plate, plate_size,
            consecutive_strong_days, net_inflow_ratio,
        )
        assert 0.0 <= score <= 100.0, (
            f"calculate_leader_score(...) = {score}"
        )


# ── Property 6: 基础评分公式一致性 ──────────────────────────────
# Feature: enhanced-heat-optimization, Property 6: 基础评分公式一致性
# **Validates: Requirements 4.2**


class TestProperty6BaseScoreFormula:
    """Property 6: 对于任意涨幅、量比、换手率输入，calculate_base_score 输出
    应等于各维度归一化后按 0.4/0.3/0.3 权重加权求和的结果。"""

    @given(
        change_pct=change_pct_st,
        volume_ratio=volume_ratio_st,
        turnover_rate=turnover_rate_st,
    )
    @settings(max_examples=200)
    def test_base_score_equals_weighted_sum(self, change_pct, volume_ratio, turnover_rate):
        """base_score 应严格等于手动计算的加权求和"""
        engine = HeatScoreEngine()
        caps = engine.caps

        # 手动计算各维度归一化分数
        change_score = engine.normalize(abs(change_pct), caps.change_pct)
        volume_score = engine.normalize(volume_ratio, caps.volume_ratio)
        turnover_score = engine.normalize(turnover_rate, caps.turnover_rate)

        expected = round(
            change_score * 0.4 + volume_score * 0.3 + turnover_score * 0.3,
            2,
        )

        actual = engine.calculate_base_score(change_pct, volume_ratio, turnover_rate)
        assert actual == pytest.approx(expected, abs=1e-9), (
            f"base_score({change_pct}, {volume_ratio}, {turnover_rate}): "
            f"actual={actual}, expected={expected}"
        )


# ── Property 7: 龙头评分公式一致性 ──────────────────────────────
# Feature: enhanced-heat-optimization, Property 7: 龙头评分公式一致性
# **Validates: Requirements 4.3**


class TestProperty7LeaderScoreFormula:
    """Property 7: 对于任意涨幅排名、量比、换手率、连续强势天数、资金净流入输入，
    calculate_leader_score 输出应等于各维度归一化后按 30%/20%/15%/20%/15%
    权重加权求和的结果。"""

    @given(
        volume_ratio=volume_ratio_st,
        turnover_rate=turnover_rate_st,
        rank_in_plate=rank_st,
        plate_size=plate_size_st,
        consecutive_strong_days=consecutive_days_st,
        net_inflow_ratio=net_inflow_st,
    )
    @settings(max_examples=200)
    def test_leader_score_equals_weighted_sum(
        self, volume_ratio, turnover_rate,
        rank_in_plate, plate_size,
        consecutive_strong_days, net_inflow_ratio,
    ):
        """leader_score 应严格等于手动计算的加权求和"""
        engine = HeatScoreEngine()
        caps = engine.caps

        # 手动计算排名分
        rank_score = HeatScoreEngine._calculate_rank_score(rank_in_plate, plate_size)

        # 手动计算各维度归一化分数
        volume_score = engine.normalize(volume_ratio, caps.volume_ratio)
        turnover_score = engine.normalize(turnover_rate, caps.turnover_rate)
        consecutive_score = engine.normalize(consecutive_strong_days, caps.consecutive_days)
        inflow_score = engine.normalize(net_inflow_ratio, caps.net_inflow_ratio)

        expected = round(
            rank_score * 0.30
            + volume_score * 0.20
            + turnover_score * 0.15
            + consecutive_score * 0.20
            + inflow_score * 0.15,
            2,
        )

        actual = engine.calculate_leader_score(
            change_pct=0,  # change_pct 不直接参与龙头评分公式
            volume_ratio=volume_ratio,
            turnover_rate=turnover_rate,
            rank_in_plate=rank_in_plate,
            plate_size=plate_size,
            consecutive_strong_days=consecutive_strong_days,
            net_inflow_ratio=net_inflow_ratio,
        )
        assert actual == pytest.approx(expected, abs=1e-9), (
            f"leader_score: actual={actual}, expected={expected}"
        )
