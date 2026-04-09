"""
熔断器单元测试
"""

import pytest
import asyncio
from simple_trade.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    CircuitBreakerOpenError,
)


@pytest.mark.asyncio
async def test_circuit_breaker_closed_state():
    """测试熔断器关闭状态（正常）"""
    config = CircuitBreakerConfig(failure_threshold=3)
    breaker = CircuitBreaker(config)
    
    async def success_func():
        return "success"
    
    # 正常调用
    result = await breaker.call(success_func)
    assert result == "success"
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_open_on_failures():
    """测试失败达到阈值后打开熔断器"""
    config = CircuitBreakerConfig(failure_threshold=3, timeout=1.0)
    breaker = CircuitBreaker(config)
    
    async def failing_func():
        raise Exception("Test failure")
    
    # 连续失败
    for i in range(3):
        with pytest.raises(Exception):
            await breaker.call(failing_func)
    
    # 验证熔断器已打开
    assert breaker.state == CircuitState.OPEN
    assert breaker.failure_count == 3


@pytest.mark.asyncio
async def test_circuit_breaker_rejects_when_open():
    """测试熔断器打开时拒绝请求"""
    config = CircuitBreakerConfig(failure_threshold=2, timeout=10.0)
    breaker = CircuitBreaker(config)
    
    async def failing_func():
        raise Exception("Test failure")
    
    # 触发熔断
    for i in range(2):
        with pytest.raises(Exception):
            await breaker.call(failing_func)
    
    assert breaker.state == CircuitState.OPEN
    
    # 尝试调用，应该被拒绝
    async def success_func():
        return "success"
    
    with pytest.raises(CircuitBreakerOpenError):
        await breaker.call(success_func)


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_after_timeout():
    """测试超时后切换到半开状态"""
    config = CircuitBreakerConfig(failure_threshold=2, timeout=0.5)
    breaker = CircuitBreaker(config)
    
    async def failing_func():
        raise Exception("Test failure")
    
    # 触发熔断
    for i in range(2):
        with pytest.raises(Exception):
            await breaker.call(failing_func)
    
    assert breaker.state == CircuitState.OPEN
    
    # 等待超时
    await asyncio.sleep(0.6)
    
    # 尝试调用，应该切换到HALF_OPEN
    async def success_func():
        return "success"
    
    result = await breaker.call(success_func)
    assert result == "success"
    assert breaker.state == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_circuit_breaker_recovery_from_half_open():
    """测试从半开状态恢复到关闭状态"""
    config = CircuitBreakerConfig(
        failure_threshold=2,
        success_threshold=2,
        timeout=0.5
    )
    breaker = CircuitBreaker(config)
    
    async def failing_func():
        raise Exception("Test failure")
    
    # 触发熔断
    for i in range(2):
        with pytest.raises(Exception):
            await breaker.call(failing_func)
    
    assert breaker.state == CircuitState.OPEN
    
    # 等待超时
    await asyncio.sleep(0.6)
    
    # 成功调用，切换到HALF_OPEN
    async def success_func():
        return "success"
    
    await breaker.call(success_func)
    assert breaker.state == CircuitState.HALF_OPEN
    
    # 再次成功，应该恢复到CLOSED
    await breaker.call(success_func)
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_to_open_on_failure():
    """测试半开状态失败后回到打开状态"""
    config = CircuitBreakerConfig(failure_threshold=2, timeout=0.5)
    breaker = CircuitBreaker(config)
    
    async def failing_func():
        raise Exception("Test failure")
    
    # 触发熔断
    for i in range(2):
        with pytest.raises(Exception):
            await breaker.call(failing_func)
    
    assert breaker.state == CircuitState.OPEN
    
    # 等待超时
    await asyncio.sleep(0.6)
    
    # 失败调用，应该从HALF_OPEN回到OPEN
    with pytest.raises(Exception):
        await breaker.call(failing_func)
    
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_circuit_breaker_manual_reset():
    """测试手动重置熔断器"""
    config = CircuitBreakerConfig(failure_threshold=2)
    breaker = CircuitBreaker(config)
    
    async def failing_func():
        raise Exception("Test failure")
    
    # 触发熔断
    for i in range(2):
        with pytest.raises(Exception):
            await breaker.call(failing_func)
    
    assert breaker.state == CircuitState.OPEN
    
    # 手动重置
    await breaker.reset()
    
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0
    assert breaker.success_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_success_resets_failure_count():
    """测试成功调用重置失败计数"""
    config = CircuitBreakerConfig(failure_threshold=3)
    breaker = CircuitBreaker(config)
    
    async def failing_func():
        raise Exception("Test failure")
    
    async def success_func():
        return "success"
    
    # 失败一次
    with pytest.raises(Exception):
        await breaker.call(failing_func)
    
    assert breaker.failure_count == 1
    
    # 成功调用
    await breaker.call(success_func)
    
    # 失败计数应该被重置
    assert breaker.failure_count == 0
    assert breaker.state == CircuitState.CLOSED
