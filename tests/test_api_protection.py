#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API保护装饰器测试

测试重试和熔断机制的集成
"""

import pytest
import time
from simple_trade.utils.api_protection import (
    protected_api_call,
    futu_api_protected,
    network_api_protected,
    get_breaker_status,
    reset_all_breakers,
    FUTU_API_BREAKER,
    NETWORK_API_BREAKER,
    CircuitBreakerState
)


class TestAPIProtection:
    """API保护装饰器测试"""

    def setup_method(self):
        """每个测试前重置熔断器"""
        reset_all_breakers()

    def test_successful_call(self):
        """测试成功的API调用"""
        call_count = [0]

        @protected_api_call(max_retries=3, error_return_value="ERROR")
        def successful_api():
            call_count[0] += 1
            return "SUCCESS"

        result = successful_api()
        assert result == "SUCCESS"
        assert call_count[0] == 1  # 只调用一次

    def test_retry_on_failure(self):
        """测试失败时的重试机制"""
        call_count = [0]

        @protected_api_call(max_retries=3, error_return_value="ERROR")
        def failing_api():
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("Temporary failure")
            return "SUCCESS"

        result = failing_api()
        assert result == "SUCCESS"
        assert call_count[0] == 3  # 重试2次后成功

    def test_max_retries_exceeded(self):
        """测试超过最大重试次数"""
        call_count = [0]

        @protected_api_call(max_retries=2, error_return_value="ERROR")
        def always_failing_api():
            call_count[0] += 1
            raise Exception("Permanent failure")

        result = always_failing_api()
        assert result == "ERROR"
        assert call_count[0] == 3  # 初始调用 + 2次重试

    def test_circuit_breaker_integration(self):
        """测试熔断器集成"""
        call_count = [0]

        @protected_api_call(
            breaker=FUTU_API_BREAKER,
            max_retries=1,
            error_return_value="ERROR"
        )
        def api_with_breaker():
            call_count[0] += 1
            raise Exception("API failure")

        # 初始状态应该是 CLOSED
        assert FUTU_API_BREAKER.state == CircuitBreakerState.CLOSED

        # 多次失败调用触发熔断器
        for _ in range(6):  # MODERATE 配置需要5次失败
            result = api_with_breaker()
            assert result == "ERROR"

        # 熔断器应该打开
        assert FUTU_API_BREAKER.state == CircuitBreakerState.OPEN

        # 熔断器打开时，调用应该被阻止
        call_count[0] = 0
        result = api_with_breaker()
        assert result == "ERROR"
        assert call_count[0] == 0  # 没有实际调用

    def test_futu_api_protected_decorator(self):
        """测试富途API专用装饰器"""
        call_count = [0]

        @futu_api_protected(max_retries=2, error_return_value=("ERROR", "Failed"))
        def futu_api_call():
            call_count[0] += 1
            if call_count[0] < 2:
                raise Exception("Temporary failure")
            return ("OK", "Success")

        result = futu_api_call()
        assert result == ("OK", "Success")
        assert call_count[0] == 2

    def test_network_api_protected_decorator(self):
        """测试网络API专用装饰器"""
        call_count = [0]

        @network_api_protected(max_retries=3, error_return_value="NETWORK_ERROR")
        def network_api_call():
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("Network timeout")
            return "NETWORK_SUCCESS"

        result = network_api_call()
        assert result == "NETWORK_SUCCESS"
        assert call_count[0] == 3

    def test_get_breaker_status(self):
        """测试获取熔断器状态"""
        status = get_breaker_status()

        assert 'futu_api' in status
        assert 'network_api' in status

        assert status['futu_api']['state'] == 'closed'
        assert status['network_api']['state'] == 'closed'

    def test_circuit_breaker_recovery(self):
        """测试熔断器恢复机制"""
        call_count = [0]
        should_fail = [True]

        @protected_api_call(
            breaker=NETWORK_API_BREAKER,
            max_retries=1,
            error_return_value="ERROR"
        )
        def recoverable_api():
            call_count[0] += 1
            if should_fail[0]:
                raise Exception("API failure")
            return "SUCCESS"

        # 触发熔断器打开（AGGRESSIVE 配置需要3次失败）
        for _ in range(4):
            result = recoverable_api()
            assert result == "ERROR"

        assert NETWORK_API_BREAKER.state == CircuitBreakerState.OPEN

        # 等待恢复时间（AGGRESSIVE 配置是30秒，但我们可以手动重置）
        NETWORK_API_BREAKER.reset()
        assert NETWORK_API_BREAKER.state == CircuitBreakerState.CLOSED

        # 现在API应该可以成功
        should_fail[0] = False
        call_count[0] = 0
        result = recoverable_api()
        assert result == "SUCCESS"
        assert call_count[0] == 1

    def test_different_error_return_values(self):
        """测试不同的错误返回值类型"""

        @protected_api_call(max_retries=1, error_return_value=None)
        def api_returns_none():
            raise Exception("Failure")

        @protected_api_call(max_retries=1, error_return_value=[])
        def api_returns_list():
            raise Exception("Failure")

        @protected_api_call(max_retries=1, error_return_value={"error": True})
        def api_returns_dict():
            raise Exception("Failure")

        assert api_returns_none() is None
        assert api_returns_list() == []
        assert api_returns_dict() == {"error": True}

    def test_no_breaker_protection(self):
        """测试不使用熔断器的保护"""
        call_count = [0]

        @protected_api_call(
            breaker=None,  # 不使用熔断器
            max_retries=2,
            error_return_value="ERROR"
        )
        def api_without_breaker():
            call_count[0] += 1
            if call_count[0] < 2:
                raise Exception("Failure")
            return "SUCCESS"

        result = api_without_breaker()
        assert result == "SUCCESS"
        assert call_count[0] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
