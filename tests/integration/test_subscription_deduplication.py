#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订阅去重集成测试

验证：多个服务请求订阅同一股票时，只调用一次富途API
"""

import asyncio
import pytest
from unittest.mock import Mock, patch
from futu import SubType, RET_OK

from simple_trade.core.subscription.global_subscription_coordinator import GlobalSubscriptionCoordinator


class TestSubscriptionDeduplication:
    """验证订阅去重功能"""

    @pytest.fixture
    def mock_futu_client(self):
        client = Mock()
        client.subscribe_stocks = Mock(return_value=(RET_OK, None))
        client.unsubscribe_stocks = Mock(return_value=(RET_OK, None))
        return client

    @pytest.fixture
    def coordinator(self, mock_futu_client):
        return GlobalSubscriptionCoordinator(mock_futu_client, Mock())

    @pytest.mark.asyncio
    async def test_three_services_same_stock(self, coordinator, mock_futu_client):
        """三个服务订阅同一股票，只调用一次富途API"""
        stock = "HK.00700"

        # 三个服务同时请求订阅
        results = await asyncio.gather(
            coordinator.request_subscription("vwap_service", [stock], [SubType.TICKER], 0),
            coordinator.request_subscription("ticker_service", [stock], [SubType.TICKER], 0),
            coordinator.request_subscription("scalping_engine", [stock], [SubType.TICKER], 5),
        )

        # 所有服务都应该成功
        for result in results:
            assert result[stock] is True

        # 富途API只被调用一次
        assert mock_futu_client.subscribe_stocks.call_count == 1

    @pytest.mark.asyncio
    async def test_release_only_when_all_unsubscribed(self, coordinator, mock_futu_client):
        """只有所有订阅者都释放后，才真正取消订阅"""
        stock = "HK.00700"

        # 两个服务订阅
        await coordinator.request_subscription("service1", [stock], [SubType.QUOTE], 0)
        await coordinator.request_subscription("service2", [stock], [SubType.QUOTE], 0)

        # service1 释放
        await coordinator.release_subscription("service1", [stock], [SubType.QUOTE])
        # 此时 service2 还在，不应该取消订阅
        assert mock_futu_client.unsubscribe_stocks.call_count == 0

        # service2 释放
        await coordinator.release_subscription("service2", [stock], [SubType.QUOTE])
        # 现在所有订阅者都释放了，应该取消订阅
        assert mock_futu_client.unsubscribe_stocks.call_count == 1

    @pytest.mark.asyncio
    async def test_priority_cleanup(self, coordinator, mock_futu_client):
        """配额不足时，清理低优先级订阅"""
        # 设置很小的配额
        coordinator.set_quota_limits({SubType.QUOTE: 2})

        # 订阅2只低优先级股票（填满配额）
        await coordinator.request_subscription("service1", ["HK.00001"], [SubType.QUOTE], 0)
        await coordinator.request_subscription("service1", ["HK.00002"], [SubType.QUOTE], 0)

        # 强制设置订阅时间为2分钟前（满足最短订阅时间）
        import time
        for key in list(coordinator._subscription_times.keys()):
            coordinator._subscription_times[key] = time.time() - 120

        # 高优先级请求（应该清理低优先级）
        result = await coordinator.request_subscription(
            "scalping", ["HK.00003"], [SubType.QUOTE], 10
        )

        # 高优先级订阅应该成功
        assert result["HK.00003"] is True

    @pytest.mark.asyncio
    async def test_force_clear_and_restore(self, coordinator, mock_futu_client):
        """测试重连后清除和恢复订阅"""
        stock = "HK.00700"

        # 先订阅
        await coordinator.request_subscription("service1", [stock], [SubType.QUOTE], 5)
        assert mock_futu_client.subscribe_stocks.call_count == 1

        # 模拟重连：清除所有状态
        await coordinator.force_clear_all()
        assert len(coordinator._subscriptions) == 0

        # 恢复订阅
        await coordinator.restore_all_subscriptions()
        # 由于清除后没有记录，不会恢复（这是预期行为）
        # 实际重连后，各服务会重新请求订阅


class TestAPISchedulerBatching:
    """验证API调度器批处理功能"""

    @pytest.fixture
    def mock_futu_client(self):
        client = Mock()
        client.executor = None

        import pandas as pd
        mock_df = pd.DataFrame({'code': ['HK.00700', 'HK.00388', 'HK.00941']})
        client.get_stock_quote = Mock(return_value=(RET_OK, mock_df))
        return client

    @pytest.mark.asyncio
    async def test_batch_merging(self, mock_futu_client):
        """100ms内的请求应该被合并"""
        from simple_trade.core.api.global_api_scheduler import GlobalAPIScheduler

        scheduler = GlobalAPIScheduler(mock_futu_client)

        # 模拟 _invoke 方法
        call_count = 0
        original_invoke = scheduler._invoke

        async def mock_invoke(api_name, params):
            nonlocal call_count
            call_count += 1
            return (RET_OK, None)

        scheduler._invoke = mock_invoke

        # 同时发起3个请求
        tasks = [
            scheduler.call('get_stock_quote', {'stock_codes': ['HK.00700']}),
            scheduler.call('get_stock_quote', {'stock_codes': ['HK.00388']}),
            scheduler.call('get_stock_quote', {'stock_codes': ['HK.00941']}),
        ]

        await asyncio.gather(*tasks)

        # 3个请求应该被合并为1次调用
        assert call_count == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
