#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘口深度分析器

聚合5大维度分析，综合判断当前价位的涨跌动力：
1. 盘口深度（挂单分布、主动买卖识别）
2. 量价关系（放量突破/缩量反弹/高位滞涨/低位不跌）
3. VWAP 多空分水岭
4. 关键点位（支撑阻力、流动性）
5. 相对强弱（个股 vs 大盘）

维度分析逻辑见 order_book_dimensions.py
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ....utils.converters import get_last_price

# ==================== 常量 ====================

SIGNAL_BULLISH = "bullish"
SIGNAL_SLIGHTLY_BULLISH = "slightly_bullish"
SIGNAL_NEUTRAL = "neutral"
SIGNAL_SLIGHTLY_BEARISH = "slightly_bearish"
SIGNAL_BEARISH = "bearish"

SIGNAL_LABELS = {
    SIGNAL_BULLISH: "看涨",
    SIGNAL_SLIGHTLY_BULLISH: "偏多",
    SIGNAL_NEUTRAL: "中性",
    SIGNAL_SLIGHTLY_BEARISH: "偏空",
    SIGNAL_BEARISH: "看跌",
}

WEIGHTS = [0.30, 0.25, 0.20, 0.15, 0.10]
DIM_NAMES = ["盘口深度", "量价关系", "VWAP", "关键点位", "相对强弱"]


# ==================== 数据结构 ====================


@dataclass
class DimensionSignal:
    """单维度分析信号"""
    name: str
    signal: str
    score: float
    description: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderBookAnalysis:
    """盘口深度分析结果"""
    stock_code: str
    order_book_raw: Dict[str, Any]
    dimensions: List[DimensionSignal]
    total_score: float
    signal: str
    label: str
    summary: str
    updated_at: datetime = field(default_factory=datetime.now)


# ==================== 工具函数 ====================


def _score_to_signal(score: float) -> str:
    if score > 25:
        return SIGNAL_BULLISH
    if score > 10:
        return SIGNAL_SLIGHTLY_BULLISH
    if score > -10:
        return SIGNAL_NEUTRAL
    if score > -25:
        return SIGNAL_SLIGHTLY_BEARISH
    return SIGNAL_BEARISH


def _clamp(value: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


# ==================== 分析器 ====================


class OrderBookAnalyzer:
    """盘口深度分析器 - 聚合5维度分析"""

    def __init__(self, order_book_service, vwap_service, big_order_tracker):
        self._ob_svc = order_book_service
        self._vwap_svc = vwap_service
        self._big_order = big_order_tracker

    async def analyze(
        self,
        stock_code: str,
        quote: Optional[Dict[str, Any]] = None,
        market_avg_change: float = 0.0,
        sector_avg_change: float = 0.0,
    ) -> Optional[OrderBookAnalysis]:
        """执行完整的盘口深度分析"""
        from .order_book_dimensions import (
            analyze_key_levels,
            analyze_order_book_depth,
            analyze_relative_strength,
            analyze_volume_price,
            analyze_vwap,
        )

        quote = quote or {}
        current_price = get_last_price(quote)

        ob_data, vwap_data, big_data = await asyncio.gather(
            self._safe_get_order_book(stock_code),
            self._safe_get_vwap(stock_code, current_price),
            self._safe_get_big_orders(stock_code),
        )

        if ob_data is None:
            return None

        sr = self._ob_svc.get_support_resistance(ob_data)
        ob_raw = self._serialize_order_book(ob_data, sr)

        dims = [
            analyze_order_book_depth(ob_data, sr, big_data),
            analyze_volume_price(quote),
            analyze_vwap(vwap_data, quote),
            analyze_key_levels(ob_data, sr, quote),
            analyze_relative_strength(quote, market_avg_change, sector_avg_change),
        ]

        # VWAP 权重动态调整：低成交量时降低 VWAP 维度影响力
        vol_ratio = quote.get('volume_ratio', 1.0) or 1.0
        weights = list(WEIGHTS)  # 复制默认权重 [0.30, 0.25, 0.20, 0.15, 0.10]
        if vol_ratio < 0.5:
            # 量比极低：VWAP 权重从 0.20 降到 0.08，差值分给盘口深度和量价
            vwap_reduction = 0.12
            weights[2] = 0.08
            weights[0] += vwap_reduction / 2  # 盘口深度 +0.06
            weights[1] += vwap_reduction / 2  # 量价关系 +0.06

        total = sum(d.score * w for d, w in zip(dims, weights))
        total = round(_clamp(total), 1)
        signal = _score_to_signal(total)
        label = SIGNAL_LABELS[signal]
        summary = self._build_summary(dims)

        return OrderBookAnalysis(
            stock_code=stock_code,
            order_book_raw=ob_raw,
            dimensions=dims,
            total_score=total,
            signal=signal,
            label=label,
            summary=summary,
        )

    @staticmethod
    def _build_summary(dims: List[DimensionSignal]) -> str:
        bullish = [d.description for d in dims if d.score > 10]
        bearish = [d.description for d in dims if d.score < -10]
        if bullish:
            return "；".join(bullish[:3]) + "。短期有上涨动力。"
        if bearish:
            return "；".join(bearish[:3]) + "。短期有下跌压力。"
        return "买卖力量均衡，方向不明，建议观望。"

    @staticmethod
    def _serialize_order_book(ob, sr: dict) -> dict:
        return {
            'bid_levels': [
                {'price': l.price, 'volume': l.volume, 'order_count': l.order_count}
                for l in ob.bid_levels
            ],
            'ask_levels': [
                {'price': l.price, 'volume': l.volume, 'order_count': l.order_count}
                for l in ob.ask_levels
            ],
            'bid_total_volume': ob.bid_total_volume,
            'ask_total_volume': ob.ask_total_volume,
            'imbalance': ob.imbalance,
            'spread': ob.spread,
            'spread_pct': ob.spread_pct,
            'support': sr.get('support'),
            'resistance': sr.get('resistance'),
        }

    async def _safe_get_order_book(self, stock_code: str):
        try:
            return await self._ob_svc.get_order_book(stock_code)
        except Exception as e:
            logger.warning(f"获取盘口失败 {stock_code}: {e}")
            return None

    async def _safe_get_vwap(self, stock_code: str, price: float):
        try:
            if self._vwap_svc:
                return await self._vwap_svc.get_vwap(stock_code, price)
        except Exception as e:
            logger.warning(f"获取VWAP失败 {stock_code}: {e}")
        return None

    async def _safe_get_big_orders(self, stock_code: str):
        try:
            if self._big_order:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: self._big_order.track_rt_tickers([stock_code], top_n=1),
                )
                return result.get(stock_code)
        except Exception as e:
            logger.warning(f"获取大单失败 {stock_code}: {e}")
        return None
