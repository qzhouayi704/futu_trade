#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局服务单元测试
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from futu import SubType, RET_OK, RET_ERROR

from simple_trade.core.subscription.global_subscription_coordinator import GlobalSubscriptionCoordinator
from simple_trade.core.api.global_api_scheduler import GlobalAPIScheduler
from simple_trade.core.connection.global_connection_manager import GlobalConnectionManager


class TestGlobalSubscriptionCoordinator:
    """测试全局订阅协调器"""

    @pytest.fixture
    def mock_futu_client(self):
        client = Mock()
        client.subscribe_stocks = Mock(return_value=(RET_OK, None))
        client.unsubscribe_stocks = Mock(return_value=(RET_OK, None))
        return client

    @pytest.fixture
    def mock_subscription_manager(self):
        return Mock()

    @pytest.fixture
    def coordinator(self, mock_futu_client, mock_subscription_manager):
        return GlobalSubscriptionCoordinator(mock_futu_client, mock_subscription_manager)

    @pytest.mark.asyncio
    async def test_request_subscription_success(self, coordinator, mock_futu_client):
        """测试订阅成功"""
        result = await coordinator.request_subscription(
            subscriber_id="test_service",
            stock_codes=["HK.00700"],
            sub_types=[SubType.QUOTE],
            priority=5
        )

        assert result["HK.00700"] is True
        mock_futu_client.subscribe_stocks.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_subscription_deduplication(self, coordinator, mock_futu_client):
        """测试订阅去重"""
        # 第一次订阅
        await coordinator.request_subscription(
            subscriber_id="service1",
            stock_codes=["HK.00700"],
            sub_types=[SubType.QUOTE],
            priority=5
        )

        # 第二次订阅同一股票（不同订阅者）
        await coordinator.request_subscription(
            subscriber_id="service2",
            stock_codes=["HK.00700"],
            sub_types=[SubType.QUOTE],
            priority=5
        )

        # 应该只调用一次富途API
        assert mock_futu_client.subscribe_stocks.call_count == 1

    @pytest.mark.asyncio
    async def test_release_subscription(self, coordinator, mock_futu_client):
        """测试释放订阅"""
        # 先订阅
        await coordinator.request_subscription(
            subscriber_id="service1",
            stock_codes=["HK.00700"],
            sub_types=[SubType.QUOTE],
            priority=5
        )

        # 释放订阅
        await coordinator.release_subscription(
            subscriber_id="service1",
            stock_codes=["HK.00700"],
            sub_types=[SubType.QUOTE]
        )

        # 应该调用反订阅
        mock_futu_client.unsubscribe_stocks.assert_called_once()


class TestGlobalAPIScheduler:
    """测试全局API调度器"""

    @pytest.fixture
    def mock_futu_client(self):
        client = Mock()
        client.executor = None
        client.get_stock_quote = Mock(return_value=(RET_OK, Mock()))
        return client

    @pytest.fixture
    def scheduler(self, mock_futu_client):
        return GlobalAPIScheduler(mock_futu_client)

    @pytest.mark.asyncio
    async def test_direct_call(self, scheduler, mock_futu_client):
        """测试直接调用"""
        result = await scheduler._direct_call(
            'get_stock_quote',
            {'stock_codes': ['HK.00700']}
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_rate_limiting(self, scheduler, mock_futu_client):
        """测试限流"""
        # 连续调用多次
        tasks = []
        for _ in range(5):
            task = scheduler._direct_call(
                'get_stock_quote',
                {'stock_codes': ['HK.00700']}
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks)
        assert len(results) == 5


class TestGlobalConnectionManager:
    """测试全局连接管理器"""

    @pytest.fixture
    def mock_futu_client(self):
        client = Mock()
        client.is_connected = True
        client._try_reconnect = Mock(return_value=True)
        return client

    @pytest.fixture
    def mock_coordinator(self):
        coordinator = AsyncMock()
        coordinator.force_clear_all = AsyncMock()
        coordinator.restore_all_subscriptions = AsyncMock()
        return coordinator

    @pytest.fixture
    def manager(self, mock_futu_client, mock_coordinator):
        return GlobalConnectionManager(mock_futu_client, mock_coordinator)

    @pytest.mark.asyncio
    async def test_start_monitoring(self, manager):
        """测试启动监控"""
        await manager.start_monitoring()
        assert manager._monitor_task is not None

    @pytest.mark.asyncio
    async def test_stop_monitoring(self, manager):
        """测试停止监控"""
        await manager.start_monitoring()
        await manager.stop_monitoring()
        assert manager._monitor_task.cancelled() or manager._monitor_task.done()

    @pytest.mark.asyncio
    async def test_reconnect_callback(self, manager):
        """测试重连回调"""
        callback_called = False

        def callback():
            nonlocal callback_called
            callback_called = True

        manager.register_reconnect_callback(callback)

        # 模拟重连
        await manager._handle_disconnection()

        # 回调应该被调用
        assert callback_called


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
