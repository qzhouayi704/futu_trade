#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
属性测试：BackgroundKlineTask Property 6 - 额度耗尽快速终止

**Validates: Requirements 3.2, 3.3**

对于任意股票列表，如果第 N 只股票下载时触发额度耗尽错误，
则第 N+1 到最后一只股票都不应被尝试下载，
且 skipped_by_quota 应等于剩余未处理的股票数量。

Tag: Feature: async-kline-download, Property 6: 额度耗尽快速终止
"""

import sys
import os
import logging
from enum import Enum
from unittest.mock import MagicMock, call

from hypothesis import given, settings, strategies as st, assume

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.market_data.kline.background_kline_task import (
    BackgroundKlineTask,
    KlineDownloadResult,
)

# 抑制测试中的日志输出
logging.disable(logging.CRITICAL)


class StockOutcome(Enum):
    """额度耗尽前的股票结果类型（不含额度耗尽）"""
    SKIP = "skip"               # 数据充足，跳过
    DOWNLOAD_OK = "download_ok" # 下载成功
    DOWNLOAD_EMPTY = "empty"    # 下载返回空数据
    SAVE_FAIL = "save_fail"     # 保存失败
    NO_CODE = "no_code"         # 缺少 code 字段
    EXCEPTION = "exception"     # 非额度异常


# 额度耗尽错误关键词，随机选择一个用于触发
QUOTA_ERROR_MESSAGES = [
    "quota exceeded",
    "额度耗尽",
    "limit exceeded",
    "rate limit reached",
    "超出限制",
]

# ── hypothesis 策略 ──────────────────────────────────────────────

pre_outcome_strategy = st.sampled_from([
    StockOutcome.SKIP,
    StockOutcome.DOWNLOAD_OK,
    StockOutcome.DOWNLOAD_EMPTY,
    StockOutcome.SAVE_FAIL,
    StockOutcome.NO_CODE,
    StockOutcome.EXCEPTION,
])

quota_error_msg_strategy = st.sampled_from(QUOTA_ERROR_MESSAGES)


def _build_mock_container(pre_outcomes, quota_error_msg):
    """构建 mock container，在 pre_outcomes 之后触发额度耗尽

    Args:
        pre_outcomes: 额度耗尽前的股票结果列表
        quota_error_msg: 额度耗尽异常消息
    """
    container = MagicMock()
    kline_service = container.kline_service

    # 请求延迟为 0，加速测试
    kline_service.config.kline_rate_limit = {"request_delay": 0}

    # 额度预检查通过
    kline_service.get_quota_info.return_value = {
        "remaining": 100,
        "status": "connected",
    }

    has_enough_results = []
    fetch_side_effects = []
    save_results = []

    # 配置额度耗尽前的股票行为
    for outcome in pre_outcomes:
        if outcome == StockOutcome.NO_CODE:
            continue  # 缺少 code 字段，不会调用 has_enough
        elif outcome == StockOutcome.SKIP:
            has_enough_results.append(True)
        else:
            has_enough_results.append(False)
            if outcome == StockOutcome.DOWNLOAD_OK:
                fetch_side_effects.append([{"mock": "kline_data"}])
                save_results.append(5)
            elif outcome == StockOutcome.DOWNLOAD_EMPTY:
                fetch_side_effects.append(None)
            elif outcome == StockOutcome.SAVE_FAIL:
                fetch_side_effects.append([{"mock": "kline_data"}])
                save_results.append(0)
            elif outcome == StockOutcome.EXCEPTION:
                fetch_side_effects.append(Exception("网络连接超时"))

    # 额度耗尽的股票：has_enough 返回 False，fetch 抛出额度异常
    has_enough_results.append(False)
    fetch_side_effects.append(Exception(quota_error_msg))

    kline_service.parser.has_enough_kline_data.side_effect = has_enough_results
    kline_service.fetcher.fetch_kline_data_with_limit.side_effect = fetch_side_effects
    kline_service.parser.filter_today_incomplete_data.side_effect = (
        lambda code, data: data
    )
    kline_service.storage.save_kline_batch.side_effect = save_results

    return container


def _build_stocks(pre_outcomes, post_count):
    """构建完整股票列表：前置 + 额度耗尽触发 + 后续未处理

    Args:
        pre_outcomes: 额度耗尽前的股票结果列表
        post_count: 额度耗尽后剩余的股票数量
    """
    stocks = []
    idx = 0

    # 前置股票
    for outcome in pre_outcomes:
        if outcome == StockOutcome.NO_CODE:
            stocks.append({"name": f"无代码股票{idx}"})
        else:
            stocks.append({"code": f"HK.{idx:05d}"})
        idx += 1

    # 触发额度耗尽的股票
    stocks.append({"code": f"HK.{idx:05d}"})
    idx += 1

    # 后续不应被处理的股票
    for _ in range(post_count):
        stocks.append({"code": f"HK.{idx:05d}"})
        idx += 1

    return stocks


def _count_pre_outcomes(pre_outcomes):
    """统计额度耗尽前各类结果的数量"""
    skipped = sum(1 for o in pre_outcomes if o == StockOutcome.SKIP)
    downloaded = sum(1 for o in pre_outcomes if o == StockOutcome.DOWNLOAD_OK)
    failed = sum(
        1 for o in pre_outcomes
        if o in (
            StockOutcome.DOWNLOAD_EMPTY,
            StockOutcome.SAVE_FAIL,
            StockOutcome.NO_CODE,
            StockOutcome.EXCEPTION,
        )
    )
    return skipped, downloaded, failed


# ── 属性测试 ──────────────────────────────────────────────────────

@given(
    pre_outcomes=st.lists(pre_outcome_strategy, min_size=0, max_size=15),
    post_count=st.integers(min_value=1, max_value=15),
    quota_error_msg=quota_error_msg_strategy,
)
@settings(max_examples=200)
def test_property6_quota_exhaustion_stops_processing(
    pre_outcomes, post_count, quota_error_msg
):
    """Property 6: 额度耗尽快速终止 - 后续股票不被处理

    **Validates: Requirements 3.2, 3.3**

    验证：
    1. quota_exhausted 为 True
    2. skipped_by_quota 等于额度耗尽后剩余未处理的股票数量
    3. 额度耗尽后的股票不应触发 has_enough 或 fetch 调用
    """
    container = _build_mock_container(pre_outcomes, quota_error_msg)
    task = BackgroundKlineTask(container)
    stocks = _build_stocks(pre_outcomes, post_count)

    result = task._execute(stocks)

    # 1. 必须标记为额度耗尽
    assert result.quota_exhausted is True, (
        f"应标记额度耗尽: quota_exhausted={result.quota_exhausted}"
    )

    # 2. skipped_by_quota 应等于后续未处理的股票数量
    assert result.skipped_by_quota == post_count, (
        f"skipped_by_quota 应为 {post_count}，实际为 {result.skipped_by_quota}"
    )

    # 3. 验证后续股票的 code 没有出现在 has_enough 或 fetch 的调用中
    kline_service = container.kline_service
    quota_trigger_idx = len(pre_outcomes)  # 触发额度耗尽的股票索引

    # 收集所有 has_enough 调用的股票代码
    has_enough_calls = [
        c[0][0]
        for c in kline_service.parser.has_enough_kline_data.call_args_list
    ]
    # 收集所有 fetch 调用的股票代码
    fetch_calls = [
        c[0][0]
        for c in kline_service.fetcher.fetch_kline_data_with_limit.call_args_list
    ]

    # 后续股票的代码列表
    post_stock_codes = [
        f"HK.{(quota_trigger_idx + 1 + j):05d}"
        for j in range(post_count)
    ]

    for code in post_stock_codes:
        assert code not in has_enough_calls, (
            f"额度耗尽后的股票 {code} 不应调用 has_enough_kline_data"
        )
        assert code not in fetch_calls, (
            f"额度耗尽后的股票 {code} 不应调用 fetch_kline_data_with_limit"
        )


@given(
    pre_outcomes=st.lists(pre_outcome_strategy, min_size=0, max_size=15),
    post_count=st.integers(min_value=0, max_value=15),
    quota_error_msg=quota_error_msg_strategy,
)
@settings(max_examples=200)
def test_property6_skipped_by_quota_equals_remaining(
    pre_outcomes, post_count, quota_error_msg
):
    """Property 6: 额度耗尽快速终止 - skipped_by_quota 精确计数

    **Validates: Requirements 3.2, 3.3**

    验证 skipped_by_quota 精确等于 total 减去已处理的股票数量
    （已处理 = skipped + downloaded + failed，其中 failed 包含触发额度耗尽的那只）
    """
    container = _build_mock_container(pre_outcomes, quota_error_msg)
    task = BackgroundKlineTask(container)
    stocks = _build_stocks(pre_outcomes, post_count)

    result = task._execute(stocks)

    pre_skipped, pre_downloaded, pre_failed = _count_pre_outcomes(pre_outcomes)

    # 已处理的股票 = 前置处理的 + 触发额度耗尽的那只（计入 failed）
    processed = pre_skipped + pre_downloaded + pre_failed + 1  # +1 是触发额度耗尽的股票
    expected_skipped_by_quota = result.total - processed

    assert result.skipped_by_quota == expected_skipped_by_quota, (
        f"skipped_by_quota 应为 {expected_skipped_by_quota}，"
        f"实际为 {result.skipped_by_quota}，"
        f"total={result.total}, processed={processed}"
    )

    # 统计不变量也应成立
    assert result.total == (
        result.skipped + result.downloaded + result.failed + result.skipped_by_quota
    ), (
        f"不变量违反: total={result.total}, "
        f"skipped={result.skipped}, downloaded={result.downloaded}, "
        f"failed={result.failed}, skipped_by_quota={result.skipped_by_quota}"
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
