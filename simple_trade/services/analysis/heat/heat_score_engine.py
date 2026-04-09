#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一热度评分引擎

将 StockHeatCalculator 和 LeaderStockFilter 中的冗余评分逻辑
统一到一个模块中，提供三种评分方法：
- 基础评分（热门股票）
- 龙头评分（龙头股识别）
- 板块热度评分（板块排序）
"""

import logging
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreCaps:
    """归一化 cap 值配置"""

    change_pct: float = 20.0       # 涨幅：20% 为满分
    volume_ratio: float = 5.0      # 量比：5 倍为满分
    turnover_rate: float = 20.0    # 换手率：20% 为满分
    up_ratio: float = 1.0          # 涨跌比：100% 为满分
    avg_change_pct: float = 10.0   # 平均涨幅：10% 为满分
    big_rise_ratio: float = 1.0    # 大涨股占比：100% 为满分
    net_inflow_ratio: float = 1.0  # 资金净流入：100% 为满分
    consecutive_days: float = 5.0  # 连续强势天数：5 天为满分


class HeatScoreEngine:
    """统一热度评分引擎，消除冗余评分逻辑

    所有评分方法输出范围均为 0-100。
    """

    def __init__(self, caps: ScoreCaps | None = None):
        self.caps = caps or ScoreCaps()
        self.logger = logging.getLogger(__name__)

    # ── 归一化 ──────────────────────────────────────────────

    def normalize(self, value: float, cap: float) -> float:
        """将 value 归一化到 0-100 范围

        Args:
            value: 原始值（负值视为 0）
            cap: 满分对应的值（必须 > 0）

        Returns:
            0-100 之间的浮点数
        """
        if cap <= 0:
            return 0.0
        return min(max(value, 0.0) / cap, 1.0) * 100

    # ── 基础评分 ────────────────────────────────────────────

    def calculate_base_score(
        self,
        change_pct: float,
        volume_ratio: float,
        turnover_rate: float,
    ) -> float:
        """基础评分：涨幅×0.4 + 量比×0.3 + 换手率×0.3

        用于热门股票筛选排序。

        Args:
            change_pct: 涨跌幅（%），取绝对值归一化
            volume_ratio: 量比
            turnover_rate: 换手率（%）

        Returns:
            0-100 之间的评分
        """
        change_score = self.normalize(abs(change_pct), self.caps.change_pct)
        volume_score = self.normalize(volume_ratio, self.caps.volume_ratio)
        turnover_score = self.normalize(turnover_rate, self.caps.turnover_rate)

        score = (
            change_score * 0.4
            + volume_score * 0.3
            + turnover_score * 0.3
        )
        return round(score, 2)

    # ── 龙头评分 ────────────────────────────────────────────

    def calculate_leader_score(
        self,
        change_pct: float,
        volume_ratio: float,
        turnover_rate: float,
        rank_in_plate: int,
        plate_size: int,
        consecutive_strong_days: int,
        net_inflow_ratio: float = 0.0,
    ) -> float:
        """龙头评分：排名分×30% + 量比分×20% + 换手率分×15%
                    + 连续强势分×20% + 资金净流入分×15%

        Args:
            change_pct: 涨跌幅（%），用于计算排名分的辅助参考
            volume_ratio: 量比
            turnover_rate: 换手率（%）
            rank_in_plate: 板块内涨幅排名（1 = 第一名）
            plate_size: 板块内股票总数
            consecutive_strong_days: 连续强势天数
            net_inflow_ratio: 资金净流入占比（0-1）

        Returns:
            0-100 之间的评分
        """
        rank_score = self._calculate_rank_score(rank_in_plate, plate_size)
        volume_score = self.normalize(volume_ratio, self.caps.volume_ratio)
        turnover_score = self.normalize(turnover_rate, self.caps.turnover_rate)
        consecutive_score = self.normalize(
            consecutive_strong_days, self.caps.consecutive_days
        )
        inflow_score = self.normalize(
            net_inflow_ratio, self.caps.net_inflow_ratio
        )

        score = (
            rank_score * 0.30
            + volume_score * 0.20
            + turnover_score * 0.15
            + consecutive_score * 0.20
            + inflow_score * 0.15
        )
        return round(score, 2)

    # ── 板块热度评分 ────────────────────────────────────────

    def calculate_plate_heat(
        self,
        up_ratio: float,
        avg_change_pct: float,
        big_rise_ratio: float,
        net_inflow_ratio: float,
    ) -> float:
        """板块热度：涨跌比×30% + 平均涨幅×25% + 大涨股占比×25%
                    + 资金净流入×20%

        Args:
            up_ratio: 涨跌比（0-1）
            avg_change_pct: 板块平均涨幅（%）
            big_rise_ratio: 大涨股占比（0-1，涨幅>3%）
            net_inflow_ratio: 资金净流入占比（0-1）

        Returns:
            0-100 之间的评分
        """
        up_score = self.normalize(up_ratio, self.caps.up_ratio)
        avg_score = self.normalize(avg_change_pct, self.caps.avg_change_pct)
        big_rise_score = self.normalize(big_rise_ratio, self.caps.big_rise_ratio)
        inflow_score = self.normalize(
            net_inflow_ratio, self.caps.net_inflow_ratio
        )

        score = (
            up_score * 0.30
            + avg_score * 0.25
            + big_rise_score * 0.25
            + inflow_score * 0.20
        )
        return round(score, 2)

    # ── 内部方法 ────────────────────────────────────────────

    @staticmethod
    def _calculate_rank_score(rank_in_plate: int, plate_size: int) -> float:
        """计算排名分：(plate_size - rank + 1) / plate_size * 100

        排名第 1 得分最高，排名越靠后得分越低。
        """
        if plate_size <= 0 or rank_in_plate <= 0:
            return 0.0
        # 确保 rank 不超过 plate_size
        rank = min(rank_in_plate, plate_size)
        return (plate_size - rank + 1) / plate_size * 100
