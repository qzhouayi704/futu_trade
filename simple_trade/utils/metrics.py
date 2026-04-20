"""
轻量级 Metrics 收集器

纯内存实现，无外部依赖。通过 GET /system/metrics 暴露 JSON 快照。

使用示例:
    from simple_trade.utils.metrics import get_metrics

    m = get_metrics()
    m.counter("api.futu.calls").inc()
    m.histogram("api.futu.latency_ms").observe(12.5)
    m.gauge("scalping.active_stocks").set(5)

    snapshot = m.snapshot()  # 返回 dict，可直接 JSON 序列化
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional


class Counter:
    """单调递增计数器"""

    __slots__ = ("_value", "_lock")

    def __init__(self) -> None:
        self._value: int = 0
        self._lock = threading.Lock()

    def inc(self, n: int = 1) -> None:
        with self._lock:
            self._value += n

    @property
    def value(self) -> int:
        return self._value

    def snapshot(self) -> dict:
        return {"type": "counter", "value": self._value}


class Gauge:
    """瞬时值指标"""

    __slots__ = ("_value", "_lock")

    def __init__(self) -> None:
        self._value: float = 0.0
        self._lock = threading.Lock()

    def set(self, v: float) -> None:
        with self._lock:
            self._value = v

    def inc(self, n: float = 1.0) -> None:
        with self._lock:
            self._value += n

    def dec(self, n: float = 1.0) -> None:
        with self._lock:
            self._value -= n

    @property
    def value(self) -> float:
        return self._value

    def snapshot(self) -> dict:
        return {"type": "gauge", "value": self._value}


class Histogram:
    """分布统计（滑动窗口，保留最近 N 个样本）

    提供 count / sum / avg / p50 / p95 / p99 / max / min 统计。
    """

    __slots__ = ("_window", "_lock", "_count_total")

    def __init__(self, window_size: int = 1000) -> None:
        self._window: deque[float] = deque(maxlen=window_size)
        self._lock = threading.Lock()
        self._count_total: int = 0

    def observe(self, value: float) -> None:
        with self._lock:
            self._window.append(value)
            self._count_total += 1

    def snapshot(self) -> dict:
        with self._lock:
            if not self._window:
                return {
                    "type": "histogram",
                    "count": 0,
                    "count_total": self._count_total,
                }
            samples = sorted(self._window)
            n = len(samples)
            return {
                "type": "histogram",
                "count": n,
                "count_total": self._count_total,
                "sum": round(sum(samples), 2),
                "avg": round(sum(samples) / n, 2),
                "min": round(samples[0], 2),
                "max": round(samples[-1], 2),
                "p50": round(samples[n * 50 // 100], 2),
                "p95": round(samples[n * 95 // 100], 2),
                "p99": round(samples[min(n * 99 // 100, n - 1)], 2),
            }


class RateCounter:
    """速率计数器 — 统计最近 N 秒内的事件数，用于计算 QPS/TPS"""

    __slots__ = ("_window_seconds", "_events", "_lock")

    def __init__(self, window_seconds: int = 60) -> None:
        self._window_seconds = window_seconds
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def inc(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._events.append(now)

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    def rate(self) -> float:
        """返回最近窗口内的每秒事件数"""
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            n = len(self._events)
        if n == 0:
            return 0.0
        return round(n / self._window_seconds, 2)

    def snapshot(self) -> dict:
        return {
            "type": "rate",
            "window_seconds": self._window_seconds,
            "rate_per_sec": self.rate(),
        }


class MetricsRegistry:
    """全局 Metrics 注册表"""

    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}
        self._rates: dict[str, RateCounter] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()

    def counter(self, name: str) -> Counter:
        if name not in self._counters:
            with self._lock:
                if name not in self._counters:
                    self._counters[name] = Counter()
        return self._counters[name]

    def gauge(self, name: str) -> Gauge:
        if name not in self._gauges:
            with self._lock:
                if name not in self._gauges:
                    self._gauges[name] = Gauge()
        return self._gauges[name]

    def histogram(self, name: str, window_size: int = 1000) -> Histogram:
        if name not in self._histograms:
            with self._lock:
                if name not in self._histograms:
                    self._histograms[name] = Histogram(window_size)
        return self._histograms[name]

    def rate(self, name: str, window_seconds: int = 60) -> RateCounter:
        if name not in self._rates:
            with self._lock:
                if name not in self._rates:
                    self._rates[name] = RateCounter(window_seconds)
        return self._rates[name]

    def snapshot(self) -> dict:
        """导出所有 metrics 的 JSON 快照"""
        result: dict = {
            "_meta": {
                "uptime_seconds": round(time.time() - self._start_time, 1),
                "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        }
        for name, c in sorted(self._counters.items()):
            result[name] = c.snapshot()
        for name, g in sorted(self._gauges.items()):
            result[name] = g.snapshot()
        for name, h in sorted(self._histograms.items()):
            result[name] = h.snapshot()
        for name, r in sorted(self._rates.items()):
            result[name] = r.snapshot()
        return result


# ========== 全局单例 ==========
_registry: Optional[MetricsRegistry] = None
_init_lock = threading.Lock()


def get_metrics() -> MetricsRegistry:
    """获取全局 MetricsRegistry 单例"""
    global _registry
    if _registry is None:
        with _init_lock:
            if _registry is None:
                _registry = MetricsRegistry()
    return _registry
