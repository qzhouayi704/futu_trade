#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Delta 动量检测器

基于累积Delta分析多空力量趋势:
- CumDelta拐头检测
- 价量背离检测
- Delta极端值检测
"""

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from .ticker_aggregator import AggregatedBar

logger = logging.getLogger(__name__)


@dataclass
class DeltaSignal:
    """Delta信号"""
    stock_code: str
    signal_type: str          # DELTA_TURN / DIVERGENCE / EXTREME_DELTA
    description: str
    delta: int
    cum_delta: int
    peak_cum_delta: int
    price: float
    confidence: float
    timestamp: float


class DeltaDetector:
    """Delta动量检测器"""

    # 配置
    TURN_THRESHOLD = 0.30      # CumDelta从峰值回落30%视为拐头
    EXTREME_SIGMA = 2.0        # Delta超过2个标准差视为极端值
    DIVERGENCE_BARS = 5        # 价量背离检测窗口

    def __init__(self, history_size: int = 60):
        self._delta_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._price_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._peak_cum_delta: dict[str, int] = defaultdict(int)
        self._trough_cum_delta: dict[str, int] = defaultdict(int)
        self._turned_down: dict[str, bool] = defaultdict(bool)
        self._turned_up: dict[str, bool] = defaultdict(bool)

    def reset_daily(self):
        """每日重置"""
        self._delta_history.clear()
        self._price_history.clear()
        self._peak_cum_delta.clear()
        self._trough_cum_delta.clear()
        self._turned_down.clear()
        self._turned_up.clear()
        logger.info("[DeltaDetector] 每日重置完成")

    def update(self, bar: AggregatedBar) -> Optional[DeltaSignal]:
        """更新bar数据，检测Delta信号"""
        code = bar.stock_code
        cum_delta = bar.cum_delta

        self._delta_history[code].append(bar.delta)
        self._price_history[code].append(bar.close_price)

        deltas = list(self._delta_history[code])
        prices = list(self._price_history[code])

        if len(deltas) < 5:
            return None

        # 更新峰值/谷值
        if cum_delta > self._peak_cum_delta[code]:
            self._peak_cum_delta[code] = cum_delta
            self._turned_down[code] = False  # 新高，重置拐头标记
        if cum_delta < self._trough_cum_delta[code]:
            self._trough_cum_delta[code] = cum_delta
            self._turned_up[code] = False

        peak = self._peak_cum_delta[code]
        trough = self._trough_cum_delta[code]

        # 1. CumDelta 拐头向下检测
        if (peak > 0
                and not self._turned_down[code]
                and cum_delta < peak * (1 - self.TURN_THRESHOLD)):
            self._turned_down[code] = True
            return DeltaSignal(
                stock_code=code,
                signal_type="DELTA_TURN_DOWN",
                description=f"CumDelta拐头: 从{peak:+.0f}→{cum_delta:+.0f}，买方力量减弱",
                delta=bar.delta, cum_delta=cum_delta,
                peak_cum_delta=peak, price=bar.close_price,
                confidence=min(1.0, abs(peak - cum_delta) / max(abs(peak), 1)),
                timestamp=bar.timestamp,
            )

        # 2. CumDelta 拐头向上检测（从负值回升）
        if (trough < 0
                and not self._turned_up[code]
                and cum_delta > trough * (1 - self.TURN_THRESHOLD)):
            self._turned_up[code] = True
            return DeltaSignal(
                stock_code=code,
                signal_type="DELTA_TURN_UP",
                description=f"CumDelta回升: 从{trough:+.0f}→{cum_delta:+.0f}，卖压缓解",
                delta=bar.delta, cum_delta=cum_delta,
                peak_cum_delta=peak, price=bar.close_price,
                confidence=min(1.0, abs(cum_delta - trough) / max(abs(trough), 1)),
                timestamp=bar.timestamp,
            )

        # 3. 价量背离检测
        if len(prices) >= self.DIVERGENCE_BARS and len(deltas) >= self.DIVERGENCE_BARS:
            recent_prices = prices[-self.DIVERGENCE_BARS:]
            price_rising = recent_prices[-1] > recent_prices[0]
            delta_sum_recent = sum(deltas[-self.DIVERGENCE_BARS:])

            # 价格新高但Delta为负 = 看多背离（危险）
            if price_rising and delta_sum_recent < 0 and recent_prices[-1] >= max(prices):
                return DeltaSignal(
                    stock_code=code,
                    signal_type="BEARISH_DIVERGENCE",
                    description=f"价量背离: 价格上涨但净卖出{abs(delta_sum_recent):.0f}股，涨势无力",
                    delta=bar.delta, cum_delta=cum_delta,
                    peak_cum_delta=peak, price=bar.close_price,
                    confidence=0.7,
                    timestamp=bar.timestamp,
                )

            # 价格新低但Delta为正 = 底部背离（机会）
            if not price_rising and delta_sum_recent > 0 and recent_prices[-1] <= min(prices):
                return DeltaSignal(
                    stock_code=code,
                    signal_type="BULLISH_DIVERGENCE",
                    description=f"底部背离: 价格下跌但净买入{delta_sum_recent:.0f}股，有资金承接",
                    delta=bar.delta, cum_delta=cum_delta,
                    peak_cum_delta=peak, price=bar.close_price,
                    confidence=0.7,
                    timestamp=bar.timestamp,
                )

        # 4. Delta极端值
        if len(deltas) >= 10:
            import statistics
            mean = statistics.mean(deltas)
            stdev = statistics.stdev(deltas)
            if stdev > 0 and abs(bar.delta - mean) > self.EXTREME_SIGMA * stdev:
                direction = "巨量买入" if bar.delta > 0 else "巨量卖出"
                return DeltaSignal(
                    stock_code=code,
                    signal_type="EXTREME_DELTA",
                    description=f"极端{direction}: Delta={bar.delta:+.0f}（超{self.EXTREME_SIGMA}σ）",
                    delta=bar.delta, cum_delta=cum_delta,
                    peak_cum_delta=peak, price=bar.close_price,
                    confidence=min(1.0, abs(bar.delta - mean) / (self.EXTREME_SIGMA * stdev) - 0.5),
                    timestamp=bar.timestamp,
                )

        return None
