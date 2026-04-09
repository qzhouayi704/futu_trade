#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
属性测试：BackgroundKlineTask Property 4 - 下载统计不变量

**Validates: Requirements 2.3, 3.4**

对于任意股票列表和任意下载执行结果，KlineDownloadResult 应满足：
    total == skipped + downloaded + failed + skipped_by_quota

Tag: Feature: async-kline-download, Property 4: 下载统计不变量
"""

import sys
import os
import logging
from enum import Enum
from unittest.mock import MagicMock, PropertyMock

from hypothesis import given, settings, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.market_data.kline.background_kline_task import (
    BackgroundKlineTask,
    KlineDownloadResult,
)

# 抑制测试中的日志输出
logging.disable(logging.CRITICAL)


class StockOutcome(Enum):
    """单只股票的可能结果"""
    SKIP = "skip"               # 数据充足，跳过
    DOWNLOAD_OK = "download_ok" # 下载成功
    DOWNLOAD_EMPTY = "empty"    # 下载返回空数据
    SAVE_FAIL = "save_fail"     # 保存失败（saved_count=0）
    NO_CODE = "no_code"         # 缺少 code 字段
    EXCEPTION = "exception"     # 非额度异常
    QUOTA_ERROR = "quota_error" # 额度耗尽异常


# ── hypothesis 策略 ──────────────────────────────────────────────

# 生成单只股票及其预期结果
stock_outcome_strategy = st.sampled_from([
    StockOutcome.SKIP,
    StockOutcome.DOWNLOAD_OK,
    StockOutcome.DOWNLOAD_EMPTY,
    StockOutcome.SAVE_FAIL,
    StockOutcome.NO_CODE,
    StockOutcome.EXCEPTION,
])

# 生成股票列表（1~30只），每只带有预期结果
# 额度耗尽单独处理：最多在某个位置插入一次
stock_list_strategy = st.lists(
    stock_outcome_strategy,
    min_size=1,
    max_size=30,
)


def _build_mock_container(outcomes: list[StockOutcome]):
    """根据预期结果列表构建 mock container

    为每只股票配置 kline_service 的各个子服务行为，
    使 _execute 按照预期路径执行。
    """
    container = MagicMock()
    kline_service = container.kline_service

    # 配置请求延迟为 0，加速测试
    kline_service.config.kline_rate_limit = {"request_delay": 0}

    # 额度预检查：正常通过
    kline_service.get_quota_info.return_value = {
        "remaining": 100,
        "status": "connected",
    }

    # 为每只股票按顺序配置 mock 行为
    has_enough_results = []
    fetch_results = []
    save_results = []

    # 跟踪需要 fetch 的股票索引（跳过 SKIP 和 NO_CODE 的）
    for outcome in outcomes:
        if outcome == StockOutcome.NO_CODE:
            # 不会调用 has_enough，直接 failed
            continue
        elif outcome == StockOutcome.SKIP:
            has_enough_results.append(True)
        else:
            has_enough_results.append(False)
            if outcome == StockOutcome.DOWNLOAD_OK:
                fetch_results.append([{"mock": "kline_data"}])
                save_results.append(5)
            elif outcome == StockOutcome.DOWNLOAD_EMPTY:
                fetch_results.append(None)
            elif outcome == StockOutcome.SAVE_FAIL:
                fetch_results.append([{"mock": "kline_data"}])
                save_results.append(0)
            elif outcome == StockOutcome.EXCEPTION:
                fetch_results.append(Exception("网络错误"))

    kline_service.parser.has_enough_kline_data.side_effect = has_enough_results

    # 构建 fetch 的 side_effect
    fetch_side_effects = []
    save_idx = 0
    for result in fetch_results:
        if isinstance(result, Exception):
            fetch_side_effects.append(result)
        else:
            fetch_side_effects.append(result)

    kline_service.fetcher.fetch_kline_data_with_limit.side_effect = (
        fetch_side_effects
    )

    # filter_today_incomplete_data 直接返回输入
    kline_service.parser.filter_today_incomplete_data.side_effect = (
        lambda code, data: data
    )

    # save_kline_batch 按顺序返回
    kline_service.storage.save_kline_batch.side_effect = save_results

    return container


def _build_stocks(outcomes: list[StockOutcome]) -> list[dict]:
    """根据结果列表生成股票字典列表"""
    stocks = []
    for i, outcome in enumerate(outcomes):
        if outcome == StockOutcome.NO_CODE:
            stocks.append({"name": f"无代码股票{i}"})  # 缺少 code 字段
        else:
            stocks.append({"code": f"HK.{i:05d}"})
    return stocks


# ── 属性测试 ──────────────────────────────────────────────────────

@given(outcomes=stock_list_strategy)
@settings(max_examples=200)
def test_property4_download_stats_invariant_normal(outcomes):
    """Property 4: 下载统计不变量（正常额度场景）

    **Validates: Requirements 2.3, 3.4**

    对于任意股票列表和任意下载结果组合（无额度耗尽），
    KlineDownloadResult 应满足：
        total == skipped + downloaded + failed + skipped_by_quota
    """
    container = _build_mock_container(outcomes)
    task = BackgroundKlineTask(container)
    stocks = _build_stocks(outcomes)

    result = task._execute(stocks)

    assert result.total == result.skipped + result.downloaded + result.failed + result.skipped_by_quota, (
        f"不变量违反: total={result.total}, "
        f"skipped={result.skipped}, downloaded={result.downloaded}, "
        f"failed={result.failed}, skipped_by_quota={result.skipped_by_quota}"
    )


# ── 额度耗尽场景的策略 ──────────────────────────────────────────

@given(
    pre_outcomes=st.lists(stock_outcome_strategy, min_size=0, max_size=15),
    post_count=st.integers(min_value=0, max_value=15),
)
@settings(max_examples=200)
def test_property4_download_stats_invariant_with_quota_exhaustion(
    pre_outcomes, post_count
):
    """Property 4: 下载统计不变量（额度耗尽场景）

    **Validates: Requirements 2.3, 3.4**

    在某个位置触发额度耗尽后，剩余股票被跳过，
    KlineDownloadResult 仍应满足：
        total == skipped + downloaded + failed + skipped_by_quota
    """
    # 在 pre_outcomes 后面插入一个额度耗尽的股票，再加上 post_count 只后续股票
    all_outcomes = list(pre_outcomes) + [StockOutcome.QUOTA_ERROR]
    for _ in range(post_count):
        all_outcomes.append(StockOutcome.DOWNLOAD_OK)  # 后续股票不会被执行

    # 构建 mock：额度耗尽股票之前的正常处理 + 额度耗尽异常
    container = MagicMock()
    kline_service = container.kline_service
    kline_service.config.kline_rate_limit = {"request_delay": 0}
    kline_service.get_quota_info.return_value = {
        "remaining": 100,
        "status": "connected",
    }

    has_enough_results = []
    fetch_side_effects = []
    save_results = []

    for outcome in all_outcomes:
        if outcome == StockOutcome.NO_CODE:
            continue
        elif outcome == StockOutcome.SKIP:
            has_enough_results.append(True)
        elif outcome == StockOutcome.QUOTA_ERROR:
            has_enough_results.append(False)
            fetch_side_effects.append(Exception("额度耗尽"))
        elif outcome == StockOutcome.DOWNLOAD_OK:
            has_enough_results.append(False)
            fetch_side_effects.append([{"mock": "data"}])
            save_results.append(5)
        elif outcome == StockOutcome.DOWNLOAD_EMPTY:
            has_enough_results.append(False)
            fetch_side_effects.append(None)
        elif outcome == StockOutcome.SAVE_FAIL:
            has_enough_results.append(False)
            fetch_side_effects.append([{"mock": "data"}])
            save_results.append(0)
        elif outcome == StockOutcome.EXCEPTION:
            has_enough_results.append(False)
            fetch_side_effects.append(Exception("网络错误"))

    kline_service.parser.has_enough_kline_data.side_effect = has_enough_results
    kline_service.fetcher.fetch_kline_data_with_limit.side_effect = (
        fetch_side_effects
    )
    kline_service.parser.filter_today_incomplete_data.side_effect = (
        lambda code, data: data
    )
    kline_service.storage.save_kline_batch.side_effect = save_results

    stocks = _build_stocks(all_outcomes)
    task = BackgroundKlineTask(container)
    result = task._execute(stocks)

    assert result.total == result.skipped + result.downloaded + result.failed + result.skipped_by_quota, (
        f"不变量违反: total={result.total}, "
        f"skipped={result.skipped}, downloaded={result.downloaded}, "
        f"failed={result.failed}, skipped_by_quota={result.skipped_by_quota}"
    )


@given(total=st.integers(min_value=0, max_value=100))
@settings(max_examples=200)
def test_property4_download_stats_invariant_quota_precheck_fail(total):
    """Property 4: 下载统计不变量（额度预检查失败场景）

    **Validates: Requirements 2.3, 3.4**

    当额度预检查发现额度为零时，所有股票被跳过，
    KlineDownloadResult 仍应满足：
        total == skipped + downloaded + failed + skipped_by_quota
    """
    container = MagicMock()
    kline_service = container.kline_service
    kline_service.config.kline_rate_limit = {"request_delay": 0}
    # 额度为零
    kline_service.get_quota_info.return_value = {
        "remaining": 0,
        "status": "connected",
    }

    stocks = [{"code": f"HK.{i:05d}"} for i in range(total)]
    task = BackgroundKlineTask(container)

    if total == 0:
        return  # submit 会直接跳过空列表

    result = task._execute(stocks)

    assert result.total == result.skipped + result.downloaded + result.failed + result.skipped_by_quota, (
        f"不变量违反: total={result.total}, "
        f"skipped={result.skipped}, downloaded={result.downloaded}, "
        f"failed={result.failed}, skipped_by_quota={result.skipped_by_quota}"
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
