#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成交速度/加速度检测器

检测:
- 成交加速（资金涌入/恐慌抛售）
- 缩量观望
- 爆量拐点
"""

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from .ticker_aggregator import AggregatedBar

logger = logging.getLogger(__name__)


@dataclass
class VelocitySignal:
    """速度信号"""
    stock_code: str
    signal_type: str       # ACCELERATE_BUY / ACCELERATE_SELL / VOLUME_DRY / VOLUME_SPIKE
    description: str
    velocity: int          # 当前笔数
    acceleration: float    # 加速度倍数
    bsr: float
    price: float
    confidence: float
    timestamp: float


class VelocityDetector:
    """成交速度检测器"""

    ACCEL_THRESHOLD = 2.0      # 加速度 > 2倍均值触发
    SPIKE_THRESHOLD = 3.0      # 爆量 > 3倍
    DRY_THRESHOLD = 0.3        # 缩量 < 30%均值

    def __init__(self, history_size: int = 30):
        self._velocity_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=history_size)
        )

    def reset_daily(self):
        self._velocity_history.clear()

    def update(self, bar: AggregatedBar) -> Optional[VelocitySignal]:
        code = bar.stock_code
        velocity = bar.tick_count
        history = self._velocity_history[code]
        history.append(velocity)

        if len(history) < 5:
            return None

        avg_vel = sum(list(history)[:-1]) / (len(history) - 1)
        if avg_vel <= 0:
            return None

        accel = velocity / avg_vel

        # 爆量 + BSR 方向确认
        if accel > self.SPIKE_THRESHOLD:
            if bar.bsr > 1.2:
                return VelocitySignal(
                    stock_code=code, signal_type="ACCELERATE_BUY",
                    description=f"加速买入: 成交{velocity}笔({accel:.1f}x均值), BSR={bar.bsr:.2f}",
                    velocity=velocity, acceleration=accel, bsr=bar.bsr,
                    price=bar.close_price, confidence=min(1.0, accel / 4),
                    timestamp=bar.timestamp,
                )
            elif bar.bsr < 0.8:
                return VelocitySignal(
                    stock_code=code, signal_type="ACCELERATE_SELL",
                    description=f"恐慌抛售: 成交{velocity}笔({accel:.1f}x均值), BSR={bar.bsr:.2f}",
                    velocity=velocity, acceleration=accel, bsr=bar.bsr,
                    price=bar.close_price, confidence=min(1.0, accel / 4),
                    timestamp=bar.timestamp,
                )
            else:
                return VelocitySignal(
                    stock_code=code, signal_type="VOLUME_SPIKE",
                    description=f"爆量: 成交{velocity}笔({accel:.1f}x均值), 方向待定",
                    velocity=velocity, acceleration=accel, bsr=bar.bsr,
                    price=bar.close_price, confidence=0.5,
                    timestamp=bar.timestamp,
                )

        # 缩量
        if accel < self.DRY_THRESHOLD and len(history) >= 10:
            return VelocitySignal(
                stock_code=code, signal_type="VOLUME_DRY",
                description=f"缩量观望: 成交{velocity}笔(仅{accel:.0%}均值)",
                velocity=velocity, acceleration=accel, bsr=bar.bsr,
                price=bar.close_price, confidence=0.4,
                timestamp=bar.timestamp,
            )

        return None
