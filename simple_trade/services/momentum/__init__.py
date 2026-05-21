#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动量引擎模块

提供实时逐笔数据驱动的7维度动量信号检测:
1. BSR 买卖力量比
2. Delta 累积净力量
3. 成交速度/加速度
4. 大单聚集检测
5. VWAP 偏离保护
6. 吸筹/派发识别
7. 多维共振触发
"""

from .engine import MomentumEngine
from .ticker_aggregator import TickerAggregator, AggregatedBar
from .bsr_monitor import BSRMonitor, MomentumSignal, MomentumState
from .delta_detector import DeltaDetector, DeltaSignal
from .velocity_detector import VelocityDetector, VelocitySignal
from .big_order_detector import BigOrderDetector, BigOrderSignal
from .vwap_detector import VWAPDetector, VWAPSignal
from .absorption_detector import AbsorptionDetector, AbsorptionSignal
from .resonance_detector import ResonanceDetector, ResonanceSignal
from .signal_publisher import SignalPublisher

__all__ = [
    'MomentumEngine',
    'TickerAggregator', 'AggregatedBar',
    'BSRMonitor', 'MomentumSignal', 'MomentumState',
    'DeltaDetector', 'DeltaSignal',
    'VelocityDetector', 'VelocitySignal',
    'BigOrderDetector', 'BigOrderSignal',
    'VWAPDetector', 'VWAPSignal',
    'AbsorptionDetector', 'AbsorptionSignal',
    'ResonanceDetector', 'ResonanceSignal',
    'SignalPublisher',
]
