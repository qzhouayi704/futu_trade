#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Property 2: EvaluationContext 评估总是返回有效结果

对于任意有效的 EvaluationContext（positions 非空），
DecisionAdvisor.evaluate(ctx) 始终返回 List[DecisionAdvice]，
且每个元素都有有效的 advice_type、urgency 和非空 title。

**Validates: Requirements 3.3**
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from simple_trade.services.advisor.decision_advisor import DecisionAdvisor
from simple_trade.services.advisor.models import (
    EvaluationContext, AdviceType, Urgency, DecisionAdvice,
)


# ==================== 策略 ====================

reasonable_float = st.floats(
    min_value=-20.0, max_value=30.0,
    allow_nan=False, allow_infinity=False,
)

stock_code_st = st.from_regex(r'HK\.\d{5}', fullmatch=True)

position_st = st.fixed_dictionaries({
    'stock_code': stock_code_st,
    'stock_name': st.text(min_size=1, max_size=4, alphabet='测试股票甲乙丙'),
    'cost_price': st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    'current_price': st.floats(min_value=0.5, max_value=600.0, allow_nan=False, allow_infinity=False),
    'pl_ratio': reasonable_float,
})

quote_st = st.fixed_dictionaries({
    'code': stock_code_st,
    'last_price': st.floats(min_value=0.5, max_value=500.0, allow_nan=False, allow_infinity=False),
    'turnover_rate': st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False),
    'volume': st.integers(min_value=0, max_value=10_000_000),
    'change_rate': reasonable_float,
    'high_price': st.floats(min_value=0.5, max_value=600.0, allow_nan=False, allow_infinity=False),
    'low_price': st.floats(min_value=0.1, max_value=500.0, allow_nan=False, allow_infinity=False),
    'prev_close_price': st.floats(min_value=0.5, max_value=500.0, allow_nan=False, allow_infinity=False),
})

signal_st = st.fixed_dictionaries({
    'stock_code': stock_code_st,
    'stock_name': st.text(min_size=1, max_size=4, alphabet='信号标的'),
    'signal_type': st.sampled_from(['BUY', 'SELL']),
    'signal_price': st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    'is_executed': st.booleans(),
})

# K线条目：dict 格式 {'close': x, 'volume': y}
kline_entry_st = st.fixed_dictionaries({
    'close': st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    'volume': st.integers(min_value=100, max_value=10_000_000),
    'open': st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    'high': st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    'low': st.floats(min_value=0.5, max_value=500.0, allow_nan=False, allow_infinity=False),
})

VALID_ADVICE_TYPES = set(AdviceType)
VALID_URGENCIES = set(Urgency)


# ==================== Property 2 ====================

@given(
    positions=st.lists(position_st, min_size=1, max_size=5),
    quotes=st.lists(quote_st, min_size=0, max_size=5),
    signals=st.lists(signal_st, min_size=0, max_size=3),
    kline_count=st.integers(min_value=0, max_value=3),
    kline_length=st.integers(min_value=0, max_value=25),
)
@settings(max_examples=100)
def test_evaluate_always_returns_valid_advices(
    positions, quotes, signals, kline_count, kline_length,
):
    """Property 2: EvaluationContext 评估总是返回有效结果

    **Feature: advisor-optimization, Property 2: EvaluationContext 评估总是返回有效结果**
    **Validates: Requirements 3.3**
    """
    # 构建 kline_cache：用 positions 中的 stock_code 作为 key
    kline_cache = {}
    for i, pos in enumerate(positions[:kline_count]):
        code = pos['stock_code']
        kline_cache[code] = [
            {'close': 100.0 + j * 0.5, 'volume': 1000 * (j + 1),
             'open': 99.0, 'high': 101.0, 'low': 98.0}
            for j in range(kline_length)
        ]

    ctx = EvaluationContext(
        positions=positions,
        quotes=quotes,
        signals=signals,
        kline_cache=kline_cache,
    )

    advisor = DecisionAdvisor()
    result = advisor.evaluate(ctx)

    # 返回值必须是 list
    assert isinstance(result, list)

    # 每个元素必须是 DecisionAdvice 且字段有效
    for advice in result:
        assert isinstance(advice, DecisionAdvice)
        assert advice.advice_type in VALID_ADVICE_TYPES
        assert advice.urgency in VALID_URGENCIES
        assert isinstance(advice.title, str) and len(advice.title) > 0
        assert isinstance(advice.id, str) and len(advice.id) > 0
