#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合多空分析器

融合挂单分析（5维度）与成交分析（4维度），
输出 9 维度综合多空判断。

权重分配：挂单 40% / 成交 60%（真实成交更可靠）
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..order_book.order_book_analyzer import (
    DimensionSignal,
    OrderBookAnalyzer,
    SIGNAL_LABELS,
    _clamp,
    _score_to_signal,
)
from .ticker_analyzer import TickerAnalyzer, TickerDimensionSignal

from ....utils.converters import get_last_price

logger = logging.getLogger(__name__)


# ==================== 数据结构 ====================


@dataclass
class CombinedAnalysis:
    """综合多空分析结果"""
    stock_code: str
    order_book_dimensions: List[DimensionSignal]       # 5个挂单维度
    ticker_dimensions: List[TickerDimensionSignal]     # 4个成交维度
    order_book_score: float                            # 挂单分析评分
    ticker_score: float                                # 成交分析评分
    combined_score: float                              # 加权综合评分 -100~100
    signal: str                                        # 综合信号
    label: str                                         # 中文标签
    summary: str                                       # 摘要（含矛盾提示）
    has_contradiction: bool                            # 挂单与成交方向是否矛盾
    ticker_available: bool                             # 成交数据是否可用
    updated_at: datetime = field(default_factory=datetime.now)


# ==================== 综合分析器 ====================


class CombinedAnalyzer:
    """综合多空分析器 - 融合挂单 + 成交"""

    ORDER_BOOK_WEIGHT = 0.4
    TICKER_WEIGHT = 0.6

    def __init__(
        self,
        order_book_analyzer: OrderBookAnalyzer,
        ticker_analyzer: TickerAnalyzer,
    ):
        self._ob_analyzer = order_book_analyzer
        self._ticker_analyzer = ticker_analyzer

    async def analyze(
        self,
        stock_code: str,
        quote: Optional[Dict[str, Any]] = None,
        market_avg_change: float = 0.0,
        avg_daily_turnover: float = 0.0,
        sector_avg_change: float = 0.0,
    ) -> Optional[CombinedAnalysis]:
        """执行综合分析（挂单 + 成交）

        Args:
            stock_code: 股票代码
            quote: 行情快照（含 last_price / cur_price）
            market_avg_change: 大盘平均涨跌幅
            avg_daily_turnover: 历史日均成交额（用于量能可信度维度）
            sector_avg_change: 板块平均涨跌幅（0 表示不可用，降级为大盘基准）

        Returns:
            CombinedAnalysis 或 None（挂单数据不可用时）
        """
        quote = quote or {}
        current_price = get_last_price(quote)

        # 从 StateManager 获取 Scalping 指标（可选消费，无数据时不影响分析）
        scalping_delta = None
        scalping_delta_direction = None
        try:
            from ....core.state import get_state_manager
            metrics = get_state_manager().get_scalping_metrics(stock_code)
            if metrics is not None:
                scalping_delta = metrics.delta
                scalping_delta_direction = metrics.delta_direction
        except Exception:
            pass  # StateManager 不可用时静默降级

        # 并行调用挂单分析和成交分析
        ob_result, ticker_result = await asyncio.gather(
            self._ob_analyzer.analyze(
                stock_code, quote, market_avg_change, sector_avg_change,
            ),
            self._ticker_analyzer.analyze(
                stock_code, current_price, quote=quote,
                avg_daily_turnover=avg_daily_turnover,
                scalping_delta=scalping_delta,
                scalping_delta_direction=scalping_delta_direction,
            ),
        )

        # 挂单分析返回 None → 整体返回 None
        if ob_result is None:
            return None

        ob_score = ob_result.total_score
        ob_dims = ob_result.dimensions

        # 成交分析返回 None → 降级为仅挂单分析
        if ticker_result is None:
            combined_score = ob_score
            ticker_available = False
            ticker_score = 0.0
            ticker_dims: List[TickerDimensionSignal] = []
            has_contradiction = False
        else:
            ticker_score = ticker_result.total_score
            ticker_dims = ticker_result.dimensions
            ticker_available = True
            has_contradiction = self._check_contradiction(ob_score, ticker_score)

            # 权重自适应：根据流动性（spread_pct）动态调整
            ob_w, tk_w = self._adaptive_weights(ob_result)
            combined_score = ob_score * ob_w + ticker_score * tk_w

            # 矛盾信号衰减：矛盾时综合评分乘以 0.3（向 0 收敛）
            if has_contradiction:
                combined_score *= 0.3

        combined_score = round(_clamp(combined_score), 1)
        signal = _score_to_signal(combined_score)
        label = SIGNAL_LABELS[signal]
        summary = self._build_summary(
            ob_result.summary, ticker_result.summary if ticker_result else None,
            has_contradiction, ticker_available,
        )

        return CombinedAnalysis(
            stock_code=stock_code,
            order_book_dimensions=ob_dims,
            ticker_dimensions=ticker_dims,
            order_book_score=ob_score,
            ticker_score=ticker_score,
            combined_score=combined_score,
            signal=signal,
            label=label,
            summary=summary,
            has_contradiction=has_contradiction,
            ticker_available=ticker_available,
        )

    @staticmethod
    def _adaptive_weights(ob_result) -> tuple:
        """根据流动性动态调整挂单/成交权重

        低流动性（spread > 0.5%）→ 挂单权重降到 0.25（易被操纵）
        高流动性（spread < 0.1%）→ 挂单权重升到 0.50（盘口更可靠）
        """
        spread_pct = 0.0
        if ob_result and ob_result.order_book_raw:
            spread_pct = ob_result.order_book_raw.get('spread_pct', 0.0) or 0.0

        if spread_pct > 0.5:
            ob_w = 0.25
        elif spread_pct < 0.1:
            ob_w = 0.50
        else:
            ob_w = CombinedAnalyzer.ORDER_BOOK_WEIGHT
        return ob_w, 1.0 - ob_w

    @staticmethod
    def _check_contradiction(ob_score: float, ticker_score: float) -> bool:
        """检测挂单与成交方向是否矛盾

        条件：符号相反（一正一负）且绝对值均 > 10
        """
        if ob_score * ticker_score >= 0:
            return False
        return abs(ob_score) > 10 and abs(ticker_score) > 10

    @staticmethod
    def _build_summary(
        ob_summary: str,
        ticker_summary: Optional[str],
        has_contradiction: bool,
        ticker_available: bool,
    ) -> str:
        """生成综合摘要"""
        if not ticker_available:
            return f"{ob_summary}（成交数据暂不可用，仅基于挂单分析）"
        if has_contradiction:
            return f"挂单与成交方向矛盾，需谨慎。挂单: {ob_summary} 成交: {ticker_summary}"
        parts = []
        if ob_summary:
            parts.append(ob_summary)
        if ticker_summary:
            parts.append(ticker_summary)
        return " ".join(parts) if parts else "综合分析无明显方向。"
