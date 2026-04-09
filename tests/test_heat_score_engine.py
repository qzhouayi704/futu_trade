#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HeatScoreEngine 单元测试

验证统一评分引擎的各方法：
- normalize 归一化
- calculate_base_score 基础评分
- calculate_leader_score 龙头评分
- calculate_plate_heat 板块热度评分
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.analysis.heat.heat_score_engine import (
    HeatScoreEngine,
    ScoreCaps,
)


@pytest.fixture
def engine():
    return HeatScoreEngine()


# ── normalize ───────────────────────────────────────────────


class TestNormalize:
    def test_zero_value(self, engine):
        assert engine.normalize(0, 10) == 0.0

    def test_half_cap(self, engine):
        assert engine.normalize(5, 10) == 50.0

    def test_at_cap(self, engine):
        assert engine.normalize(10, 10) == 100.0

    def test_above_cap_clamped(self, engine):
        """超过 cap 的值应被截断为 100"""
        assert engine.normalize(20, 10) == 100.0

    def test_negative_value_treated_as_zero(self, engine):
        """负值应被视为 0"""
        assert engine.normalize(-5, 10) == 0.0

    def test_zero_cap_returns_zero(self, engine):
        """cap <= 0 时返回 0"""
        assert engine.normalize(10, 0) == 0.0
        assert engine.normalize(10, -1) == 0.0


# ── calculate_base_score ────────────────────────────────────


class TestBaseScore:
    def test_all_zero(self, engine):
        assert engine.calculate_base_score(0, 0, 0) == 0.0

    def test_all_at_cap(self, engine):
        """所有维度达到 cap 值时应得 100 分"""
        score = engine.calculate_base_score(20, 5, 20)
        assert score == 100.0

    def test_weight_correctness(self, engine):
        """验证权重 0.4/0.3/0.3"""
        # change_pct=20 → 100, volume_ratio=0 → 0, turnover=0 → 0
        score = engine.calculate_base_score(20, 0, 0)
        assert score == pytest.approx(40.0, abs=0.01)

        # change_pct=0, volume_ratio=5 → 100, turnover=0
        score = engine.calculate_base_score(0, 5, 0)
        assert score == pytest.approx(30.0, abs=0.01)

        # change_pct=0, volume_ratio=0, turnover=20 → 100
        score = engine.calculate_base_score(0, 0, 20)
        assert score == pytest.approx(30.0, abs=0.01)

    def test_uses_absolute_change_pct(self, engine):
        """涨幅取绝对值"""
        score_pos = engine.calculate_base_score(10, 0, 0)
        score_neg = engine.calculate_base_score(-10, 0, 0)
        assert score_pos == score_neg

    def test_output_range(self, engine):
        """输出应在 0-100 范围内"""
        score = engine.calculate_base_score(50, 20, 50)
        assert 0 <= score <= 100


# ── calculate_leader_score ──────────────────────────────────


class TestLeaderScore:
    def test_all_max(self, engine):
        """所有维度满分时应得 100"""
        score = engine.calculate_leader_score(
            change_pct=20, volume_ratio=5, turnover_rate=20,
            rank_in_plate=1, plate_size=10,
            consecutive_strong_days=5, net_inflow_ratio=1.0,
        )
        assert score == 100.0

    def test_all_zero(self, engine):
        score = engine.calculate_leader_score(
            change_pct=0, volume_ratio=0, turnover_rate=0,
            rank_in_plate=0, plate_size=0,
            consecutive_strong_days=0, net_inflow_ratio=0,
        )
        assert score == 0.0

    def test_weight_distribution(self, engine):
        """验证权重 30%/20%/15%/20%/15%"""
        # 只有排名分满分（rank=1, plate_size=10 → 100）
        score = engine.calculate_leader_score(
            change_pct=0, volume_ratio=0, turnover_rate=0,
            rank_in_plate=1, plate_size=10,
            consecutive_strong_days=0, net_inflow_ratio=0,
        )
        assert score == pytest.approx(30.0, abs=0.01)

        # 只有量比满分
        score = engine.calculate_leader_score(
            change_pct=0, volume_ratio=5, turnover_rate=0,
            rank_in_plate=0, plate_size=0,
            consecutive_strong_days=0, net_inflow_ratio=0,
        )
        assert score == pytest.approx(20.0, abs=0.01)

    def test_rank_score_first_place(self, engine):
        """排名第 1 应得满分排名分"""
        score = engine.calculate_leader_score(
            change_pct=0, volume_ratio=0, turnover_rate=0,
            rank_in_plate=1, plate_size=100,
            consecutive_strong_days=0, net_inflow_ratio=0,
        )
        # rank_score = 100/100 * 100 = 100, 权重 30%
        assert score == pytest.approx(30.0, abs=0.01)

    def test_rank_score_last_place(self, engine):
        """排名最后应得最低排名分"""
        score = engine.calculate_leader_score(
            change_pct=0, volume_ratio=0, turnover_rate=0,
            rank_in_plate=100, plate_size=100,
            consecutive_strong_days=0, net_inflow_ratio=0,
        )
        # rank_score = 1/100 * 100 = 1, 权重 30% → 0.3
        assert score == pytest.approx(0.3, abs=0.01)

    def test_output_range(self, engine):
        score = engine.calculate_leader_score(
            change_pct=50, volume_ratio=20, turnover_rate=50,
            rank_in_plate=1, plate_size=5,
            consecutive_strong_days=10, net_inflow_ratio=2.0,
        )
        assert 0 <= score <= 100


# ── calculate_plate_heat ────────────────────────────────────


class TestPlateHeat:
    def test_all_max(self, engine):
        score = engine.calculate_plate_heat(1.0, 10, 1.0, 1.0)
        assert score == 100.0

    def test_all_zero(self, engine):
        score = engine.calculate_plate_heat(0, 0, 0, 0)
        assert score == 0.0

    def test_weight_distribution(self, engine):
        """验证权重 30%/25%/25%/20%"""
        # 只有涨跌比满分
        score = engine.calculate_plate_heat(1.0, 0, 0, 0)
        assert score == pytest.approx(30.0, abs=0.01)

        # 只有平均涨幅满分
        score = engine.calculate_plate_heat(0, 10, 0, 0)
        assert score == pytest.approx(25.0, abs=0.01)

        # 只有大涨股占比满分
        score = engine.calculate_plate_heat(0, 0, 1.0, 0)
        assert score == pytest.approx(25.0, abs=0.01)

        # 只有资金净流入满分
        score = engine.calculate_plate_heat(0, 0, 0, 1.0)
        assert score == pytest.approx(20.0, abs=0.01)

    def test_output_range(self, engine):
        score = engine.calculate_plate_heat(2.0, 30, 2.0, 2.0)
        assert 0 <= score <= 100


# ── ScoreCaps 自定义 ────────────────────────────────────────


class TestCustomCaps:
    def test_custom_caps(self):
        """自定义 cap 值应生效"""
        caps = ScoreCaps(change_pct=10.0, volume_ratio=2.0, turnover_rate=10.0)
        engine = HeatScoreEngine(caps=caps)

        # change_pct=10 在 cap=10 时应为满分
        score = engine.calculate_base_score(10, 0, 0)
        assert score == pytest.approx(40.0, abs=0.01)
