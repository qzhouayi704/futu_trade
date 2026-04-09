#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略服务模块

包含：
- ScreeningEngine: 策略筛选引擎
- ScreeningCache: 筛选结果缓存管理
- ScreeningResult: 筛选结果数据类
- SignalDetector: 信号检测器
- SignalHistoryManager: 信号历史管理器
- SignalRecord: 信号记录数据类
- SignalTracker: 信号效果追踪器
"""

from .screening_engine import ScreeningEngine, ScreeningResult
from .screening_cache import ScreeningCache
from .signal_detector import SignalDetector, SignalRecord
from .signal_history import SignalHistoryManager
from .signal_tracker import SignalTracker
from .position_stop_loss import PositionStopLossChecker, StopLossParams

__all__ = [
    'ScreeningEngine',
    'ScreeningCache',
    'ScreeningResult',
    'SignalDetector',
    'SignalHistoryManager',
    'SignalRecord',
    'SignalTracker',
    'PositionStopLossChecker',
    'StopLossParams',
]
