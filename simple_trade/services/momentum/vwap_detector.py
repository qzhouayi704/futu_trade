#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VWAP偏离检测器

检测:
- VWAP回踩买入（经典形态）
- VWAP跌破（趋势转弱）
- 超买/超卖
"""

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from .ticker_aggregator import AggregatedBar

logger = logging.getLogger(__name__)


@dataclass
class VWAPSignal:
    """VWAP信号"""
    stock_code: str
    signal_type: str       # VWAP_BOUNCE / VWAP_BREAK / OVERBOUGHT / OVERSOLD
    description: str
    vwap: float
    deviation: float       # 偏离率%
    price: float
    confidence: float
    timestamp: float


class VWAPDetector:
    """VWAP偏离检测器"""

    OVERBOUGHT = 1.5       # 偏离>1.5%视为超买
    OVERSOLD = -1.5        # 偏离<-1.5%视为超卖
    BOUNCE_ZONE = 0.3      # 回踩区间: VWAP±0.3%

    def __init__(self, history_size: int = 30):
        self._dev_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._prev_side: dict[str, str] = {}  # 上一次在VWAP的哪一侧

    def reset_daily(self):
        self._dev_history.clear()
        self._prev_side.clear()

    def update(self, bar: AggregatedBar) -> Optional[VWAPSignal]:
        code = bar.stock_code
        if bar.vwap <= 0:
            return None

        dev = (bar.close_price - bar.vwap) / bar.vwap * 100
        history = self._dev_history[code]
        history.append(dev)

        if len(history) < 3:
            self._prev_side[code] = "ABOVE" if dev > 0 else "BELOW"
            return None

        prev = self._prev_side.get(code, "ABOVE" if dev > 0 else "BELOW")
        current_side = "ABOVE" if dev > 0 else "BELOW"

        signal = None

        # VWAP回踩买入: 从上方接近VWAP，且BSR > 1
        if (prev == "ABOVE" and abs(dev) < self.BOUNCE_ZONE
                and bar.bsr > 1.0 and list(history)[-2] > self.BOUNCE_ZONE):
            signal = VWAPSignal(
                stock_code=code, signal_type="VWAP_BOUNCE",
                description=f"VWAP回踩: 价格{bar.close_price:.2f}接近VWAP({bar.vwap:.2f}), BSR={bar.bsr:.2f}",
                vwap=bar.vwap, deviation=dev, price=bar.close_price,
                confidence=0.7, timestamp=bar.timestamp,
            )

        # VWAP跌破: 从上方跌到下方
        elif prev == "ABOVE" and current_side == "BELOW" and dev < -0.3 and bar.bsr < 0.9:
            signal = VWAPSignal(
                stock_code=code, signal_type="VWAP_BREAK",
                description=f"跌破VWAP: 价格{bar.close_price:.2f}<VWAP({bar.vwap:.2f}), 偏离{dev:.1f}%",
                vwap=bar.vwap, deviation=dev, price=bar.close_price,
                confidence=0.7, timestamp=bar.timestamp,
            )

        # 超买
        elif dev > self.OVERBOUGHT:
            signal = VWAPSignal(
                stock_code=code, signal_type="OVERBOUGHT",
                description=f"超买: 价格高于VWAP {dev:.1f}%, 回调风险增大",
                vwap=bar.vwap, deviation=dev, price=bar.close_price,
                confidence=min(1.0, dev / 3), timestamp=bar.timestamp,
            )

        # 超卖
        elif dev < self.OVERSOLD:
            signal = VWAPSignal(
                stock_code=code, signal_type="OVERSOLD",
                description=f"超卖: 价格低于VWAP {abs(dev):.1f}%, 反弹可能增大",
                vwap=bar.vwap, deviation=dev, price=bar.close_price,
                confidence=min(1.0, abs(dev) / 3), timestamp=bar.timestamp,
            )

        self._prev_side[code] = current_side
        return signal
