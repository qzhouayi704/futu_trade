#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SubscriptionHelper 集成测试 - 验证后台K线任务集成

验证 subscribe_target_stocks 完成后 BackgroundKlineTask.submit 被调用，
以及 submit 非阻塞（Property 2）。

**Validates: Requirements 1.2, 1.3**
"""

import sys
import os
import time
import logging
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.subscription.subscription_helper import SubscriptionHelper
from simple_trade.services.market_data.kline.background_kline_task import BackgroundKlineTask

# 抑制测试中的日志输出
logging.disable(logging.CRITICAL)


# ── 辅助函数 ──────────────────────────────────────────────────────

def _make_subscribe_result(success=True, codes=None):
    """构建 subscription_manager.subscribe 的返回值"""
    codes = codes or []
    if success:
        return {
            'success': True,
            'message': f'成功订阅 {len(codes)} 只',
            'successful_stocks': codes,
            'already_subscribed': [],
            'failed_stocks': [],
            'otc_stocks': [],
            'errors': [],
        }
    return {
        'success': False,
        'message': '订阅失败',
        'successful_stocks': [],
        'already_subscribed': [],
        'failed_stocks': codes,
        'errors': ['订阅失败'],
    }


def _create_helper_with_mocks(container=None):
    """创建带有完整 mock 依赖的 SubscriptionHelper

    SubscriptionHelper 构造函数会创建多个真实子服务对象，
    这里在构造后将关键子服务替换为 MagicMock，以便控制行为。
    """
    db_manager = MagicMock()
    futu_client = MagicMock()
    futu_client.is_available.return_value = True

    subscription_manager = MagicMock()
    quote_service = MagicMock()
    config = MagicMock()

    # 配置 config 属性
    config.monitor_stocks_limit_by_market = {'HK': 50, 'US': 50}
    config.realtime_activity_filter = {'enabled': False}
    config.kline_priority_enabled = True

    if container is None:
        container = MagicMock()

    helper = SubscriptionHelper(
        db_manager=db_manager,
        futu_client=futu_client,
        subscription_manager=subscription_manager,
        quote_service=quote_service,
        config=config,
        container=container,
    )

    # 替换内部服务为 MagicMock，避免真实对象无法设置 return_value
    helper.stock_query_service = MagicMock()
    helper.activity_filter = MagicMock()
    helper.stock_marker = MagicMock()

    return helper, subscription_manager


# ── 测试：subscribe_target_stocks 成功后调用 submit ────────────

class TestSubscriptionHelperKlineIntegration:
    """验证 SubscriptionHelper 与 BackgroundKlineTask 的集成"""

    def test_submit_called_after_successful_subscribe(self):
        """订阅成功后，应调用 BackgroundKlineTask.submit

        **Validates: Requirements 1.2**
        """
        helper, sub_mgr = _create_helper_with_mocks()

        target_stocks = [
            {'code': 'HK.00700', 'market': 'HK'},
            {'code': 'HK.09988', 'market': 'HK'},
        ]
        codes = [s['code'] for s in target_stocks]

        helper.stock_query_service.get_target_stocks.return_value = target_stocks
        # 活跃度筛选关闭时走 calculator.apply_market_limits，需返回原列表
        helper.activity_filter.calculator.apply_market_limits.return_value = target_stocks

        sub_mgr.subscribe.return_value = _make_subscribe_result(True, codes)
        sub_mgr.subscribed_stocks = set(codes)

        helper.background_kline_task = MagicMock(spec=BackgroundKlineTask)

        result = helper.subscribe_target_stocks(markets=['HK'])

        assert result['success'] is True
        helper.background_kline_task.submit.assert_called_once_with(target_stocks)

    def test_submit_not_called_when_subscribe_fails(self):
        """订阅失败时，不应调用 BackgroundKlineTask.submit

        **Validates: Requirements 1.2**
        """
        helper, sub_mgr = _create_helper_with_mocks()

        target_stocks = [{'code': 'HK.00700', 'market': 'HK'}]
        helper.stock_query_service.get_target_stocks.return_value = target_stocks
        helper.activity_filter.calculator.apply_market_limits.return_value = target_stocks

        sub_mgr.subscribe.return_value = _make_subscribe_result(False, ['HK.00700'])

        helper.background_kline_task = MagicMock(spec=BackgroundKlineTask)

        result = helper.subscribe_target_stocks(markets=['HK'])

        assert result['success'] is False
        helper.background_kline_task.submit.assert_not_called()

    def test_submit_not_called_when_no_container(self):
        """没有 container 时，background_kline_task 为 None，不应报错

        **Validates: Requirements 1.2**
        """
        helper, sub_mgr = _create_helper_with_mocks()

        target_stocks = [{'code': 'HK.00700', 'market': 'HK'}]
        codes = [s['code'] for s in target_stocks]
        helper.stock_query_service.get_target_stocks.return_value = target_stocks
        helper.activity_filter.calculator.apply_market_limits.return_value = target_stocks
        sub_mgr.subscribe.return_value = _make_subscribe_result(True, codes)
        sub_mgr.subscribed_stocks = set(codes)

        # 模拟无 container 的情况
        helper.background_kline_task = None

        result = helper.subscribe_target_stocks(markets=['HK'])

        # 不应报错，订阅仍然成功
        assert result['success'] is True

    def test_submit_receives_filtered_stocks(self):
        """submit 应接收经过活跃度筛选后的股票列表

        **Validates: Requirements 1.2**
        """
        helper, sub_mgr = _create_helper_with_mocks()

        filtered_stocks = [
            {'code': 'HK.00700', 'market': 'HK'},
            {'code': 'HK.09988', 'market': 'HK'},
            {'code': 'HK.01810', 'market': 'HK'},
        ]
        codes = [s['code'] for s in filtered_stocks]

        helper.stock_query_service.get_target_stocks.return_value = filtered_stocks
        helper.activity_filter.calculator.apply_market_limits.return_value = filtered_stocks
        sub_mgr.subscribe.return_value = _make_subscribe_result(True, codes)
        sub_mgr.subscribed_stocks = set(codes)

        helper.background_kline_task = MagicMock(spec=BackgroundKlineTask)

        helper.subscribe_target_stocks(markets=['HK'])

        # 验证传递给 submit 的是筛选后的完整股票列表
        call_args = helper.background_kline_task.submit.call_args[0][0]
        assert len(call_args) == 3
        assert all('code' in s for s in call_args)


class TestBackgroundKlineTaskSubmitNonBlocking:
    """Property 2: 后台任务提交非阻塞

    **Validates: Requirements 1.3**

    对于任意股票列表，调用 BackgroundKlineTask.submit() 应在极短时间内返回
    （不超过 100ms），不等待实际下载完成。
    """

    def test_submit_returns_within_100ms(self):
        """submit() 应在 100ms 内返回，不等待 _execute 完成

        **Validates: Requirements 1.3**
        """
        container = MagicMock()
        # 让 _execute 模拟耗时操作（但 submit 不应等待它）
        task = BackgroundKlineTask(container)

        # 用一个慢速的 _execute 替换，验证 submit 不会阻塞
        import threading
        execute_started = threading.Event()
        execute_can_finish = threading.Event()

        original_execute = task._execute

        def slow_execute(stocks):
            execute_started.set()
            execute_can_finish.wait(timeout=5)
            return MagicMock()

        task._execute = slow_execute

        stocks = [{'code': f'HK.{i:05d}'} for i in range(10)]

        start = time.monotonic()
        task.submit(stocks)
        elapsed_ms = (time.monotonic() - start) * 1000

        # submit 应在 100ms 内返回
        assert elapsed_ms < 100, f"submit() 耗时 {elapsed_ms:.1f}ms，超过 100ms 限制"

        # 等待后台线程启动，确认任务确实被提交了
        assert execute_started.wait(timeout=2), "_execute 未被调用"

        # 清理：让后台线程结束
        execute_can_finish.set()

    def test_submit_nonblocking_with_large_stock_list(self):
        """大量股票时 submit() 仍应非阻塞

        **Validates: Requirements 1.3**
        """
        container = MagicMock()
        task = BackgroundKlineTask(container)

        import threading
        execute_can_finish = threading.Event()

        def slow_execute(stocks):
            execute_can_finish.wait(timeout=5)
            return MagicMock()

        task._execute = slow_execute

        # 100 只股票
        stocks = [{'code': f'HK.{i:05d}'} for i in range(100)]

        start = time.monotonic()
        task.submit(stocks)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 100, f"submit() 耗时 {elapsed_ms:.1f}ms，超过 100ms 限制"

        execute_can_finish.set()

    def test_submit_empty_list_returns_immediately(self):
        """空列表时 submit() 直接返回，不提交任务

        **Validates: Requirements 1.3**
        """
        container = MagicMock()
        task = BackgroundKlineTask(container)

        start = time.monotonic()
        task.submit([])
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 100, f"submit([]) 耗时 {elapsed_ms:.1f}ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
