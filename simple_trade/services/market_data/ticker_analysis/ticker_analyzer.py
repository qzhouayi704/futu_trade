#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐笔成交分析器

聚合4大维度分析，综合判断当前价位的真实买卖力量：
1. 主动买卖力量（主动买入 vs 主动卖出）
2. 大单成交占比（主力资金动向）
3. 成交密集价位（支撑位与阻力位）
4. 成交节奏变化（放量/缩量趋势）

维度分析逻辑见 ticker_dimensions.py
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..order_book.order_book_analyzer import SIGNAL_LABELS, _score_to_signal, _clamp
from .ticker_service import TickerService

logger = logging.getLogger(__name__)


# ==================== 数据结构 ====================


@dataclass
class TickerDimensionSignal:
    """成交分析维度信号"""
    name: str                                       # 维度名称
    signal: str                                     # bullish / slightly_bullish / neutral / slightly_bearish / bearish
    score: float                                    # -100 到 100
    description: str                                # 描述文字
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TickerAnalysis:
    """成交分析完整结果"""
    stock_code: str
    dimensions: List[TickerDimensionSignal]          # 4个维度
    total_score: float                               # 综合评分 -100~100
    signal: str                                      # 综合信号
    label: str                                       # 中文标签
    summary: str                                     # 摘要文字
    updated_at: datetime = field(default_factory=datetime.now)


# ==================== 分析器 ====================


class TickerAnalyzer:
    """逐笔成交分析器 - 聚合4维度分析"""

    def __init__(self, ticker_service: TickerService, min_order_amount: float = 100000):
        """
        Args:
            ticker_service: 逐笔成交数据服务
            min_order_amount: 大单阈值（复用 BigOrderTracker 配置）
        """
        self._ticker_svc = ticker_service
        self._min_order_amount = min_order_amount

    async def analyze(
        self, stock_code: str, current_price: float = 0.0,
        quote: Optional[Dict[str, Any]] = None,
        avg_daily_turnover: float = 0.0,
        scalping_delta: Optional[float] = None,
        scalping_delta_direction: Optional[str] = None,
    ) -> Optional[TickerAnalysis]:
        """执行完整的成交分析

        Args:
            stock_code: 股票代码
            current_price: 当前价格（用于密集价位的支撑/阻力判断）
            quote: 实时报价快照（含 turnover、change_pct 等）
            avg_daily_turnover: 历史日均成交额（从K线数据库计算）
            scalping_delta: Scalping Delta 净动量（可选，来自 StateManager）
            scalping_delta_direction: Scalping Delta 方向（可选）

        Returns:
            TickerAnalysis 或 None（数据不可用时）
        """
        from .ticker_dimensions import (
            analyze_active_buy_sell,
            analyze_big_order_ratio,
        )
        from .ticker_dimensions_ext import (
            analyze_volume_clusters,
            analyze_trade_rhythm,
        )
        from .volume_credibility import analyze_volume_credibility

        ticker_data = await self._ticker_svc.get_ticker_data(stock_code)
        if ticker_data is None or not ticker_data.records:
            return None

        records = ticker_data.records
        quote = quote or {}

        # 大单阈值动态化：基于日均成交额的 0.1%，范围 [5万, 100万]
        if avg_daily_turnover > 0:
            dynamic_threshold = max(50000, min(avg_daily_turnover * 0.001, 1000000))
        else:
            dynamic_threshold = self._min_order_amount

        # 执行5个维度分析
        dims = [
            analyze_active_buy_sell(
                records,
                scalping_delta=scalping_delta,
                scalping_delta_direction=scalping_delta_direction,
            ),
            analyze_big_order_ratio(records, dynamic_threshold),
            analyze_volume_clusters(records, current_price),
            analyze_trade_rhythm(records),
            analyze_volume_credibility(
                stock_code=stock_code,
                today_turnover=quote.get("turnover", 0.0),
                avg_daily_turnover=avg_daily_turnover,
                change_pct=quote.get("change_pct", 0.0),
            ),
        ]

        # 计算综合评分（带可信度衰减）
        total = self._calc_weighted_score(dims)
        total = round(_clamp(total), 1)
        signal = _score_to_signal(total)
        label = SIGNAL_LABELS[signal]
        summary = self._build_summary(dims)

        return TickerAnalysis(
            stock_code=stock_code,
            dimensions=dims,
            total_score=total,
            signal=signal,
            label=label,
            summary=summary,
        )

    @staticmethod
    def _calc_weighted_score(dims: List[TickerDimensionSignal]) -> float:
        """计算带可信度衰减的综合评分

        当量能可信度为负分时，对主动买卖维度的正分做衰减，
        避免缩量拉升时给出过于乐观的多头信号。
        """
        if not dims:
            return 0.0

        # 找到关键维度
        credibility_dim = next((d for d in dims if d.name == "量能可信度"), None)
        active_dim = next((d for d in dims if d.name == "主动买卖"), None)

        weights = {d.name: 1.0 for d in dims}

        # 量能不足时衰减主动买卖的正分权重
        if (credibility_dim and active_dim
                and credibility_dim.score < -20 and active_dim.score > 10):
            weights["主动买卖"] = 0.5

        total_weight = sum(weights[d.name] for d in dims)
        weighted_sum = sum(d.score * weights[d.name] for d in dims)
        return weighted_sum / total_weight if total_weight > 0 else 0.0

    @staticmethod
    def _build_summary(dims: List[TickerDimensionSignal]) -> str:
        """根据各维度结果生成摘要"""
        credibility_dim = next((d for d in dims if d.name == "量能可信度"), None)
        active_dim = next((d for d in dims if d.name == "主动买卖"), None)

        bullish = [d.description for d in dims if d.score > 10]
        bearish = [d.description for d in dims if d.score < -10]

        # 诱多警告优先
        if (credibility_dim and active_dim
                and credibility_dim.score < -20 and active_dim.score > 10):
            trap_warning = credibility_dim.details.get("trap_warning", "")
            if trap_warning:
                return f"⚠️ {trap_warning}。成交面信号可信度低。"

        if bullish:
            return "；".join(bullish[:3]) + "。成交面偏多。"
        if bearish:
            return "；".join(bearish[:3]) + "。成交面偏空。"
        return "成交买卖力量均衡，方向不明。"
