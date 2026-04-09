#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动日内交易服务 - Property-Based Tests

使用 hypothesis 验证自动交易核心逻辑的正确性。
"""

import sys
import os
import importlib.util

# 直接加载模块，避免触发完整导入链
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

_at_spec = importlib.util.spec_from_file_location(
    "simple_trade.services.trading.aggressive.auto_trade_models",
    os.path.join(_project_root, "simple_trade", "services", "trading", "aggressive", "auto_trade_models.py")
)
_at_mod = importlib.util.module_from_spec(_at_spec)
sys.modules["simple_trade.services.trading.aggressive.auto_trade_models"] = _at_mod
_at_spec.loader.exec_module(_at_mod)

import pytest
from hypothesis import given, strategies as st, assume, settings

calculate_targets = _at_mod.calculate_targets
should_buy = _at_mod.should_buy
check_sell_condition = _at_mod.check_sell_condition
is_valid_transition = _at_mod.is_valid_transition
VALID_TRANSITIONS = _at_mod.VALID_TRANSITIONS

# ========== 自定义 Strategies ==========
positive_price = st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False)
pct_value = st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False)


# ========== Property 1: 目标价计算正确性 ==========

class TestProperty1TargetCalculation:
    """
    **Validates: Requirements AC-2.3**

    Property 1: 目标价计算正确性
    - buy_target < prev_close
    - sell_target > prev_close
    - stop_price < buy_target
    """

    @given(
        prev_close=positive_price,
        buy_dip_pct=pct_value,
        sell_rise_pct=pct_value,
        stop_loss_pct=pct_value,
    )
    @settings(max_examples=500)
    def test_target_relationships(self, prev_close, buy_dip_pct, sell_rise_pct, stop_loss_pct):
        """目标价之间的大小关系必须正确"""
        targets = calculate_targets(prev_close, buy_dip_pct, sell_rise_pct, stop_loss_pct)

        assert targets['buy_target'] < prev_close, \
            f"buy_target {targets['buy_target']} should be < prev_close {prev_close}"

        assert targets['sell_target'] > prev_close, \
            f"sell_target {targets['sell_target']} should be > prev_close {prev_close}"

        assert targets['stop_price'] < targets['buy_target'], \
            f"stop_price {targets['stop_price']} should be < buy_target {targets['buy_target']}"

    @given(
        prev_close=positive_price,
        buy_dip_pct=pct_value,
        sell_rise_pct=pct_value,
        stop_loss_pct=pct_value,
    )
    @settings(max_examples=300)
    def test_formula_correctness(self, prev_close, buy_dip_pct, sell_rise_pct, stop_loss_pct):
        """验证计算公式"""
        targets = calculate_targets(prev_close, buy_dip_pct, sell_rise_pct, stop_loss_pct)

        expected_buy = prev_close * (1 - buy_dip_pct / 100)
        expected_sell = prev_close * (1 + sell_rise_pct / 100)
        expected_stop = expected_buy * (1 - stop_loss_pct / 100)

        assert abs(targets['buy_target'] - expected_buy) < 0.001
        assert abs(targets['sell_target'] - expected_sell) < 0.001
        assert abs(targets['stop_price'] - expected_stop) < 0.001


# ========== Property 2: 买入触发条件 ==========

class TestProperty2BuyTrigger:
    """
    **Validates: Requirements AC-2.4**

    Property 2: 买入触发条件
    - price <= buy_target → should_buy = True
    - price > buy_target → should_buy = False
    """

    @given(
        buy_target=positive_price,
        price_offset=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=500)
    def test_buy_trigger(self, buy_target, price_offset):
        """买入触发条件正确"""
        price = buy_target + price_offset
        assume(price > 0)

        result = should_buy(price, buy_target)

        if price <= buy_target:
            assert result is True, f"price {price} <= buy_target {buy_target}, should_buy should be True"
        else:
            assert result is False, f"price {price} > buy_target {buy_target}, should_buy should be False"


# ========== Property 3: 卖出触发条件 ==========

class TestProperty3SellTrigger:
    """
    **Validates: Requirements AC-2.5, AC-2.6**

    Property 3: 卖出触发条件
    """

    @given(
        sell_target=positive_price,
        stop_price=st.floats(min_value=0.5, max_value=5000.0, allow_nan=False, allow_infinity=False),
        price=positive_price,
    )
    @settings(max_examples=500)
    def test_sell_conditions(self, sell_target, stop_price, price):
        """卖出条件正确"""
        assume(sell_target > stop_price)  # 正常情况下卖出目标 > 止损价

        result = check_sell_condition(price, sell_target, stop_price)

        if price <= stop_price:
            assert result == 'stop_loss', \
                f"price {price} <= stop_price {stop_price}, should be stop_loss, got {result}"
        elif price >= sell_target:
            assert result == 'profit', \
                f"price {price} >= sell_target {sell_target}, should be profit, got {result}"
        else:
            assert result is None, \
                f"price {price} between stop and target, should be None, got {result}"


# ========== Property 4: 止损优先于止盈 ==========

class TestProperty4StopLossPriority:
    """
    **Validates: Requirements AC-2.7**

    Property 4: 止损优先于止盈
    当价格同时满足止损和止盈条件时，止损优先
    """

    @given(
        base_price=st.floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300)
    def test_stop_loss_priority(self, base_price):
        """止损优先于止盈"""
        # 构造 stop_price > sell_target 的极端场景（理论上不应发生，但测试优先级）
        # 或者 price 同时 <= stop_price 且 >= sell_target
        stop_price = base_price
        sell_target = base_price * 0.99  # sell_target < stop_price
        price = base_price * 0.98  # price <= stop_price

        result = check_sell_condition(price, sell_target, stop_price)
        # 当 price <= stop_price，无论 sell_target 如何，都应该是 stop_loss
        assert result == 'stop_loss', \
            f"When price <= stop_price, should be stop_loss, got {result}"

    @given(
        stop_price=st.floats(min_value=5.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_exact_stop_price(self, stop_price):
        """价格恰好等于止损价时触发止损"""
        sell_target = stop_price + 10  # 卖出目标远高于止损
        result = check_sell_condition(stop_price, sell_target, stop_price)
        assert result == 'stop_loss'


# ========== Property 5: 状态机转换正确性 ==========

class TestProperty5StateMachine:
    """
    **Validates: Requirements AC-2.10**

    Property 5: 状态机转换正确性
    """

    @given(
        current=st.sampled_from(['waiting_buy', 'bought', 'completed', 'stop_loss', 'stopped']),
        target=st.sampled_from(['waiting_buy', 'bought', 'completed', 'stop_loss', 'stopped']),
    )
    @settings(max_examples=200)
    def test_valid_transitions(self, current, target):
        """状态转换验证"""
        result = is_valid_transition(current, target)
        expected = target in VALID_TRANSITIONS.get(current, set())
        assert result == expected, \
            f"Transition {current} -> {target}: expected {expected}, got {result}"

    def test_terminal_states_have_no_transitions(self):
        """终态不能再转换"""
        for terminal in ['completed', 'stop_loss', 'stopped']:
            for target in ['waiting_buy', 'bought', 'completed', 'stop_loss', 'stopped']:
                assert not is_valid_transition(terminal, target), \
                    f"Terminal state {terminal} should not transition to {target}"

    def test_waiting_buy_valid_transitions(self):
        """waiting_buy 只能转到 bought 或 stopped"""
        assert is_valid_transition('waiting_buy', 'bought')
        assert is_valid_transition('waiting_buy', 'stopped')
        assert not is_valid_transition('waiting_buy', 'completed')
        assert not is_valid_transition('waiting_buy', 'stop_loss')

    def test_bought_valid_transitions(self):
        """bought 可以转到 completed, stop_loss, stopped"""
        assert is_valid_transition('bought', 'completed')
        assert is_valid_transition('bought', 'stop_loss')
        assert is_valid_transition('bought', 'stopped')
        assert not is_valid_transition('bought', 'waiting_buy')
