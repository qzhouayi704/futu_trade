#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
属性测试：BackgroundKlineTask Property 5 - 单只股票异常不影响其余股票处理

**Validates: Requirements 2.4**

对于任意股票列表，如果其中某只股票下载时抛出非额度耗尽的异常，
其余股票仍应被正常检查和处理，最终 downloaded + skipped + failed 应等于 total
（当 quota_exhausted 为 False 时）。

Tag: Feature: async-kline-download, Property 5: 单只股票异常不影响其余股票处理
"""

import sys
import os
import logging
from enum import Enum
from unittest.mock import MagicMock

from hypothesis import given, settings, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.market_data.kline.background_kline_task import (
    BackgroundKlineTask,
    KlineDownloadResult,
)

# 抑制测试中的日志输出
logging.disable(logging.CRITICAL)


class StockOutcome(Enum):
    """单只股票的可能结果（不含额度耗尽）"""
    SKIP = "skip"               # 数据充足，跳过
    DOWNLOAD_OK = "download_ok" # 下载成功
    DOWNLOAD_EMPTY = "empty"    # 下载返回空数据
    SAVE_FAIL = "save_fail"     # 保存失败（saved_count=0）
    NO_CODE = "no_code"         # 缺少 code 字段
    EXCEPTION = "exception"     # 非额度异常


# ── hypothesis 策略 ──────────────────────────────────────────────

# 非额度耗尽的结果类型
non_quota_outcome = st.sampled_from([
    StockOutcome.SKIP,
    StockOutcome.DOWNLOAD_OK,
    StockOutcome.DOWNLOAD_EMPTY,
    StockOutcome.SAVE_FAIL,
    StockOutcome.NO_CODE,
    StockOutcome.EXCEPTION,
])

# 生成股票列表（2~30只），确保至少有一只异常股票
# 通过 filter 保证列表中至少包含一个 EXCEPTION
stock_list_with_exception = st.lists(
    non_quota_outcome,
    min_size=2,
    max_size=30,
).filter(
    lambda outcomes: any(o == StockOutcome.EXCEPTION for o in outcomes)
)

# 生成任意非额度耗尽的股票列表（1~30只）
stock_list_any = st.lists(
    non_quota_outcome,
    min_size=1,
    max_size=30,
)


def _build_mock_container(outcomes: list[StockOutcome]):
    """根据预期结果列表构建 mock container（不含额度耗尽场景）"""
    container = MagicMock()
    kline_service = container.kline_service

    # 配置请求延迟为 0，加速测试
    kline_service.config.kline_rate_limit = {"request_delay": 0}

    # 额度预检查：正常通过
    kline_service.get_quota_info.return_value = {
        "remaining": 100,
        "status": "connected",
    }

    has_enough_results = []
    fetch_side_effects = []
    save_results = []

    for outcome in outcomes:
        if outcome == StockOutcome.NO_CODE:
            # 缺少 code 字段，不会调用 has_enough
            continue
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
                # 非额度耗尽异常（关键词不含 quota/额度 等）
                fetch_side_effects.append(Exception("网络连接超时"))

    kline_service.parser.has_enough_kline_data.side_effect = has_enough_results
    kline_service.fetcher.fetch_kline_data_with_limit.side_effect = (
        fetch_side_effects
    )
    kline_service.parser.filter_today_incomplete_data.side_effect = (
        lambda code, data: data
    )
    kline_service.storage.save_kline_batch.side_effect = save_results

    return container


def _build_stocks(outcomes: list[StockOutcome]) -> list[dict]:
    """根据结果列表生成股票字典列表"""
    stocks = []
    for i, outcome in enumerate(outcomes):
        if outcome == StockOutcome.NO_CODE:
            stocks.append({"name": f"无代码股票{i}"})
        else:
            stocks.append({"code": f"HK.{i:05d}"})
    return stocks


def _count_expected(outcomes: list[StockOutcome]) -> dict:
    """计算预期的各类计数"""
    expected_skipped = sum(1 for o in outcomes if o == StockOutcome.SKIP)
    expected_downloaded = sum(1 for o in outcomes if o == StockOutcome.DOWNLOAD_OK)
    expected_failed = sum(
        1 for o in outcomes
        if o in (
            StockOutcome.DOWNLOAD_EMPTY,
            StockOutcome.SAVE_FAIL,
            StockOutcome.NO_CODE,
            StockOutcome.EXCEPTION,
        )
    )
    return {
        "skipped": expected_skipped,
        "downloaded": expected_downloaded,
        "failed": expected_failed,
    }


# ── 属性测试 ──────────────────────────────────────────────────────

@given(outcomes=stock_list_with_exception)
@settings(max_examples=200)
def test_property5_exception_does_not_affect_other_stocks(outcomes):
    """Property 5: 单只股票异常不影响其余股票处理

    **Validates: Requirements 2.4**

    当列表中存在抛出非额度耗尽异常的股票时，
    其余股票仍应被正常检查和处理。
    验证：
    1. quota_exhausted 为 False
    2. downloaded + skipped + failed == total
    3. 各分类计数与预期一致
    """
    container = _build_mock_container(outcomes)
    task = BackgroundKlineTask(container)
    stocks = _build_stocks(outcomes)

    result = task._execute(stocks)

    # 非额度耗尽场景
    assert result.quota_exhausted is False, (
        f"不应触发额度耗尽: quota_exhausted={result.quota_exhausted}"
    )

    # 核心不变量：所有股票都被处理
    assert result.downloaded + result.skipped + result.failed == result.total, (
        f"所有股票应被处理: total={result.total}, "
        f"downloaded={result.downloaded}, skipped={result.skipped}, "
        f"failed={result.failed}"
    )

    # 各分类计数与预期一致
    expected = _count_expected(outcomes)
    assert result.skipped == expected["skipped"], (
        f"跳过数不匹配: expected={expected['skipped']}, got={result.skipped}"
    )
    assert result.downloaded == expected["downloaded"], (
        f"下载数不匹配: expected={expected['downloaded']}, got={result.downloaded}"
    )
    assert result.failed == expected["failed"], (
        f"失败数不匹配: expected={expected['failed']}, got={result.failed}"
    )


@given(outcomes=stock_list_any)
@settings(max_examples=200)
def test_property5_all_stocks_processed_without_quota_exhaustion(outcomes):
    """Property 5: 无额度耗尽时所有股票均被处理

    **Validates: Requirements 2.4**

    对于任意非额度耗尽的股票列表，
    最终 downloaded + skipped + failed 应等于 total，
    且 quota_exhausted 为 False，skipped_by_quota 为 0。
    """
    container = _build_mock_container(outcomes)
    task = BackgroundKlineTask(container)
    stocks = _build_stocks(outcomes)

    result = task._execute(stocks)

    assert result.quota_exhausted is False
    assert result.skipped_by_quota == 0

    assert result.downloaded + result.skipped + result.failed == result.total, (
        f"所有股票应被处理: total={result.total}, "
        f"downloaded={result.downloaded}, skipped={result.skipped}, "
        f"failed={result.failed}"
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
