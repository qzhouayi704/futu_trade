#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scalping 指标共享状态

从 Scalping 系统（DeltaCalculator、POCCalculator、TapeVelocityMonitor）
收集关键指标，供 Strategy 系统（TickerAnalyzer、SignalDetector）可选消费。

设计原则：
- 松耦合：Scalping 写入、Strategy 读取，双方互不依赖
- 可选消费：无 Scalping 数据时 Strategy 正常工作
- 自动过期：缓存 30 秒，过期自动失效
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 默认缓存有效期（秒）
_DEFAULT_TTL = 30.0


@dataclass
class ScalpingMetrics:
    """单只股票的 Scalping 指标快照（不可变值对象）"""

    # Delta 相关
    delta: float = 0.0                # 最近一个周期的净动量
    delta_volume: int = 0             # 最近一个周期的成交量
    delta_direction: str = "neutral"  # "bullish" / "bearish" / "neutral"
    big_order_ratio: float = 0.0      # 大单成交量占比

    # POC 相关
    poc_price: float = 0.0            # 成交量最大堆积区价格
    poc_buy_ratio: float = 0.5        # POC 价位的买入占比

    # Tape Velocity 相关
    tape_velocity_count: int = 0      # 当前 3 秒窗口成交笔数
    tape_velocity_baseline: float = 0.0  # 5 分钟滚动基准
    is_ignited: bool = False          # 是否处于动能点火状态

    # 元数据
    updated_at: float = 0.0           # Unix 时间戳（秒）


class ScalpingMetricsState:
    """Scalping 指标共享状态管理器

    线程安全的内存缓存，支持按股票代码存取指标快照。
    缓存自动过期，过期后 get 返回 None。
    """

    def __init__(self, ttl: float = _DEFAULT_TTL):
        self._lock = threading.RLock()
        self._ttl = ttl
        # stock_code → ScalpingMetrics
        self._metrics: Dict[str, ScalpingMetrics] = {}

    def set(self, stock_code: str, metrics: ScalpingMetrics) -> None:
        """写入指标快照（由 Scalping 系统调用）"""
        with self._lock:
            metrics.updated_at = time.time()
            self._metrics[stock_code] = metrics

    def get(self, stock_code: str) -> Optional[ScalpingMetrics]:
        """读取指标快照，过期返回 None（由 Strategy 系统调用）"""
        with self._lock:
            m = self._metrics.get(stock_code)
            if m is None:
                return None
            if time.time() - m.updated_at > self._ttl:
                # 过期自动清除
                del self._metrics[stock_code]
                return None
            return m

    def get_all(self) -> Dict[str, ScalpingMetrics]:
        """获取所有未过期的指标快照"""
        now = time.time()
        with self._lock:
            expired = [
                k for k, v in self._metrics.items()
                if now - v.updated_at > self._ttl
            ]
            for k in expired:
                del self._metrics[k]
            return dict(self._metrics)

    def remove(self, stock_code: str) -> None:
        """移除指定股票的指标"""
        with self._lock:
            self._metrics.pop(stock_code, None)

    def reset(self) -> None:
        """重置所有指标"""
        with self._lock:
            self._metrics.clear()
        logger.info("ScalpingMetricsState 已重置")
