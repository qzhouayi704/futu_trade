#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""决策助理数据模型"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class HealthLevel(str, Enum):
    """持仓健康度等级"""
    STRONG = "STRONG"
    NEUTRAL = "NEUTRAL"
    WEAK = "WEAK"
    DANGER = "DANGER"


class AdviceType(str, Enum):
    """建议类型"""
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    CLEAR = "CLEAR"
    SWAP = "SWAP"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    ADD_POSITION = "ADD_POSITION"


class Urgency(int, Enum):
    """紧急程度"""
    LOW = 1
    MEDIUM = 5
    HIGH = 8
    CRITICAL = 10


# 建议类型的中文标签
ADVICE_TYPE_LABELS: Dict[AdviceType, str] = {
    AdviceType.HOLD: "继续持有",
    AdviceType.REDUCE: "减仓",
    AdviceType.CLEAR: "清仓",
    AdviceType.SWAP: "换仓",
    AdviceType.STOP_LOSS: "止损",
    AdviceType.TAKE_PROFIT: "止盈",
    AdviceType.ADD_POSITION: "加仓",
}

# 健康等级的中文标签
HEALTH_LEVEL_LABELS: Dict[HealthLevel, str] = {
    HealthLevel.STRONG: "强势",
    HealthLevel.NEUTRAL: "中性",
    HealthLevel.WEAK: "弱势",
    HealthLevel.DANGER: "危险",
}


@dataclass
class PositionHealth:
    """持仓健康度评估结果"""
    stock_code: str
    stock_name: str
    health_level: HealthLevel
    score: float                          # 0-100 健康度评分
    profit_pct: float                     # 当前盈亏比例 (%)
    holding_days: int = 0                 # 持有天数
    turnover_rate: float = 0.0            # 当日换手率 (%)
    amplitude: float = 0.0               # 当日振幅 (%)
    volume_ratio: float = 0.0            # 量比（相对5日均量）
    trend: str = "SIDEWAYS"              # UP / DOWN / SIDEWAYS
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'health_level': self.health_level.value,
            'score': round(self.score, 1),
            'profit_pct': round(self.profit_pct, 2),
            'holding_days': self.holding_days,
            'turnover_rate': round(self.turnover_rate, 2),
            'amplitude': round(self.amplitude, 2),
            'volume_ratio': round(self.volume_ratio, 2),
            'trend': self.trend,
            'reasons': self.reasons,
        }


@dataclass
class DecisionAdvice:
    """决策建议"""
    id: str
    advice_type: AdviceType
    urgency: Urgency
    title: str
    description: str
    # 卖出侧
    sell_stock_code: Optional[str] = None
    sell_stock_name: Optional[str] = None
    sell_price: Optional[float] = None
    # 买入侧
    buy_stock_code: Optional[str] = None
    buy_stock_name: Optional[str] = None
    buy_price: Optional[float] = None
    # 数量建议
    quantity: Optional[int] = None
    sell_ratio: Optional[float] = None    # 卖出比例 (0~1)
    # 关联数据
    position_health: Optional[PositionHealth] = None
    # 元数据
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    is_dismissed: bool = False
    # AI 分析结果（可选）
    ai_analysis: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            'id': self.id,
            'advice_type': self.advice_type.value,
            'advice_type_label': ADVICE_TYPE_LABELS.get(self.advice_type, ''),
            'urgency': self.urgency.value,
            'title': self.title,
            'description': self.description,
            'sell_stock_code': self.sell_stock_code,
            'sell_stock_name': self.sell_stock_name,
            'sell_price': self.sell_price,
            'buy_stock_code': self.buy_stock_code,
            'buy_stock_name': self.buy_stock_name,
            'buy_price': self.buy_price,
            'quantity': self.quantity,
            'sell_ratio': self.sell_ratio,
            'created_at': self.created_at,
            'is_dismissed': self.is_dismissed,
        }
        if self.position_health:
            result['position_health'] = self.position_health.to_dict()
        if self.ai_analysis:
            result['ai_analysis'] = self.ai_analysis
        return result


@dataclass
class EvaluationContext:
    """评估上下文 - 封装评估所需的全部输入数据，消除数据泥团"""
    positions: List[Dict[str, Any]]
    quotes: List[Dict[str, Any]]
    signals: List[Dict[str, Any]]
    kline_cache: Dict[str, List]
    plate_data: Dict[str, List[str]] = field(default_factory=dict)  # stock_code → [板块名列表]

    @property
    def quotes_map(self) -> Dict[str, Dict[str, Any]]:
        """按股票代码索引的报价字典"""
        return {q.get('code', ''): q for q in self.quotes}

    @property
    def has_quotes(self) -> bool:
        return len(self.quotes) > 0

    @property
    def has_klines(self) -> bool:
        return len(self.kline_cache) > 0
