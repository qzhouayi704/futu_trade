#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信号排名引擎 · 第 1 步：纯加权打分骨架（InflowRankingScorer）

以现有 StockScorer V2 为骨架，叠加领域因子做候选排序。本文件**只做"纯加权外壳"**：
- 输入的各因子值须由**调用方预先归一到 0-100**（本步不接线、不算因子，只做加权求和）。
- 缺失因子（值为 None / 键不存在）→ **跳过、不计其权重**，即"按剩余权重归一"（不用常数填充）。
- 门控为**乘法**：penalty_factor（惩罚系数，clamp 到 (0,1]）与 veto（一票否决 → 乘 veto_factor）。

因子键固定为 6 个：
- ``base``      —— StockScorer V2 基础分
- ``pos``       —— 价格位置（低吸/追高）
- ``flow``      —— 资金强度
- ``theme``     —— 题材热度
- ``leader``    —— 龙头属性
- ``ovn_bonus`` —— 尾盘/隔夜加成

不同信号类型（overnight / inflow / theme）各持一组权重；未知信号类型回退到 ``inflow``。

设计取舍（与 capital_trend_detector 一致）：
- 纯逻辑、无 I/O：禁止 import DB/网络/富途，只用 stdlib + 项目 utils，便于单测。
- master flag(``enabled``) 默认 False：``rank()`` 原样返回输入（保持现状顺序，零风险可逆）。

产生这些因子值的接线（调 StockScorer / price_position 等）是后续步骤，本步不碰。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# 因子键（顺序固定，遍历时按此顺序）
FACTORS = ("base", "pos", "flow", "theme", "leader", "ovn_bonus")

# 三种信号类型的默认权重（未归一，score_one 内按实际计入的权重之和归一）
DEFAULT_WEIGHTS: Dict[str, Dict[str, float]] = {
    "overnight": {"base": 40, "pos": 20, "flow": 10, "theme": 5,  "leader": 15, "ovn_bonus": 10},
    "inflow":    {"base": 35, "pos": 25, "flow": 25, "theme": 0,  "leader": 5,  "ovn_bonus": 0},
    "theme":     {"base": 30, "pos": 25, "flow": 10, "theme": 25, "leader": 5,  "ovn_bonus": 0},
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _default_weights() -> Dict[str, Dict[str, float]]:
    """深拷贝默认权重表，避免 dataclass 实例共享同一份可变字典。"""
    return {sig: dict(factors) for sig, factors in DEFAULT_WEIGHTS.items()}


@dataclass
class InflowRankingConfig:
    """排名引擎配置。权重为 signal_type → {factor: weight} 两层字典。"""

    enabled: bool = False
    mode: str = "shadow"          # shadow / live
    top_n: int = 12
    veto_factor: float = 0.15     # veto 命中时乘此系数
    weights: Dict[str, Dict[str, float]] = field(default_factory=_default_weights)

    @classmethod
    def from_env(cls) -> "InflowRankingConfig":
        from ....utils import env_flag

        cfg = cls(
            enabled=env_flag("SIGNAL_RANK_ENABLED", False),
            mode=os.environ.get("SIGNAL_RANK_MODE", "shadow"),
            top_n=_env_int("SIGNAL_RANK_TOP_N", 12),
            veto_factor=_env_float("SIGNAL_RANK_VETO_FACTOR", 0.15),
            weights=_default_weights(),
        )
        # 单个权重覆盖：SIGNAL_RANK_W_{FACTOR}_{SIGNAL}（大写），无则保留默认
        for signal, factors in cfg.weights.items():
            for factor in FACTORS:
                key = "SIGNAL_RANK_W_{f}_{s}".format(f=factor.upper(), s=signal.upper())
                factors[factor] = _env_float(key, factors.get(factor, 0.0))
        return cfg


class InflowRankingScorer:
    """纯加权打分器：加权求和 + 缺失因子按剩余权重归一 + 乘法门控。

    因子值须由调用方归一到 0-100；缺失（None）按剩余权重归一；
    veto / penalty_factor 为乘法门控。``enabled`` 关闭时 ``rank`` 原样返回。
    """

    def __init__(self, config: Optional[InflowRankingConfig] = None) -> None:
        self.cfg = config or InflowRankingConfig.from_env()

    def score_one(self, metrics: dict, signal_type: str) -> float:
        """对单个候选算加权分（0-100，保留两位）。

        Args:
            metrics: 因子字典，各因子已归一到 0-100；可含 ``penalty_factor``/``veto``。
            signal_type: overnight / inflow / theme；未知回退 inflow。
        """
        weights = self.cfg.weights.get(signal_type) or self.cfg.weights.get("inflow", {})

        num = 0.0
        den = 0.0
        for factor in FACTORS:
            w = weights.get(factor, 0.0)
            if w <= 0:
                continue
            value = metrics.get(factor)
            if value is None:
                continue  # 缺失 → 跳过、不计权重（按剩余归一）
            num += float(value) * w
            den += w

        weighted = (num / den) if den > 0 else 50.0  # 全缺 → 中性 50

        # 乘法门控：penalty_factor clamp 到 (0,1]；veto 命中乘 veto_factor
        pf = metrics.get("penalty_factor", 1.0)
        if pf is None:
            pf = 1.0
        pf = _clamp(float(pf), 0.0, 1.0)
        veto = bool(metrics.get("veto", False))
        final = weighted * pf * (self.cfg.veto_factor if veto else 1.0)

        return round(_clamp(final, 0.0, 100.0), 2)

    def rank(self, candidates: List[dict], signal_type: str) -> List[dict]:
        """按加权分降序稳定排序；未启用时原样返回候选（零风险）。

        candidate 的因子可放在 ``c["metrics"]`` 或直接放在 c 上。
        """
        if not self.cfg.enabled:
            return candidates

        for c in candidates:
            metrics = c.get("metrics", c)
            c["rank_score"] = self.score_one(metrics, signal_type)

        # Python sorted 稳定：同分维持原相对顺序
        return sorted(candidates, key=lambda c: c["rank_score"], reverse=True)
