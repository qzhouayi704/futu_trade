#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
吸筹/派发检测器

检测:
- 吸筹: 大量卖单但价格不跌 → 有人在低价接盘
- 派发: 大量买单但价格不涨 → 有人在高位出货
"""

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from .ticker_aggregator import AggregatedBar

logger = logging.getLogger(__name__)


@dataclass
class AbsorptionSignal:
    """吸筹/派发信号"""
    stock_code: str
    signal_type: str       # ACCUMULATION / DISTRIBUTION
    description: str
    sell_buy_ratio: float   # 卖/买比例
    price_change: float     # 价格变化%
    price: float
    confidence: float
    timestamp: float


class AbsorptionDetector:
    """吸筹/派发检测器"""

    # 卖量超过买量 N 倍，但价格跌幅不超过 M%
    VOLUME_IMBALANCE = 1.3    # 方向量差 > 30%
    PRICE_TOLERANCE = 0.3     # 价格变化容忍度 (%)
    WINDOW = 5                # 检测窗口 (bar数)

    def __init__(self):
        self._bars: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.WINDOW)
        )
        self._last_signal: dict[str, float] = {}
        self._cooldown = 600  # 10min冷却

    def reset_daily(self):
        self._bars.clear()
        self._last_signal.clear()

    def update(self, bar: AggregatedBar) -> Optional[AbsorptionSignal]:
        code = bar.stock_code
        self._bars[code].append(bar)

        window = list(self._bars[code])
        if len(window) < self.WINDOW:
            return None

        # 冷却
        if bar.timestamp - self._last_signal.get(code, 0) < self._cooldown:
            return None

        # 窗口内统计
        total_buy_vol = sum(b.buy_volume for b in window)
        total_sell_vol = sum(b.sell_volume for b in window)
        price_start = window[0].open_price
        price_end = window[-1].close_price
        price_chg = (price_end - price_start) / price_start * 100 if price_start > 0 else 0

        if total_buy_vol == 0 or total_sell_vol == 0:
            return None

        sell_buy_ratio = total_sell_vol / total_buy_vol

        # 吸筹: 卖量>买量×1.3，但价格跌幅<0.3%
        if sell_buy_ratio > self.VOLUME_IMBALANCE and price_chg > -self.PRICE_TOLERANCE:
            self._last_signal[code] = bar.timestamp
            return AbsorptionSignal(
                stock_code=code, signal_type="ACCUMULATION",
                description=(
                    f"疑似吸筹: 卖量{total_sell_vol}>{total_buy_vol}×{self.VOLUME_IMBALANCE}, "
                    f"但价格仅{price_chg:+.2f}% → 有资金承接"
                ),
                sell_buy_ratio=sell_buy_ratio, price_change=price_chg,
                price=bar.close_price, confidence=min(1.0, (sell_buy_ratio - 1) * 2),
                timestamp=bar.timestamp,
            )

        # 派发: 买量>卖量×1.3，但价格涨幅<0.3%
        buy_sell_ratio = total_buy_vol / total_sell_vol
        if buy_sell_ratio > self.VOLUME_IMBALANCE and price_chg < self.PRICE_TOLERANCE:
            self._last_signal[code] = bar.timestamp
            return AbsorptionSignal(
                stock_code=code, signal_type="DISTRIBUTION",
                description=(
                    f"疑似派发: 买量{total_buy_vol}>{total_sell_vol}×{self.VOLUME_IMBALANCE}, "
                    f"但价格仅{price_chg:+.2f}% → 有人高位出货"
                ),
                sell_buy_ratio=1/buy_sell_ratio, price_change=price_chg,
                price=bar.close_price, confidence=min(1.0, (buy_sell_ratio - 1) * 2),
                timestamp=bar.timestamp,
            )

        return None
