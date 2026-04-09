"""
熔断器（Circuit Breaker）

实现熔断降级机制，防止故障扩散。

状态机：
- CLOSED（关闭）：正常状态，请求正常通过
- OPEN（打开）：熔断状态，直接拒绝请求
- HALF_OPEN（半开）：尝试恢复，允许部分请求通过
"""

import time
import asyncio
import logging
from enum import Enum
from functools import wraps
from typing import Callable, Optional, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"  # 关闭（正常）
    OPEN = "open"  # 打开（熔断）
    HALF_OPEN = "half_open"  # 半开（尝试恢复）


class CircuitBreakerConfig:
    """熔断器配置"""
    
    def __init__(
        self,
        failure_threshold: int = 5,  # 失败阈值
        success_threshold: int = 2,  # 成功阈值（半开状态）
        timeout: float = 60.0,  # 熔断超时时间（秒）
        expected_exception: type = Exception,  # 预期的异常类型
    ):
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception


class CircuitBreaker:
    """
    熔断器实现
    
    工作原理：
    1. CLOSED状态：正常执行，记录失败次数
    2. 失败次数达到阈值 → 切换到OPEN状态
    3. OPEN状态：直接拒绝请求，等待超时
    4. 超时后 → 切换到HALF_OPEN状态
    5. HALF_OPEN状态：允许部分请求，测试服务是否恢复
    6. 成功次数达到阈值 → 切换回CLOSED状态
    7. 失败 → 切换回OPEN状态
    """
    
    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitState:
        """获取当前状态"""
        return self._state
    
    @property
    def failure_count(self) -> int:
        """获取失败计数"""
        return self._failure_count
    
    @property
    def success_count(self) -> int:
        """获取成功计数"""
        return self._success_count
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        通过熔断器调用函数
        
        Args:
            func: 要调用的函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            函数返回值
            
        Raises:
            CircuitBreakerOpenError: 熔断器打开时
            原始异常: 函数执行失败时
        """
        async with self._lock:
            # 检查是否需要从OPEN切换到HALF_OPEN
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    logger.info("熔断器切换到HALF_OPEN状态，尝试恢复")
                else:
                    raise CircuitBreakerOpenError(
                        f"熔断器处于OPEN状态，拒绝请求。"
                        f"将在 {self._get_remaining_timeout():.1f} 秒后尝试恢复"
                    )
        
        # 执行函数
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            # 成功处理
            await self._on_success()
            return result
            
        except self.config.expected_exception as e:
            # 失败处理
            await self._on_failure()
            raise
    
    async def _on_success(self):
        """处理成功调用"""
        async with self._lock:
            self._failure_count = 0
            
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                logger.debug(
                    f"熔断器HALF_OPEN状态成功计数: "
                    f"{self._success_count}/{self.config.success_threshold}"
                )
                
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._success_count = 0
                    logger.info("熔断器恢复到CLOSED状态")
    
    async def _on_failure(self):
        """处理失败调用"""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()
            
            if self._state == CircuitState.HALF_OPEN:
                # 半开状态失败，立即切换回OPEN
                self._state = CircuitState.OPEN
                self._success_count = 0
                logger.warning("熔断器从HALF_OPEN切换回OPEN状态")
            
            elif self._state == CircuitState.CLOSED:
                logger.debug(
                    f"熔断器失败计数: "
                    f"{self._failure_count}/{self.config.failure_threshold}"
                )
                
                if self._failure_count >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN
                    logger.error(
                        f"熔断器打开！失败次数达到阈值 "
                        f"{self.config.failure_threshold}，"
                        f"将在 {self.config.timeout} 秒后尝试恢复"
                    )
    
    def _should_attempt_reset(self) -> bool:
        """判断是否应该尝试重置（从OPEN到HALF_OPEN）"""
        if self._last_failure_time is None:
            return True
        
        elapsed = (datetime.now() - self._last_failure_time).total_seconds()
        return elapsed >= self.config.timeout
    
    def _get_remaining_timeout(self) -> float:
        """获取剩余超时时间"""
        if self._last_failure_time is None:
            return 0.0
        
        elapsed = (datetime.now() - self._last_failure_time).total_seconds()
        remaining = self.config.timeout - elapsed
        return max(0.0, remaining)
    
    async def reset(self):
        """手动重置熔断器"""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            logger.info("熔断器已手动重置")


class CircuitBreakerOpenError(Exception):
    """熔断器打开异常"""
    pass


def circuit_breaker(config: Optional[CircuitBreakerConfig] = None):
    """
    熔断器装饰器
    
    Args:
        config: 熔断器配置
        
    Returns:
        装饰器函数
    """
    breaker = CircuitBreaker(config)
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # 同步函数需要在事件循环中运行
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(breaker.call(func, *args, **kwargs))
        
        # 根据函数类型返回对应的包装器
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# 预定义的熔断器配置
AGGRESSIVE_BREAKER = CircuitBreakerConfig(
    failure_threshold=3,
    success_threshold=1,
    timeout=30.0
)

MODERATE_BREAKER = CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0
)

CONSERVATIVE_BREAKER = CircuitBreakerConfig(
    failure_threshold=10,
    success_threshold=3,
    timeout=120.0
)
