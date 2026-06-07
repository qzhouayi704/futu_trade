#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘后优选 — 数据模型"""

from dataclasses import dataclass, field
from typing import Dict, List, Any


@dataclass
class OvernightCandidate:
    """盘后优选候选股"""
    stock_code: str
    stock_name: str
    total_score: float = 0.0        # 0-100 综合评分
    rank: int = 0
    verdict: str = ""               # "强烈推荐" / "推荐" / "可关注"
    category: str = ""              # "趋势反转" / "资金吸筹" / "强势延续" / "综合优选"
    # 各维度得分
    scores: Dict[str, float] = field(default_factory=dict)
    # 推荐理由
    reasons: List[str] = field(default_factory=list)
    # 关键指标快照
    key_metrics: Dict[str, Any] = field(default_factory=dict)
    # 排除标记
    excluded: bool = False
    exclude_reason: str = ""
    # 降权标记
    penalty_factor: float = 1.0     # 1.0=无降权, 0.5=降权50%
    penalty_reasons: List[str] = field(default_factory=list)
    # R5候选标记
    r5_candidate: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'total_score': round(self.total_score, 1),
            'rank': self.rank,
            'verdict': self.verdict,
            'category': self.category,
            'scores': {k: round(v, 1) if isinstance(v, (int, float)) else v for k, v in self.scores.items()},
            'reasons': self.reasons,
            'key_metrics': self.key_metrics,
            'excluded': self.excluded,
            'exclude_reason': self.exclude_reason,
            'penalty_factor': self.penalty_factor,
            'penalty_reasons': self.penalty_reasons,
            'r5_candidate': self.r5_candidate,
        }


# 评分权重配置
WEIGHTS = {
    # Tier 1 - 核心 (55%)
    'capital_continuity': 0.20,   # P1: R11 资金持续流入
    'trend_reversal': 0.20,       # P2: 趋势反转买入信号
    'net_inflow_position': 0.15,  # P3: R1 资金净流入建仓
    # Tier 2 - 确认 (30%)
    'capital_score_v2': 0.08,     # P4: 资金评分v2
    'big_order_strength': 0.07,   # P5: 大单买入强度
    'kline_profile': 0.07,        # P6: K线画像
    'quickscan_verdict': 0.08,    # P7: QuickScan判定
    # Tier 3 - 辅助 (15%)
    'leader_bonus': 0.05,         # P8: 龙头板块
    'volume_price_fit': 0.05,     # P9: 量价配合
    'opportunity_score': 0.05,    # P10: 机会评分
}
