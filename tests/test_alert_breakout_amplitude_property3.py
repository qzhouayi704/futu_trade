#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
属性测试：Property 3 - 振幅阈值决定价格突破预警生成

**Validates: Requirements 2.1, 2.3**

*For any* 股票报价，当日内振幅 (high_price - low_price) / low_price * 100
小于 min_breakout_amplitude 时，_check_price_breakout 不产生任何预警；
当振幅大于等于阈值且价格满足接近日高/日低条件时，正常产生预警。

Tag: Feature: alert-log-optimization, Property 3: 振幅阈值决定价格突破预警生成
"""

import sys
import os
import logging
from unittest.mock import MagicMock

from hypothesis import given, settings, assume, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.alert.alert_checker import AlertChecker
from simple_trade.config.config import Config

# 抑制测试中的日志输出
logging.disable(logging.CRITICAL)


# ── hypothesis 策略 ──────────────────────────────────────────────

# 合理的价格范围（港股典型价格区间）
positive_price = st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False)

# 振幅阈值范围
amplitude_threshold = st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False)


def _make_checker(min_breakout_amplitude: float) -> AlertChecker:
    """构建 AlertChecker 实例，仅配置振幅阈值，mock 掉 db_manager"""
    config = Config()
    config.min_breakout_amplitude = min_breakout_amplitude
    db_manager = MagicMock()
    return AlertChecker(db_manager=db_manager, config=config)


def _make_quote(current_price: float, high_price: float, low_price: float) -> dict:
    """构建最小化的报价字典"""
    return {
        'code': 'HK.00700',
        'name': '腾讯控股',
        'current_price': current_price,
        'high_price': high_price,
        'low_price': low_price,
    }


def _calc_amplitude(high_price: float, low_price: float) -> float:
    """计算日内振幅百分比"""
    return (high_price - low_price) / low_price * 100


# ── 属性测试 ──────────────────────────────────────────────────────

@given(
    low_price=positive_price,
    current_price=positive_price,
    threshold=amplitude_threshold,
    # amplitude_frac: 振幅占阈值的比例，确保 < 1.0 即振幅 < 阈值
    amplitude_frac=st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=500)
def test_property3_small_amplitude_no_alerts(low_price, current_price, threshold, amplitude_frac):
    """Property 3（振幅不足场景）：振幅小于阈值时不产生任何预警

    **Validates: Requirements 2.1, 2.3**

    当 low_price > 0 且 high_price > 0 且振幅 < threshold 时，
    _check_price_breakout 不应产生任何预警。
    """
    # 构造 high_price 使振幅 = threshold * amplitude_frac < threshold
    target_amplitude = threshold * amplitude_frac
    high_price = low_price * (1 + target_amplitude / 100)
    assume(high_price <= 10000.0)
    assume(high_price >= low_price)

    amplitude = _calc_amplitude(high_price, low_price)
    assume(amplitude < threshold)

    checker = _make_checker(threshold)
    quote = _make_quote(current_price, high_price, low_price)
    alerts = []

    checker._check_price_breakout(quote, alerts)

    assert len(alerts) == 0, (
        f"振幅 {amplitude:.4f}% < 阈值 {threshold}%，不应产生预警，"
        f"但产生了 {len(alerts)} 条: {[a['type'] for a in alerts]}"
    )


@given(
    low_price=positive_price,
    spread_ratio=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    threshold=amplitude_threshold,
)
@settings(max_examples=500)
def test_property3_sufficient_amplitude_near_high(low_price, spread_ratio, threshold):
    """Property 3（振幅足够 + 接近日高）：振幅 >= 阈值且价格接近日高时产生预警

    **Validates: Requirements 2.1, 2.3**

    构造 high_price 使振幅 >= threshold，且 current_price 接近 high_price（ratio >= 0.98），
    验证产生"接近日高"预警。
    """
    # 构造 high_price 使振幅恰好 >= threshold
    min_high = low_price * (1 + threshold / 100)
    # spread_ratio 控制振幅超出阈值的程度
    high_price = min_high + spread_ratio * low_price
    assume(high_price <= 10000.0)

    amplitude = _calc_amplitude(high_price, low_price)
    assume(amplitude >= threshold)

    # current_price 接近日高（ratio >= 0.98）
    current_price = high_price * 0.99  # 确保 >= 0.98
    assume(current_price > 0)

    checker = _make_checker(threshold)
    quote = _make_quote(current_price, high_price, low_price)
    alerts = []

    checker._check_price_breakout(quote, alerts)

    alert_types = [a['type'] for a in alerts]
    assert '接近日高' in alert_types, (
        f"振幅 {amplitude:.4f}% >= 阈值 {threshold}%，"
        f"current/high = {current_price/high_price:.4f} >= 0.98，"
        f"应产生'接近日高'预警，但实际预警: {alert_types}"
    )


@given(
    low_price=positive_price,
    spread_ratio=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    threshold=amplitude_threshold,
)
@settings(max_examples=500)
def test_property3_sufficient_amplitude_near_low(low_price, spread_ratio, threshold):
    """Property 3（振幅足够 + 接近日低）：振幅 >= 阈值且价格接近日低时产生预警

    **Validates: Requirements 2.1, 2.3**

    构造 high_price 使振幅 >= threshold，且 current_price 接近 low_price（ratio <= 1.02），
    验证产生"接近日低"预警。
    """
    min_high = low_price * (1 + threshold / 100)
    high_price = min_high + spread_ratio * low_price
    assume(high_price <= 10000.0)

    amplitude = _calc_amplitude(high_price, low_price)
    assume(amplitude >= threshold)

    # current_price 接近日低（ratio <= 1.02）
    current_price = low_price * 1.01  # 确保 <= 1.02
    assume(current_price > 0)

    checker = _make_checker(threshold)
    quote = _make_quote(current_price, high_price, low_price)
    alerts = []

    checker._check_price_breakout(quote, alerts)

    alert_types = [a['type'] for a in alerts]
    assert '接近日低' in alert_types, (
        f"振幅 {amplitude:.4f}% >= 阈值 {threshold}%，"
        f"current/low = {current_price/low_price:.4f} <= 1.02，"
        f"应产生'接近日低'预警，但实际预警: {alert_types}"
    )


@given(
    low_price=positive_price,
    spread_ratio=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    threshold=amplitude_threshold,
    mid_factor=st.floats(min_value=0.05, max_value=0.95, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=500)
def test_property3_sufficient_amplitude_mid_price_no_breakout(
    low_price, spread_ratio, threshold, mid_factor
):
    """Property 3（振幅足够但价格居中）：振幅 >= 阈值但价格不接近日高/日低时无预警

    **Validates: Requirements 2.1, 2.3**

    构造 high_price 使振幅 >= threshold，但 current_price 处于中间区域
    （不满足 >= 0.98 * high 也不满足 <= 1.02 * low），验证不产生预警。
    """
    min_high = low_price * (1 + threshold / 100)
    high_price = min_high + spread_ratio * low_price
    assume(high_price <= 10000.0)

    amplitude = _calc_amplitude(high_price, low_price)
    assume(amplitude >= threshold)

    # 需要足够的价格空间来放置中间价格
    upper_bound = high_price * 0.98  # 低于此值才不触发"接近日高"
    lower_bound = low_price * 1.02   # 高于此值才不触发"接近日低"
    assume(lower_bound < upper_bound)

    # current_price 在中间区域
    current_price = lower_bound + mid_factor * (upper_bound - lower_bound)
    assume(current_price > 0)
    # 双重确认不满足触发条件
    assume(current_price / high_price < 0.98)
    assume(current_price / low_price > 1.02)

    checker = _make_checker(threshold)
    quote = _make_quote(current_price, high_price, low_price)
    alerts = []

    checker._check_price_breakout(quote, alerts)

    assert len(alerts) == 0, (
        f"振幅 {amplitude:.4f}% >= 阈值 {threshold}%，"
        f"但价格居中 (current/high={current_price/high_price:.4f}, "
        f"current/low={current_price/low_price:.4f})，"
        f"不应产生预警，但产生了: {[a['type'] for a in alerts]}"
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
