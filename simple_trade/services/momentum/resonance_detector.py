#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多维共振检测器

整合所有维度的信号，在多个维度同时看多/看空时发出高置信度信号。
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional, List, Any

logger = logging.getLogger(__name__)


@dataclass
class ResonanceSignal:
    """共振信号"""
    stock_code: str
    signal_type: str       # STRONG_BUY / STRONG_SELL / MODERATE_BUY / MODERATE_SELL
    description: str
    dimensions: List[str]  # 触发的维度列表
    dimension_count: int   # 共振维度数
    price: float
    confidence: float
    timestamp: float
    priority: str          # HIGH / MEDIUM / LOW


class ResonanceDetector:
    """多维共振检测器"""

    def __init__(self):
        # 每只股票最近一轮各维度信号（1分钟内的）
        self._recent_signals: dict[str, dict] = {}
        self._last_resonance: dict[str, float] = {}
        self._cooldown = 300  # 5min冷却

    def reset_daily(self):
        self._recent_signals.clear()
        self._last_resonance.clear()

    def collect_signal(self, stock_code: str, signal: Any, bar_timestamp: float):
        """收集一个维度的信号"""
        if stock_code not in self._recent_signals:
            self._recent_signals[stock_code] = {}

        bucket = self._recent_signals[stock_code]

        # 只保留1分钟内的信号
        expired = [k for k, v in bucket.items() if bar_timestamp - v['ts'] > 60]
        for k in expired:
            del bucket[k]

        # 分类信号方向
        sig_type = signal.signal_type
        direction = self._classify_direction(sig_type)

        bucket[sig_type] = {
            'direction': direction,
            'ts': bar_timestamp,
            'desc': signal.description,
            'confidence': getattr(signal, 'confidence', 0.5),
        }

    def check_resonance(self, stock_code: str, price: float, timestamp: float) -> Optional[ResonanceSignal]:
        """检查是否达到共振条件"""
        if timestamp - self._last_resonance.get(stock_code, 0) < self._cooldown:
            return None

        bucket = self._recent_signals.get(stock_code, {})
        if len(bucket) < 2:
            return None

        # 统计多空方向
        bullish = [k for k, v in bucket.items() if v['direction'] == 'BULL']
        bearish = [k for k, v in bucket.items() if v['direction'] == 'BEAR']

        # 计算平均置信度
        def avg_conf(keys):
            return sum(bucket[k]['confidence'] for k in keys) / len(keys) if keys else 0

        signal = None

        # 强烈买入共振: >= 3个看多维度
        if len(bullish) >= 3:
            self._last_resonance[stock_code] = timestamp
            descs = [bucket[k]['desc'] for k in bullish]
            signal = ResonanceSignal(
                stock_code=stock_code, signal_type="STRONG_BUY",
                description=f"强烈买入共振({len(bullish)}维): " + " | ".join(d[:20] for d in descs[:3]),
                dimensions=bullish, dimension_count=len(bullish),
                price=price, confidence=min(1.0, avg_conf(bullish)),
                timestamp=timestamp, priority="HIGH",
            )

        # 强烈卖出共振
        elif len(bearish) >= 3:
            self._last_resonance[stock_code] = timestamp
            descs = [bucket[k]['desc'] for k in bearish]
            signal = ResonanceSignal(
                stock_code=stock_code, signal_type="STRONG_SELL",
                description=f"强烈卖出共振({len(bearish)}维): " + " | ".join(d[:20] for d in descs[:3]),
                dimensions=bearish, dimension_count=len(bearish),
                price=price, confidence=min(1.0, avg_conf(bearish)),
                timestamp=timestamp, priority="HIGH",
            )

        # 中等买入: 2个看多
        elif len(bullish) == 2:
            self._last_resonance[stock_code] = timestamp
            signal = ResonanceSignal(
                stock_code=stock_code, signal_type="MODERATE_BUY",
                description=f"买入共振(2维): {', '.join(bullish)}",
                dimensions=bullish, dimension_count=2,
                price=price, confidence=avg_conf(bullish) * 0.7,
                timestamp=timestamp, priority="MEDIUM",
            )

        # 中等卖出: 2个看空
        elif len(bearish) == 2:
            self._last_resonance[stock_code] = timestamp
            signal = ResonanceSignal(
                stock_code=stock_code, signal_type="MODERATE_SELL",
                description=f"卖出共振(2维): {', '.join(bearish)}",
                dimensions=bearish, dimension_count=2,
                price=price, confidence=avg_conf(bearish) * 0.7,
                timestamp=timestamp, priority="MEDIUM",
            )

        return signal

    @staticmethod
    def _classify_direction(signal_type: str) -> str:
        """将信号类型分类为多/空/中性"""
        bull = {'BUY_MOMENTUM', 'RECOVERY', 'BULLISH_DIVERGENCE', 'DELTA_TURN_UP',
                'ACCELERATE_BUY', 'BIG_BUY_CLUSTER', 'VWAP_BOUNCE', 'OVERSOLD',
                'ACCUMULATION'}
        bear = {'SELL_MOMENTUM', 'EXHAUSTION', 'BEARISH_DIVERGENCE', 'DELTA_TURN_DOWN',
                'ACCELERATE_SELL', 'BIG_SELL_CLUSTER', 'VWAP_BREAK', 'OVERBOUGHT',
                'DISTRIBUTION', 'EXTREME_DELTA'}

        if signal_type in bull:
            return 'BULL'
        elif signal_type in bear:
            return 'BEAR'
        return 'NEUTRAL'
