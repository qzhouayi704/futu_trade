#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
属性测试：Property 5 & Property 6 - 建议变化检测和指纹一致性

**Validates: Requirements 5.1, 5.2, 5.3**

Property 5: 建议变化检测正确性
*For any* 两个建议列表，如果它们的内容指纹集合相同，则 `_is_advice_changed`
返回 False；如果指纹集合不同，则返回 True。

Property 6: 建议指纹一致性
*For any* DecisionAdvice 对象，其指纹由 `(advice_type, sell_stock_code,
buy_stock_code, urgency)` 四元组唯一确定。两个建议对象当且仅当这四个字段
完全相同时，指纹相同。

Tag:
  Feature: alert-log-optimization, Property 5: 建议变化检测正确性
  Feature: alert-log-optimization, Property 6: 建议指纹一致性
"""

import sys
import os
import uuid

from hypothesis import given, settings, assume, strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.advisor.models import (
    DecisionAdvice, AdviceType, Urgency,
)
from simple_trade.services.advisor.decision_advisor import DecisionAdvisor


# ── hypothesis 策略 ──────────────────────────────────────────────

STOCK_CODES = [
    'HK.00700', 'HK.09988', 'HK.01810', 'HK.03690',
    'HK.09618', 'HK.02318', 'HK.00388', 'HK.01024',
    None,
]

advice_type_st = st.sampled_from(list(AdviceType))
urgency_st = st.sampled_from(list(Urgency))
stock_code_st = st.sampled_from(STOCK_CODES)


def _make_advice(
    advice_type: AdviceType,
    urgency: Urgency,
    sell_stock_code=None,
    buy_stock_code=None,
) -> DecisionAdvice:
    """构造一个 DecisionAdvice，仅指纹相关字段由参数控制，其余用默认值。"""
    return DecisionAdvice(
        id=str(uuid.uuid4()),
        advice_type=advice_type,
        urgency=urgency,
        title="测试建议",
        description="属性测试生成",
        sell_stock_code=sell_stock_code,
        buy_stock_code=buy_stock_code,
    )


# 单个 DecisionAdvice 的 strategy
advice_strategy = st.builds(
    _make_advice,
    advice_type=advice_type_st,
    urgency=urgency_st,
    sell_stock_code=stock_code_st,
    buy_stock_code=stock_code_st,
)

# 建议列表（0~10 条）
advice_list_strategy = st.lists(advice_strategy, min_size=0, max_size=10)


# ── Property 5: 建议变化检测正确性 ──────────────────────────────

@given(advices_a=advice_list_strategy, advices_b=advice_list_strategy)
@settings(max_examples=200)
def test_property5_same_fingerprints_means_no_change(advices_a, advices_b):
    """Property 5: 指纹集合相同 → _is_advice_changed 返回 False

    **Validates: Requirements 5.1**

    将 advices_a 设为缓存，用 advices_b 调用 _is_advice_changed。
    如果两者的指纹集合相同，结果应为 False。
    """
    advisor = DecisionAdvisor()
    fp = DecisionAdvisor._advice_fingerprint

    fps_a = {fp(a) for a in advices_a}
    fps_b = {fp(a) for a in advices_b}

    # 设置缓存
    advisor._advice_cache = advices_a

    result = advisor._is_advice_changed(advices_b)

    if fps_a == fps_b:
        assert result is False, (
            f"指纹集合相同时应返回 False，但返回了 True。\n"
            f"  fps_a={fps_a}\n  fps_b={fps_b}"
        )


@given(advices_a=advice_list_strategy, advices_b=advice_list_strategy)
@settings(max_examples=200)
def test_property5_different_fingerprints_means_changed(advices_a, advices_b):
    """Property 5: 指纹集合不同 → _is_advice_changed 返回 True

    **Validates: Requirements 5.2**

    将 advices_a 设为缓存，用 advices_b 调用 _is_advice_changed。
    如果两者的指纹集合不同，结果应为 True。
    """
    advisor = DecisionAdvisor()
    fp = DecisionAdvisor._advice_fingerprint

    fps_a = {fp(a) for a in advices_a}
    fps_b = {fp(a) for a in advices_b}

    assume(fps_a != fps_b)

    advisor._advice_cache = advices_a

    result = advisor._is_advice_changed(advices_b)

    assert result is True, (
        f"指纹集合不同时应返回 True，但返回了 False。\n"
        f"  fps_a={fps_a}\n  fps_b={fps_b}"
    )


@given(advices=advice_list_strategy)
@settings(max_examples=200)
def test_property5_identical_list_is_not_changed(advices):
    """Property 5 补充: 同一列表与自身比较应返回 False

    **Validates: Requirements 5.1**
    """
    advisor = DecisionAdvisor()
    advisor._advice_cache = list(advices)  # 浅拷贝

    result = advisor._is_advice_changed(advices)

    assert result is False, (
        f"同一列表与自身比较应返回 False，但返回了 True。"
    )


# ── Property 6: 建议指纹一致性 ──────────────────────────────────

@given(
    advice_type=advice_type_st,
    urgency=urgency_st,
    sell_code=stock_code_st,
    buy_code=stock_code_st,
)
@settings(max_examples=200)
def test_property6_same_tuple_same_fingerprint(
    advice_type, urgency, sell_code, buy_code,
):
    """Property 6: 四元组相同 → 指纹相同

    **Validates: Requirements 5.3**

    两个 DecisionAdvice 对象如果 (advice_type, sell_stock_code,
    buy_stock_code, urgency) 完全相同，则指纹必须相同，
    即使其他字段（id, title, description 等）不同。
    """
    fp = DecisionAdvisor._advice_fingerprint

    a1 = _make_advice(advice_type, urgency, sell_code, buy_code)
    a2 = DecisionAdvice(
        id="different-id",
        advice_type=advice_type,
        urgency=urgency,
        title="不同标题",
        description="不同描述",
        sell_stock_code=sell_code,
        buy_stock_code=buy_code,
        sell_price=999.99,
        buy_price=888.88,
    )

    assert fp(a1) == fp(a2), (
        f"四元组相同但指纹不同。\n"
        f"  a1 fp={fp(a1)}\n  a2 fp={fp(a2)}"
    )


@given(
    type_a=advice_type_st, type_b=advice_type_st,
    urg_a=urgency_st, urg_b=urgency_st,
    sell_a=stock_code_st, sell_b=stock_code_st,
    buy_a=stock_code_st, buy_b=stock_code_st,
)
@settings(max_examples=300)
def test_property6_different_tuple_different_fingerprint(
    type_a, type_b, urg_a, urg_b,
    sell_a, sell_b, buy_a, buy_b,
):
    """Property 6: 四元组不同 → 指纹不同

    **Validates: Requirements 5.3**

    两个 DecisionAdvice 对象如果 (advice_type, sell_stock_code,
    buy_stock_code, urgency) 中至少有一个字段不同，则指纹必须不同。
    """
    # 确保四元组至少有一个字段不同
    assume(
        (type_a, sell_a, buy_a, urg_a)
        != (type_b, sell_b, buy_b, urg_b)
    )

    fp = DecisionAdvisor._advice_fingerprint

    a1 = _make_advice(type_a, urg_a, sell_a, buy_a)
    a2 = _make_advice(type_b, urg_b, sell_b, buy_b)

    assert fp(a1) != fp(a2), (
        f"四元组不同但指纹相同。\n"
        f"  a1=({type_a}, {sell_a}, {buy_a}, {urg_a}) fp={fp(a1)}\n"
        f"  a2=({type_b}, {sell_b}, {buy_b}, {urg_b}) fp={fp(a2)}"
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
