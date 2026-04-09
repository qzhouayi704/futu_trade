#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试：ActivityFilterService Property 1 - 活跃度筛选不触发K线下载

**Validates: Requirements 1.1**

验证 ActivityFilterService 的 filter_active_stocks() 和 filter_by_realtime_activity()
方法不会调用 download_kline_for_stocks()。

注意：kline_downloader.py 已在任务 5.1 中被删除（无生产代码调用方），
因此本测试通过验证该模块不存在来确认解耦已完成，同时保留对筛选方法的
基本调用测试以确保它们不会因缺少 kline_downloader 而报错。
"""

import sys
import os
import logging
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.market_data.activity_filter import ActivityFilterService

# 抑制测试中的日志输出
logging.disable(logging.CRITICAL)


@pytest.fixture
def mock_dependencies():
    """构建 ActivityFilterService 所需的 mock 依赖"""
    subscription_manager = MagicMock()
    quote_service = MagicMock()
    config = MagicMock()
    db_manager = MagicMock()
    container = MagicMock()
    return subscription_manager, quote_service, config, db_manager, container


@pytest.fixture
def service(mock_dependencies):
    """创建 ActivityFilterService 实例，mock 内部子服务"""
    sub_mgr, quote_svc, config, db_mgr, container = mock_dependencies

    with patch(
        "simple_trade.services.market_data.activity_filter.ActivityCalculator"
    ) as MockCalc, patch(
        "simple_trade.services.market_data.activity_filter.SubscriptionOptimizer"
    ) as MockOpt:
        # 配置 ActivityCalculator mock
        calc = MockCalc.return_value
        calc.get_min_volume.return_value = 500000
        calc.get_min_price_config.return_value = {}
        calc.handle_priority_stocks.return_value = ([], [])
        calc.check_activity_cache.return_value = ([], [])
        calc.apply_market_limits.side_effect = lambda stocks, limits: stocks

        # 配置 SubscriptionOptimizer mock
        opt = MockOpt.return_value
        opt.process_batches.return_value = {
            "active": [],
            "inactive": [],
            "failed": [],
        }

        svc = ActivityFilterService(
            subscription_manager=sub_mgr,
            quote_service=quote_svc,
            config=config,
            db_manager=db_mgr,
            container=container,
        )
        yield svc


# ── 测试用例 ──────────────────────────────────────────────────────


SAMPLE_STOCKS = [
    {"code": "HK.00700", "name": "腾讯控股"},
    {"code": "HK.09988", "name": "阿里巴巴"},
    {"code": "US.AAPL", "name": "苹果"},
]

ACTIVITY_CONFIG = {
    "min_turnover_rate": 1.0,
    "min_turnover_amount": 5000000,
}

MARKET_LIMITS = {"HK": 100, "US": 100}


def test_kline_downloader_module_removed():
    """kline_downloader 模块已被删除，确认不可导入

    **Validates: Requirements 1.1**

    kline_downloader.py 已在清理任务中被删除，因为没有任何生产代码调用方。
    此测试确认该模块确实不存在，从根本上保证筛选流程不可能触发旧的同步K线下载。
    """
    with pytest.raises(ModuleNotFoundError):
        import importlib
        importlib.import_module(
            "simple_trade.services.market_data.kline.kline_downloader"
        )


def test_filter_active_stocks_runs_without_kline_downloader(service):
    """filter_active_stocks() 在 kline_downloader 不存在时正常运行

    **Validates: Requirements 1.1**
    """
    # 不应抛出任何异常
    service.filter_active_stocks(
        stocks=SAMPLE_STOCKS,
        activity_config=ACTIVITY_CONFIG,
    )


def test_filter_by_realtime_activity_runs_without_kline_downloader(service):
    """filter_by_realtime_activity() 在 kline_downloader 不存在时正常运行

    **Validates: Requirements 1.1**
    """
    service.filter_by_realtime_activity(
        stocks=SAMPLE_STOCKS,
        market_limits=MARKET_LIMITS,
        activity_config=ACTIVITY_CONFIG,
    )


def test_filter_active_stocks_with_priority_runs_without_kline_downloader(service):
    """带优先股票的 filter_active_stocks() 在 kline_downloader 不存在时正常运行

    **Validates: Requirements 1.1**
    """
    service.filter_active_stocks(
        stocks=SAMPLE_STOCKS,
        activity_config=ACTIVITY_CONFIG,
        priority_stocks=["HK.00700"],
    )


def test_filter_with_empty_stocks_runs_without_kline_downloader(service):
    """空股票列表在 kline_downloader 不存在时正常运行

    **Validates: Requirements 1.1**
    """
    service.filter_active_stocks(
        stocks=[],
        activity_config=ACTIVITY_CONFIG,
    )

    service.filter_by_realtime_activity(
        stocks=[],
        market_limits=MARKET_LIMITS,
        activity_config=ACTIVITY_CONFIG,
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
