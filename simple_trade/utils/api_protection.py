#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API保护装饰器 - 集成重试和熔断机制

提供统一的外部API调用保护，包括：
1. 指数退避重试
2. 熔断器保护
3. 超时控制
4. 错误日志记录
"""

import logging
import functools
import time
import threading
from typing import Callable, Any, Tuple, Optional
from enum import Enum
from datetime import datetime


class CircuitBreakerState(Enum):
    """熔断器状态"""
    CLOSED = "closed"  # 关闭（正常）
    OPEN = "open"  # 打开（熔断）
    HALF_OPEN = "half_open"  # 半开（尝试恢复）


class SimpleSyncCircuitBreaker:
    """简单的同步熔断器"""
    
    def __init__(self, failure_threshold: int = 5, timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self._lock = threading.Lock()
    
    def can_execute(self) -> bool:
        """检查是否可以执行"""
        with self._lock:
            if self.state == CircuitBreakerState.CLOSED:
                return True
            
            if self.state == CircuitBreakerState.OPEN:
                # 检查是否应该尝试恢复
                if self.last_failure_time:
                    elapsed = (datetime.now() - self.last_failure_time).total_seconds()
                    if elapsed >= self.timeout:
                        self.state = CircuitBreakerState.HALF_OPEN
                        return True
                return False
            
            # HALF_OPEN 状态允许执行
            return True
    
    def record_success(self):
        """记录成功"""
        with self._lock:
            self.failure_count = 0
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.CLOSED
                logging.info("熔断器恢复到CLOSED状态")
    
    def record_failure(self):
        """记录失败"""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now()
            
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.OPEN
                logging.warning("熔断器从HALF_OPEN切换回OPEN状态")
            elif self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
                logging.error(f"熔断器打开！失败次数达到阈值 {self.failure_threshold}")
    
    def reset(self):
        """重置熔断器"""
        with self._lock:
            self.state = CircuitBreakerState.CLOSED
            self.failure_count = 0
            self.last_failure_time = None
    
    def get_status(self) -> dict:
        """获取状态"""
        with self._lock:
            return {
                'state': self.state.value,
                'failure_count': self.failure_count,
                'failure_threshold': self.failure_threshold,
                'timeout': self.timeout
            }


# 预定义的熔断器配置
FUTU_API_BREAKER = SimpleSyncCircuitBreaker(failure_threshold=5, timeout=60.0)
NETWORK_API_BREAKER = SimpleSyncCircuitBreaker(failure_threshold=3, timeout=30.0)


def retry_on_exception(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    backoff_factor: float = 2.0
) -> Callable:
    """
    简单的重试装饰器，使用指数退避
    
    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟（秒）
        max_delay: 最大延迟（秒）
        backoff_factor: 退避因子
    
    Returns:
        装饰后的函数
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        # 计算延迟时间
                        delay = min(initial_delay * (backoff_factor ** attempt), max_delay)
                        logging.debug(
                            f"重试 {func.__name__} (第{attempt + 1}次), "
                            f"{delay:.2f}秒后重试"
                        )
                        time.sleep(delay)
                    else:
                        # 最后一次尝试失败，抛出异常
                        raise
            
            # 理论上不会到这里
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


def protected_api_call(
    breaker: Optional[SimpleSyncCircuitBreaker] = None,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    backoff_factor: float = 2.0,
    timeout: Optional[float] = None,
    error_return_value: Any = None
) -> Callable:
    """
    保护API调用的装饰器，集成重试和熔断机制
    
    Args:
        breaker: 熔断器实例，None表示不使用熔断器
        max_retries: 最大重试次数
        initial_delay: 初始重试延迟（秒）
        max_delay: 最大重试延迟（秒）
        backoff_factor: 退避因子
        timeout: 超时时间（秒），None表示不限制
        error_return_value: 失败时的返回值
    
    Returns:
        装饰后的函数
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 如果使用熔断器，先检查熔断器状态
            if breaker:
                if not breaker.can_execute():
                    logging.warning(
                        f"{func.__name__} 被熔断器阻止执行 "
                        f"(state={breaker.state.name})"
                    )
                    return error_return_value
            
            # 定义重试逻辑
            @retry_on_exception(
                max_retries=max_retries,
                initial_delay=initial_delay,
                max_delay=max_delay,
                backoff_factor=backoff_factor
            )
            def _execute():
                try:
                    result = func(*args, **kwargs)
                    
                    # 成功时记录到熔断器
                    if breaker:
                        breaker.record_success()
                    
                    return result
                    
                except Exception as e:
                    # 失败时记录到熔断器
                    if breaker:
                        breaker.record_failure()
                    
                    logging.error(
                        f"{func.__name__} 执行失败: {type(e).__name__}: {e}"
                    )
                    raise
            
            try:
                return _execute()
            except Exception as e:
                logging.error(
                    f"{func.__name__} 最终失败（已重试{max_retries}次）: {e}"
                )
                return error_return_value
        
        return wrapper
    return decorator


def futu_api_protected(
    max_retries: int = 2,
    error_return_value: Any = None
) -> Callable:
    """
    富途API专用保护装饰器
    
    使用中等熔断策略，适合富途API的稳定性特点
    
    Args:
        max_retries: 最大重试次数，默认2次
        error_return_value: 失败时的返回值
    
    Returns:
        装饰后的函数
    """
    return protected_api_call(
        breaker=FUTU_API_BREAKER,
        max_retries=max_retries,
        initial_delay=0.5,
        max_delay=5.0,
        backoff_factor=2.0,
        error_return_value=error_return_value
    )


def network_api_protected(
    max_retries: int = 3,
    timeout: float = 30.0,
    error_return_value: Any = None
) -> Callable:
    """
    网络API专用保护装饰器
    
    使用激进熔断策略，适合不稳定的网络API
    
    Args:
        max_retries: 最大重试次数，默认3次
        timeout: 超时时间（秒），默认30秒
        error_return_value: 失败时的返回值
    
    Returns:
        装饰后的函数
    """
    return protected_api_call(
        breaker=NETWORK_API_BREAKER,
        max_retries=max_retries,
        initial_delay=1.0,
        max_delay=10.0,
        backoff_factor=2.0,
        timeout=timeout,
        error_return_value=error_return_value
    )


def get_breaker_status() -> dict:
    """获取所有熔断器的状态"""
    return {
        'futu_api': FUTU_API_BREAKER.get_status(),
        'network_api': NETWORK_API_BREAKER.get_status()
    }


def reset_all_breakers():
    """重置所有熔断器"""
    FUTU_API_BREAKER.reset()
    NETWORK_API_BREAKER.reset()
    logging.info("所有熔断器已重置")
