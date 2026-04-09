#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
属性测试：Property 1 & Property 2 - 预警聚合正确性

**Validates: Requirements 1.1, 1.3**

Property 1: 预警聚合日志条数等于去重股票数
*For any* 预警列表，按 stock_code 聚合后输出的日志条数应等于列表中不同
stock_code 的数量。单条预警的股票输出原始消息，多条预警的股票输出包含
所有预警类型的摘要。

Property 2: 预警聚合不修改返回数据
*For any* 报价列表，调用 check_alerts 后返回的预警列表内容和数量应与
聚合日志操作前完全一致。聚合仅影响日志输出，不影响返回的数据结构。

Tag:
  Feature: alert-log-optimization, Property 1: 预警聚合日志条数等于去重股票数
  Feature: alert-log-optimization, Property 2: 预警聚合不修改返回数据
"""

import sys
import os
import copy
import logging
from unittest.mock import MagicMock, patch
from datetime import datetime

from hypothesis import given, settings, assume, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.alert.alert_checker import AlertChecker
from simple_trade.config.config import Config


# ── hypothesis 策略 ──────────────────────────────────────────────

# 港股代码池（用于生成随机 stock_code）
STOCK_CODES = [
    'HK.00700', 'HK.09988', 'HK.01810', 'HK.03690',
    'HK.09618', 'HK.02318', 'HK.00388', 'HK.01024',
]

STOCK_NAMES = {
    'HK.00700': '腾讯控股', 'HK.09988': '阿里巴巴',
    'HK.01810': '小米集团', 'HK.03690': '美团',
    'HK.09618': '京东集团', 'HK.02318': '中国平安',
    'HK.00388': '香港交易所', 'HK.01024': '快手',
}

ALERT_TYPES = ['涨幅预警', '跌幅预警', '成交量异常', '接近日高', '接近日低']
ALERT_LEVELS = ['info', 'warning', 'danger']


# 单条预警的 strategy
alert_strategy = st.fixed_dictionaries({
    'stock_code': st.sampled_from(STOCK_CODES),
    'type': st.sampled_from(ALERT_TYPES),
    'level': st.sampled_from(ALERT_LEVELS),
    'current_price': st.floats(
        min_value=1.0, max_value=1000.0,
        allow_nan=False, allow_infinity=False,
    ),
    'change_percent': st.floats(
        min_value=-20.0, max_value=20.0,
        allow_nan=False, allow_infinity=False,
    ),
}).map(lambda d: {
    **d,
    'stock_name': STOCK_NAMES[d['stock_code']],
    'message': (
        f"{STOCK_NAMES[d['stock_code']]}({d['stock_code']}) "
        f"{d['type']}: {d['current_price']:.2f}"
    ),
    'timestamp': datetime.now().isoformat(),
})

# 预警列表（1~20 条）
alerts_list_strategy = st.lists(alert_strategy, min_size=1, max_size=20)


# ── Property 1 ───────────────────────────────────────────────────

@given(alerts=alerts_list_strategy)
@settings(max_examples=200)
def test_property1_aggregated_log_count_equals_unique_stocks(alerts):
    """Property 1: 预警聚合日志条数等于去重股票数

    **Validates: Requirements 1.1**

    *For any* 预警列表，_log_aggregated_alerts 输出的 INFO 日志条数
    应等于列表中不同 stock_code 的数量。
    """
    config = Config()
    db_manager = MagicMock()
    checker = AlertChecker(db_manager=db_manager, config=config)

    expected_unique_stocks = len({a['stock_code'] for a in alerts})

    with patch('simple_trade.services.alert.alert_checker.logging') as mock_log:
        checker._log_aggregated_alerts(alerts)

        info_calls = mock_log.info.call_args_list
        assert len(info_calls) == expected_unique_stocks, (
            f"期望 {expected_unique_stocks} 条聚合日志，"
            f"实际 {len(info_calls)} 条。"
            f"预警列表: {[(a['stock_code'], a['type']) for a in alerts]}"
        )


@given(alerts=alerts_list_strategy)
@settings(max_examples=200)
def test_property1_single_alert_uses_original_message(alerts):
    """Property 1 补充: 单条预警的股票输出原始消息

    **Validates: Requirements 1.1**

    对于只有一条预警的股票，日志应包含该预警的原始 message。
    """
    config = Config()
    db_manager = MagicMock()
    checker = AlertChecker(db_manager=db_manager, config=config)

    # 按 stock_code 分组，找出只有一条预警的股票
    grouped = {}
    for a in alerts:
        grouped.setdefault(a['stock_code'], []).append(a)

    single_stocks = {
        code: items[0] for code, items in grouped.items()
        if len(items) == 1
    }

    if not single_stocks:
        return  # 没有单条预警的股票，跳过

    with patch('simple_trade.services.alert.alert_checker.logging') as mock_log:
        checker._log_aggregated_alerts(alerts)

        logged_messages = [
            call.args[0] for call in mock_log.info.call_args_list
        ]

        for code, alert in single_stocks.items():
            expected_msg = f"预警触发: {alert['message']}"
            assert expected_msg in logged_messages, (
                f"单条预警股票 {code} 应输出原始消息 '{expected_msg}'，"
                f"实际日志: {logged_messages}"
            )


@given(alerts=alerts_list_strategy)
@settings(max_examples=200)
def test_property1_multi_alerts_summary_contains_types(alerts):
    """Property 1 补充: 多条预警的股票输出包含所有预警类型的摘要

    **Validates: Requirements 1.1**

    对于有多条预警的股票，日志应包含股票名称、代码和所有预警类型。
    """
    config = Config()
    db_manager = MagicMock()
    checker = AlertChecker(db_manager=db_manager, config=config)

    grouped = {}
    for a in alerts:
        grouped.setdefault(a['stock_code'], []).append(a)

    multi_stocks = {
        code: items for code, items in grouped.items()
        if len(items) > 1
    }

    if not multi_stocks:
        return

    with patch('simple_trade.services.alert.alert_checker.logging') as mock_log:
        checker._log_aggregated_alerts(alerts)

        logged_messages = [
            call.args[0] for call in mock_log.info.call_args_list
        ]

        for code, stock_alerts in multi_stocks.items():
            name = stock_alerts[0]['stock_name']
            # 验证有一条日志包含该股票的代码和名称
            matching = [
                m for m in logged_messages
                if code in m and name in m
            ]
            assert len(matching) == 1, (
                f"多条预警股票 {name}({code}) 应有一条摘要日志，"
                f"匹配到 {len(matching)} 条。日志: {logged_messages}"
            )

            # 验证摘要中包含所有预警类型
            summary_msg = matching[0]
            for alert in stock_alerts:
                assert alert['type'] in summary_msg, (
                    f"摘要日志应包含预警类型 '{alert['type']}'，"
                    f"实际: '{summary_msg}'"
                )


# ── Property 2 ───────────────────────────────────────────────────

@given(alerts=alerts_list_strategy)
@settings(max_examples=200)
def test_property2_aggregation_does_not_modify_alerts(alerts):
    """Property 2: 预警聚合不修改返回数据

    **Validates: Requirements 1.3**

    *For any* 预警列表，调用 _log_aggregated_alerts 后，
    列表的内容和数量应与调用前完全一致。
    """
    config = Config()
    db_manager = MagicMock()
    checker = AlertChecker(db_manager=db_manager, config=config)

    # 深拷贝一份作为基准
    alerts_before = copy.deepcopy(alerts)

    # 抑制日志输出
    logging.disable(logging.CRITICAL)
    try:
        checker._log_aggregated_alerts(alerts)
    finally:
        logging.disable(logging.NOTSET)

    # 验证数量不变
    assert len(alerts) == len(alerts_before), (
        f"聚合后预警数量变化: {len(alerts_before)} -> {len(alerts)}"
    )

    # 验证每条预警内容不变
    for i, (before, after) in enumerate(zip(alerts_before, alerts)):
        assert before == after, (
            f"第 {i} 条预警被修改。\n"
            f"  修改前: {before}\n"
            f"  修改后: {after}"
        )


@given(alerts=st.lists(alert_strategy, min_size=0, max_size=20))
@settings(max_examples=200)
def test_property2_empty_alerts_safe(alerts):
    """Property 2 补充: 空预警列表调用聚合也安全

    **Validates: Requirements 1.3**

    包括空列表在内的任意预警列表，聚合操作都不应抛出异常或修改数据。
    """
    config = Config()
    db_manager = MagicMock()
    checker = AlertChecker(db_manager=db_manager, config=config)

    alerts_before = copy.deepcopy(alerts)

    logging.disable(logging.CRITICAL)
    try:
        checker._log_aggregated_alerts(alerts)
    finally:
        logging.disable(logging.NOTSET)

    assert alerts == alerts_before, "聚合操作不应修改预警列表"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
