#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DecisionAdvisor 评估属性测试

Property 4: 数据缺失时评估降级不抛异常
Property 5: AI 增强失败不影响基础建议
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock
from hypothesis import given, settings
from hypothesis import strategies as st

from simple_trade.services.advisor.decision_advisor import DecisionAdvisor
from simple_trade.services.advisor.models import (
    EvaluationContext, AdviceType, DecisionAdvice,
)


# ==================== 策略 ====================

reasonable_float = st.floats(min_value=-20.0, max_value=30.0, allow_nan=False, allow_infinity=False)

position_st = st.fixed_dictionaries({
    'stock_code': st.from_regex(r'HK\.\d{5}', fullmatch=True),
    'stock_name': st.text(min_size=1, max_size=4, alphabet='测试股票甲乙丙'),
    'cost_price': st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    'current_price': st.floats(min_value=0.5, max_value=600.0, allow_nan=False, allow_infinity=False),
    'pl_ratio': reasonable_float,
})

quote_st = st.fixed_dictionaries({
    'code': st.from_regex(r'HK\.\d{5}', fullmatch=True),
    'last_price': st.floats(min_value=0.5, max_value=500.0, allow_nan=False, allow_infinity=False),
    'turnover_rate': st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False),
    'volume': st.integers(min_value=0, max_value=10000000),
    'change_rate': reasonable_float,
    'high_price': st.floats(min_value=0.5, max_value=600.0, allow_nan=False, allow_infinity=False),
    'low_price': st.floats(min_value=0.1, max_value=500.0, allow_nan=False, allow_infinity=False),
    'prev_close_price': st.floats(min_value=0.5, max_value=500.0, allow_nan=False, allow_infinity=False),
})

# 随机选择哪些数据为空
empty_choice = st.sampled_from(['quotes', 'klines', 'signals', 'quotes+klines', 'all_empty'])


# ==================== Property 4 ====================

@given(
    positions=st.lists(position_st, min_size=1, max_size=5),
    empty=empty_choice,
)
@settings(max_examples=100)
def test_missing_data_graceful_degradation(positions, empty):
    """Property 4: 数据缺失时评估降级不抛异常

    **Validates: Requirements 1.4, 6.2, 6.3**
    """
    quotes = []
    signals = []
    kline_cache = {}

    if empty == 'signals':
        signals = []
    elif empty == 'quotes':
        quotes = []
    elif empty == 'klines':
        kline_cache = {}
    elif empty == 'quotes+klines':
        quotes = []
        kline_cache = {}
    else:  # all_empty
        pass

    ctx = EvaluationContext(
        positions=positions,
        quotes=quotes,
        signals=signals,
        kline_cache=kline_cache,
    )

    advisor = DecisionAdvisor()
    # 不应抛出异常
    result = advisor.evaluate(ctx)

    assert isinstance(result, list)
    for advice in result:
        assert isinstance(advice, DecisionAdvice)
        assert advice.advice_type is not None
        assert advice.urgency is not None
        assert advice.title

    # 无 K线时不应有加仓建议
    if not kline_cache:
        for advice in result:
            assert advice.advice_type != AdviceType.ADD_POSITION, \
                "无K线数据时不应生成加仓建议"


# ==================== Property 5 ====================

exception_types = st.sampled_from([
    ValueError, KeyError, AttributeError, RuntimeError,
    TypeError, ConnectionError, TimeoutError,
])


@given(exc_type=exception_types)
@settings(max_examples=100)
def test_ai_enhancement_failure_preserves_base_advices(exc_type):
    """Property 5: AI 增强失败不影响基础建议

    **Validates: Requirements 6.4**
    """
    # 创建带 mock AI analyst 的 advisor
    mock_analyst = MagicMock()
    mock_analyst.trigger_detector.detect_triggers.side_effect = exc_type("AI故障")

    advisor = DecisionAdvisor(gemini_analyst=mock_analyst)

    ctx = EvaluationContext(
        positions=[{
            'stock_code': 'HK.00700', 'stock_name': '腾讯',
            'cost_price': 300.0, 'current_price': 280.0, 'pl_ratio': -6.7,
        }],
        quotes=[{
            'code': 'HK.00700', 'last_price': 280.0,
            'turnover_rate': 2.0, 'volume': 5000000,
            'change_rate': -2.0, 'high_price': 290.0,
            'low_price': 275.0, 'prev_close_price': 286.0,
        }],
        signals=[],
        kline_cache={},
    )

    # 先获取规则引擎的基础建议
    base_advices = advisor.evaluate(ctx)

    # 用 AI 增强（应该失败但不影响结果）
    loop = asyncio.new_event_loop()
    try:
        enhanced = loop.run_until_complete(
            advisor.enhance_with_ai(base_advices, ctx)
        )
    finally:
        loop.close()

    # 增强后的建议数量应与基础一致
    assert len(enhanced) == len(base_advices)
    for base, enh in zip(base_advices, enhanced):
        assert base.advice_type == enh.advice_type
        assert base.urgency == enh.urgency
        assert base.title == enh.title
