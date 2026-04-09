#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemini 量化分析师数据模型"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class TriggerType(str, Enum):
    """触发类型"""
    PRICE_SURGE = "PRICE_SURGE"           # 1分钟内拉升2%+
    PRICE_PLUNGE = "PRICE_PLUNGE"         # 1分钟内下跌2%+
    BREAKING_NEWS = "BREAKING_NEWS"       # 突发新闻
    HIGH_URGENCY_ADVICE = "HIGH_URGENCY"  # 规则引擎高紧急度建议
    CAPITAL_ANOMALY = "CAPITAL_ANOMALY"   # 资金异动
    MANUAL = "MANUAL"                     # 手动触发


class AnalystAction(str, Enum):
    """分析师建议动作"""
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"
    WAIT = "WAIT"


@dataclass
class TriggerEvent:
    """触发事件"""
    trigger_type: TriggerType
    stock_code: str
    stock_name: str
    reason: str
    priority: int                 # 1-10，越高越优先
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class MarketContext:
    """市场上下文"""
    timestamp: datetime
    trading_session: str          # "MORNING" / "AFTERNOON" / "LUNCH" / "PRE_MARKET" / "AFTER_HOURS"
    minutes_since_open: int
    market_sentiment: str         # "BULLISH" / "BEARISH" / "NEUTRAL"
    hsi_change_pct: float = 0.0
    sector_sentiment: Dict[str, str] = field(default_factory=dict)


@dataclass
class NewsSummary:
    """过滤后的核心新闻摘要"""
    has_breaking_news: bool = False
    sentiment: str = "NEUTRAL"    # "POSITIVE" / "NEGATIVE" / "NEUTRAL"
    sentiment_score: float = 0.0  # -1.0 到 1.0
    key_facts: List[str] = field(default_factory=list)  # 核心事实（最多3条）
    related_stocks: List[str] = field(default_factory=list)


@dataclass
class AnalystInput:
    """分析师输入数据包"""
    stock_code: str
    stock_name: str
    trigger_type: TriggerType
    trigger_reason: str
    market_context: MarketContext
    technical: Any                # TechnicalIndicators
    position_health: Dict = field(default_factory=dict)
    news: Optional[NewsSummary] = None
    rule_advice: Optional[Dict] = None
    # 增强数据（供 Gemini 综合分析）
    kline_summary: Optional[str] = None          # 近12日K线走势摘要
    sector_info: Optional[str] = None            # 所属板块及板块表现
    capital_flow_summary: Optional[str] = None   # 近期资金流向摘要


@dataclass
class AnalystOutput:
    """分析师输出结果"""
    stock_code: str
    stock_name: str
    # Gemini 原始输出
    catalyst_impact: str = "Neutral"       # "Bullish" / "Bearish" / "Neutral"
    smart_money_alignment: str = "Unclear"  # "Confirming" / "Diverging" / "Unclear"
    is_priced_in: bool = False
    alpha_signal_score: float = 0.0        # -1.0 到 1.0
    # 建议
    action: AnalystAction = AnalystAction.WAIT
    confidence: float = 0.0                # 0-1
    reasoning: str = ""                    # 分析推理
    key_factors: List[str] = field(default_factory=list)
    risk_warning: Optional[str] = None
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    time_horizon: str = "INTRADAY"
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'catalyst_impact': self.catalyst_impact,
            'smart_money_alignment': self.smart_money_alignment,
            'is_priced_in': self.is_priced_in,
            'alpha_signal_score': round(self.alpha_signal_score, 2),
            'action': self.action.value,
            'confidence': round(self.confidence, 2),
            'reasoning': self.reasoning,
            'key_factors': self.key_factors,
            'risk_warning': self.risk_warning,
            'target_price': self.target_price,
            'stop_loss_price': self.stop_loss_price,
            'time_horizon': self.time_horizon,
            'created_at': self.created_at.isoformat(),
        }


# 需要延迟导入避免循环依赖
from typing import Any  # noqa: E402
