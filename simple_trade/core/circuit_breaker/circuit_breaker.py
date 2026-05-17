#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
接口级熔断器（P4-2）

职责：
1. 每个 API 接口独立熔断，互不影响
2. get_history_kline 熔断不影响 get_stock_quote
3. 三态模型：CLOSED → OPEN → HALF_OPEN → CLOSED

熔断策略：
- CLOSED: 正常，失败计数
- OPEN: 拒绝请求，等待冷却期后进入 HALF_OPEN
- HALF_OPEN: 允许单次探针请求，成功恢复/失败重新 OPEN
"""

import logging
import threading
import time
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """单接口熔断器"""

    def __init__(self, name: str, failure_threshold: int = 5,
                 recovery_timeout: float = 60.0, half_open_max: int = 1):
        self.name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max = half_open_max

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._half_open_attempts = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            # 自动从 OPEN 转 HALF_OPEN
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_attempts = 0
                    logger.info(f"[熔断器:{self.name}] OPEN → HALF_OPEN")
            return self._state

    def allow_request(self) -> bool:
        """是否允许请求通过"""
        state = self.state  # 触发自动转换
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_attempts < self._half_open_max:
                    self._half_open_attempts += 1
                    return True
            return False
        return False  # OPEN

    def record_success(self):
        """记录成功"""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info(f"[熔断器:{self.name}] HALF_OPEN → CLOSED (恢复)")
            self._success_count += 1

    def record_failure(self):
        """记录失败"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(f"[熔断器:{self.name}] HALF_OPEN → OPEN (探针失败)")
            elif self._state == CircuitState.CLOSED and self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    f"[熔断器:{self.name}] CLOSED → OPEN "
                    f"(连续失败{self._failure_count}次 ≥ {self._failure_threshold})"
                )

    def get_status(self) -> dict:
        return {
            'name': self.name,
            'state': self.state.value,
            'failure_count': self._failure_count,
            'success_count': self._success_count,
            'recovery_timeout': self._recovery_timeout,
        }


class CircuitBreakerRegistry:
    """熔断器注册表 — 为每个接口维护独立熔断器"""

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

        # 默认配置（可按接口覆盖）
        self._configs = {
            'get_history_kline': {'failure_threshold': 3, 'recovery_timeout': 120},
            'get_market_snapshot': {'failure_threshold': 5, 'recovery_timeout': 60},
            'get_stock_quote': {'failure_threshold': 5, 'recovery_timeout': 60},
            'subscribe': {'failure_threshold': 10, 'recovery_timeout': 30},
            'get_capital_flow': {'failure_threshold': 5, 'recovery_timeout': 90},
        }

    def get(self, api_name: str) -> CircuitBreaker:
        """获取（或创建）指定接口的熔断器"""
        if api_name not in self._breakers:
            with self._lock:
                if api_name not in self._breakers:
                    config = self._configs.get(api_name, {})
                    self._breakers[api_name] = CircuitBreaker(
                        name=api_name,
                        failure_threshold=config.get('failure_threshold', 5),
                        recovery_timeout=config.get('recovery_timeout', 60),
                    )
        return self._breakers[api_name]

    def get_all_status(self) -> list:
        """获取所有熔断器状态"""
        return [b.get_status() for b in self._breakers.values()]


# 全局单例
_registry: Optional[CircuitBreakerRegistry] = None


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    """获取全局熔断器注册表"""
    global _registry
    if _registry is None:
        _registry = CircuitBreakerRegistry()
    return _registry
