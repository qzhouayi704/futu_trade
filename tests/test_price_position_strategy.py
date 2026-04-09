#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置统计策略 - Property-Based Tests

使用 hypothesis 进行属性测试，验证策略核心逻辑的正确性。
"""

import sys
import os
import importlib.util

# 直接加载策略模块，避免触发 simple_trade/__init__.py 的完整导入链
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

# 先加载 base_strategy（price_position_strategy 依赖它）
_base_spec = importlib.util.spec_from_file_location(
    "simple_trade.backtest.strategies.base_strategy",
    os.path.join(_project_root, "simple_trade", "backtest", "strategies", "base_strategy.py")
)
_base_mod = importlib.util.module_from_spec(_base_spec)
sys.modules["simple_trade.backtest.strategies.base_strategy"] = _base_mod
_base_spec.loader.exec_module(_base_mod)

# 加载 price_position_strategy
_pp_spec = importlib.util.spec_from_file_location(
    "simple_trade.backtest.strategies.price_position_strategy",
    os.path.join(_project_root, "simple_trade", "backtest", "strategies", "price_position_strategy.py")
)
_pp_mod = importlib.util.module_from_spec(_pp_spec)
sys.modules["simple_trade.backtest.strategies.price_position_strategy"] = _pp_mod
_pp_spec.loader.exec_module(_pp_mod)

# 加载 fee_calculator
_fee_spec = importlib.util.spec_from_file_location(
    "simple_trade.backtest.core.fee_calculator",
    os.path.join(_project_root, "simple_trade", "backtest", "core", "fee_calculator.py")
)
_fee_mod = importlib.util.module_from_spec(_fee_spec)
sys.modules["simple_trade.backtest.core.fee_calculator"] = _fee_mod
_fee_spec.loader.exec_module(_fee_mod)

import pytest
from hypothesis import given, strategies as st, assume, settings

PricePositionStrategy = _pp_mod.PricePositionStrategy
ZONE_DEFINITIONS = _pp_mod.ZONE_DEFINITIONS
ZONE_NAMES = _pp_mod.ZONE_NAMES
LOOKBACK_DAYS = _pp_mod.LOOKBACK_DAYS
FeeCalculator = _fee_mod.FeeCalculator

# 情绪相关常量
SENTIMENT_BEARISH = _pp_mod.SENTIMENT_BEARISH
SENTIMENT_NEUTRAL = _pp_mod.SENTIMENT_NEUTRAL
SENTIMENT_BULLISH = _pp_mod.SENTIMENT_BULLISH
SENTIMENT_LEVELS = _pp_mod.SENTIMENT_LEVELS
DEFAULT_SENTIMENT_THRESHOLDS = _pp_mod.DEFAULT_SENTIMENT_THRESHOLDS
DEFAULT_SENTIMENT_ADJUSTMENTS = _pp_mod.DEFAULT_SENTIMENT_ADJUSTMENTS

# 开盘类型相关常量
OPEN_TYPE_GAP_UP = _pp_mod.OPEN_TYPE_GAP_UP
OPEN_TYPE_FLAT = _pp_mod.OPEN_TYPE_FLAT
OPEN_TYPE_GAP_DOWN = _pp_mod.OPEN_TYPE_GAP_DOWN
OPEN_TYPES = _pp_mod.OPEN_TYPES
DEFAULT_GAP_THRESHOLD = _pp_mod.DEFAULT_GAP_THRESHOLD


# ========== 自定义 Strategies ==========

# 正的价格值
positive_price = st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False)

# 价格位置 [0, 100]
price_position = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)


def make_kline(time_key: str, open_p: float, high_p: float, low_p: float, close_p: float, volume: int = 1000):
    """创建一条K线数据"""
    return {
        'time_key': time_key,
        'open_price': open_p,
        'high_price': high_p,
        'low_price': low_p,
        'close_price': close_p,
        'volume': volume,
        'stock_code': 'HK.00700',
    }


# ========== Property 1: 涨跌幅计算正确性 ==========

class TestProperty1RiseDropCalculation:
    """
    **Validates: Requirements 1.2, 1.3**

    Property 1: 涨跌幅计算正确性
    - high_rise_pct = (high - prev_close) / prev_close * 100
    - low_drop_pct = (low - prev_close) / prev_close * 100
    - 必然有 high_rise_pct >= low_drop_pct（因为 high >= low）
    """

    @given(
        prev_close=positive_price,
        low_price=positive_price,
        high_delta=st.floats(min_value=0.0, max_value=5000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_high_rise_gte_low_drop(self, prev_close, low_price, high_delta):
        """high_rise_pct 必然 >= low_drop_pct"""
        high_price = low_price + high_delta  # 确保 high >= low
        close_price = (high_price + low_price) / 2

        strategy = PricePositionStrategy(lookback_days=2)
        klines = []
        for day in range(3):
            klines.append(make_kline(
                f'2025-01-{day+1:02d}',
                prev_close, prev_close, prev_close, prev_close
            ))
        klines.append(make_kline(
            '2025-01-04',
            prev_close, high_price, low_price, close_price
        ))

        metrics = strategy.calculate_daily_metrics(klines)

        if metrics:
            last = metrics[-1]
            assert last['high_rise_pct'] >= last['low_drop_pct'], \
                f"high_rise_pct ({last['high_rise_pct']}) < low_drop_pct ({last['low_drop_pct']})"

    @given(
        prev_close=positive_price,
        high_price=positive_price,
        low_price=positive_price,
    )
    @settings(max_examples=200)
    def test_formula_correctness(self, prev_close, high_price, low_price):
        """验证涨跌幅计算公式正确"""
        assume(high_price >= low_price)
        close_price = (high_price + low_price) / 2

        expected_high_rise = (high_price - prev_close) / prev_close * 100
        expected_low_drop = (low_price - prev_close) / prev_close * 100

        strategy = PricePositionStrategy(lookback_days=2)
        klines = []
        for day in range(3):
            klines.append(make_kline(
                f'2025-01-{day+1:02d}',
                prev_close, prev_close, prev_close, prev_close
            ))
        klines.append(make_kline(
            '2025-01-04',
            prev_close, high_price, low_price, close_price
        ))

        metrics = strategy.calculate_daily_metrics(klines)
        if metrics:
            last = metrics[-1]
            assert abs(last['high_rise_pct'] - round(expected_high_rise, 4)) < 0.01
            assert abs(last['low_drop_pct'] - round(expected_low_drop, 4)) < 0.01


# ========== Property 2: 价格位置范围有效性 ==========

class TestProperty2PricePositionRange:
    """
    **Validates: Requirements 1.4**

    Property 2: 价格位置范围有效性
    """

    @given(
        base_price=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        price_variations=st.lists(
            st.floats(min_value=-0.1, max_value=0.1, allow_nan=False, allow_infinity=False),
            min_size=14, max_size=14,
        ),
    )
    @settings(max_examples=200)
    def test_position_in_valid_range(self, base_price, price_variations):
        """price_position 必然在 [0, 100] 范围内"""
        strategy = PricePositionStrategy(lookback_days=12)

        klines = []
        for i, var in enumerate(price_variations):
            p = base_price * (1 + var)
            p = max(0.01, p)
            high = p * 1.02
            low = p * 0.98
            klines.append(make_kline(
                f'2025-01-{i+1:02d}', p, high, low, p
            ))

        metrics = strategy.calculate_daily_metrics(klines)

        for m in metrics:
            assert 0 <= m['price_position'] <= 100, \
                f"price_position {m['price_position']} out of [0, 100]"

    def test_equal_prices_give_50(self):
        """当所有价格相同时，price_position = 50"""
        strategy = PricePositionStrategy(lookback_days=3)
        price = 100.0

        klines = []
        for i in range(5):
            klines.append(make_kline(
                f'2025-01-{i+1:02d}', price, price, price, price
            ))

        metrics = strategy.calculate_daily_metrics(klines)

        for m in metrics:
            assert m['price_position'] == 50.0, \
                f"Expected 50.0 for equal prices, got {m['price_position']}"


# ========== Property 3: 区间分类完备性 ==========

class TestProperty3ZoneClassification:
    """
    **Validates: Requirements 1.5**

    Property 3: 区间分类完备性
    """

    @given(position=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=500)
    def test_any_position_maps_to_valid_zone(self, position):
        """任意 position 都能映射到有效区间"""
        zone = PricePositionStrategy.classify_zone(position)
        assert zone in ZONE_NAMES, f"position {position} mapped to invalid zone: {zone}"

    @given(position=st.floats(min_value=-50.0, max_value=150.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_out_of_range_clamped(self, position):
        """超出范围的 position 也能映射到有效区间（钳位后）"""
        zone = PricePositionStrategy.classify_zone(position)
        assert zone in ZONE_NAMES, f"position {position} mapped to invalid zone: {zone}"

    def test_boundary_values(self):
        """边界值测试"""
        assert PricePositionStrategy.classify_zone(0.0) == '低位(0-20%)'
        assert PricePositionStrategy.classify_zone(20.0) == '偏低(20-40%)'
        assert PricePositionStrategy.classify_zone(40.0) == '中位(40-60%)'
        assert PricePositionStrategy.classify_zone(60.0) == '偏高(60-80%)'
        assert PricePositionStrategy.classify_zone(80.0) == '高位(80-100%)'
        assert PricePositionStrategy.classify_zone(100.0) == '高位(80-100%)'


# ========== Property 4: 频率分布一致性 ==========

class TestProperty4FrequencyDistribution:
    """
    **Validates: Requirements 2.3**

    Property 4: 频率分布一致性
    """

    @given(
        zone_assignments=st.lists(
            st.sampled_from(ZONE_NAMES),
            min_size=5, max_size=100,
        )
    )
    @settings(max_examples=200)
    def test_frequencies_sum_to_100(self, zone_assignments):
        """所有区间频率之和 ≈ 100%"""
        strategy = PricePositionStrategy()

        metrics = []
        for i, zone in enumerate(zone_assignments):
            metrics.append({
                'date': f'2025-01-{(i % 28) + 1:02d}',
                'stock_code': 'HK.00700',
                'prev_close': 100.0,
                'open_price': 100.0,
                'high_price': 102.0,
                'low_price': 98.0,
                'close_price': 101.0,
                'high_rise_pct': 2.0,
                'low_drop_pct': -2.0,
                'price_position': 50.0,
                'zone': zone,
            })

        zone_stats = strategy.compute_zone_statistics(metrics)

        total_freq = sum(s['frequency_pct'] for s in zone_stats.values())
        assert abs(total_freq - 100.0) < 0.5, \
            f"Frequencies sum to {total_freq}, expected ~100%"

        for zone_name, stats in zone_stats.items():
            assert stats['frequency_pct'] >= 0, \
                f"Zone {zone_name} has negative frequency: {stats['frequency_pct']}"


# ========== Property 5: 交易模拟盈亏计算正确性（更新版） ==========

class TestProperty5TradeSimulation:
    """
    **Validates: Requirements 3.5, 3.6**

    Property 5: 交易模拟盈亏计算正确性（修正版：sell_target基于prev_close）
    """

    @given(
        prev_close=st.floats(min_value=10.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
        sell_rise_pct=st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
        stop_loss_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        low_factor=st.floats(min_value=0.90, max_value=1.0, allow_nan=False, allow_infinity=False),
        high_factor=st.floats(min_value=1.0, max_value=1.10, allow_nan=False, allow_infinity=False),
        close_factor=st.floats(min_value=0.95, max_value=1.05, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300)
    def test_profit_calculation_and_exit_type(
        self, prev_close, buy_dip_pct, sell_rise_pct, stop_loss_pct,
        low_factor, high_factor, close_factor
    ):
        """验证盈亏计算和退出类型"""
        strategy = PricePositionStrategy()

        low_price = prev_close * low_factor
        high_price = prev_close * high_factor
        close_price = prev_close * close_factor
        high_price = max(high_price, close_price, low_price)
        low_price = min(low_price, close_price, high_price)

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': prev_close,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': sell_rise_pct,
            'stop_loss_pct': stop_loss_pct,
        }}

        trades = strategy.simulate_trades(metrics, trade_params)

        buy_target = prev_close * (1 - buy_dip_pct / 100)
        # ★ 修正：卖出目标基于前收盘价（买在prev_close下方，卖在prev_close上方）
        sell_target = prev_close * (1 + sell_rise_pct / 100)
        stop_price = buy_target * (1 - stop_loss_pct / 100)

        if low_price > buy_target:
            assert len(trades) == 0, "Should not trigger buy when low > buy_target"
        else:
            assert len(trades) == 1, f"Expected 1 trade, got {len(trades)}"
            trade = trades[0]

            # 验证买入价
            assert abs(trade['buy_price'] - round(buy_target, 3)) < 0.01

            # 验证退出类型（止损优先）
            if low_price <= stop_price:
                assert trade['exit_type'] == 'stop_loss'
                expected_sell = stop_price
            elif high_price >= sell_target:
                assert trade['exit_type'] == 'profit'
                expected_sell = sell_target
            else:
                assert trade['exit_type'] == 'close'
                expected_sell = close_price

            # 验证盈亏计算
            expected_profit = (expected_sell - buy_target) / buy_target * 100
            assert abs(trade['profit_pct'] - round(expected_profit, 4)) < 0.15, \
                f"Profit mismatch: {trade['profit_pct']} vs {expected_profit}"


# ========== Property 6: 卖出目标价基于买入价 ==========

class TestProperty6SellTargetBasedOnPrevClose:
    """
    **Validates: Requirements AC-1.1**

    Property 6: 卖出目标价基于前收盘价
    - sell_target = prev_close * (1 + sell_rise_pct / 100)
    - 买入价 = prev_close * (1 - buy_dip_pct / 100)
    - 利润空间 ≈ buy_dip_pct + sell_rise_pct
    - 当 exit_type == 'profit' 时，sell_price == sell_target
    """

    @given(
        prev_close=st.floats(min_value=10.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        sell_rise_pct=st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300)
    def test_sell_target_based_on_prev_close(self, prev_close, buy_dip_pct, sell_rise_pct):
        """卖出目标价必须基于前收盘价计算"""
        strategy = PricePositionStrategy()

        buy_price = prev_close * (1 - buy_dip_pct / 100)
        expected_sell_target = prev_close * (1 + sell_rise_pct / 100)

        # 构造一个必然触发买入且必然止盈的场景
        low_price = buy_price * 0.99  # 低于买入价，触发买入
        high_price = expected_sell_target * 1.01  # 高于卖出目标，触发止盈
        close_price = prev_close

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': prev_close,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': sell_rise_pct,
            'stop_loss_pct': 50.0,  # 极大止损，确保不触发
        }}

        trades = strategy.simulate_trades(metrics, trade_params)

        assert len(trades) == 1, f"Expected 1 trade, got {len(trades)}"
        trade = trades[0]

        assert trade['exit_type'] == 'profit', \
            f"Expected 'profit' exit, got '{trade['exit_type']}'"

        # 验证 sell_target 基于 prev_close
        assert abs(trade['sell_target'] - round(expected_sell_target, 3)) < 0.01, \
            f"sell_target {trade['sell_target']} != expected {expected_sell_target:.3f}"

        # 验证 sell_price == sell_target
        assert abs(trade['sell_price'] - trade['sell_target']) < 0.01, \
            f"sell_price {trade['sell_price']} != sell_target {trade['sell_target']}"

        # 验证利润空间 ≈ buy_dip_pct + sell_rise_pct
        actual_profit_pct = (expected_sell_target - buy_price) / buy_price * 100
        # 利润空间应该大于 buy_dip + sell_rise 的近似值（因为基数不同会有微小差异）
        assert actual_profit_pct > 0, \
            f"Profit should be positive when buy_dip={buy_dip_pct}, sell_rise={sell_rise_pct}"


# ========== Property 7: 止损逻辑正确性 ==========

class TestProperty7StopLossLogic:
    """
    **Validates: Requirements AC-2.1, AC-2.2, AC-2.4**

    Property 7: 止损逻辑正确性
    """

    @given(
        prev_close=st.floats(min_value=50.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        stop_loss_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300)
    def test_stop_loss_triggers_correctly(self, prev_close, buy_dip_pct, stop_loss_pct):
        """当 low_price <= stop_price 时必须触发止损"""
        strategy = PricePositionStrategy()

        buy_price = prev_close * (1 - buy_dip_pct / 100)
        stop_price = buy_price * (1 - stop_loss_pct / 100)

        # 构造触发买入且触发止损的场景
        low_price = stop_price * 0.99  # 低于止损价
        high_price = prev_close * 1.01  # 不太高
        close_price = prev_close * 0.98

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': prev_close,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': 2.0,
            'stop_loss_pct': stop_loss_pct,
        }}

        trades = strategy.simulate_trades(metrics, trade_params)

        assert len(trades) == 1, f"Expected 1 trade, got {len(trades)}"
        trade = trades[0]

        # 止损必须触发
        assert trade['exit_type'] == 'stop_loss', \
            f"Expected 'stop_loss' exit, got '{trade['exit_type']}'"

        # 卖出价 == 止损价
        assert abs(trade['sell_price'] - round(stop_price, 3)) < 0.01, \
            f"sell_price {trade['sell_price']} != stop_price {stop_price:.3f}"

    @given(
        prev_close=st.floats(min_value=50.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=1.0, max_value=3.0, allow_nan=False, allow_infinity=False),
        stop_loss_pct=st.floats(min_value=1.0, max_value=3.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_stop_loss_priority_over_profit(self, prev_close, buy_dip_pct, stop_loss_pct):
        """同时触及止损和止盈时，止损优先"""
        strategy = PricePositionStrategy()

        buy_price = prev_close * (1 - buy_dip_pct / 100)
        stop_price = buy_price * (1 - stop_loss_pct / 100)
        sell_target = prev_close * (1 + 1.0 / 100)  # 基于prev_close的1%止盈

        # 构造同时触及止损和止盈的场景
        low_price = min(stop_price * 0.99, buy_price * 0.99)
        high_price = max(sell_target * 1.01, prev_close * 1.01)
        close_price = prev_close

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': prev_close,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': 1.0,
            'stop_loss_pct': stop_loss_pct,
        }}

        trades = strategy.simulate_trades(metrics, trade_params)

        assert len(trades) == 1
        # 止损优先
        assert trades[0]['exit_type'] == 'stop_loss', \
            f"Expected 'stop_loss' when both triggered, got '{trades[0]['exit_type']}'"


# ========== Property 8: 净盈亏计算正确性 ==========

class TestProperty8NetProfitCalculation:
    """
    **Validates: Requirements AC-3.3**

    Property 8: 净盈亏计算正确性
    - net_profit_pct < profit_pct（费用总是正的）
    - buy_fee > 0 且 sell_fee > 0
    """

    @given(
        prev_close=st.floats(min_value=10.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        sell_rise_pct=st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_net_profit_less_than_gross(self, prev_close, buy_dip_pct, sell_rise_pct):
        """净盈亏必然小于毛盈亏（因为费用 > 0）"""
        strategy = PricePositionStrategy()
        fee_calculator = FeeCalculator()

        buy_price = prev_close * (1 - buy_dip_pct / 100)
        sell_target = prev_close * (1 + sell_rise_pct / 100)

        # 构造触发买入且止盈的场景
        low_price = buy_price * 0.99
        high_price = sell_target * 1.01
        close_price = prev_close

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': prev_close,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': sell_rise_pct,
            'stop_loss_pct': 50.0,  # 极大止损，不触发
        }}

        trades = strategy.simulate_trades(
            metrics, trade_params,
            trade_amount=60000.0,
            fee_calculator=fee_calculator,
        )

        assert len(trades) == 1
        trade = trades[0]

        # 净盈亏 < 毛盈亏
        assert trade['net_profit_pct'] < trade['profit_pct'], \
            f"net_profit_pct ({trade['net_profit_pct']}) should be < profit_pct ({trade['profit_pct']})"

        # 费用 > 0
        assert trade['buy_fee'] > 0, f"buy_fee should be > 0, got {trade['buy_fee']}"
        assert trade['sell_fee'] > 0, f"sell_fee should be > 0, got {trade['sell_fee']}"

    def test_no_fee_when_no_calculator(self):
        """不传 fee_calculator 时费用为 0"""
        strategy = PricePositionStrategy()

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': 100.0,
            'open_price': 100.0,
            'high_price': 105.0,
            'low_price': 95.0,
            'close_price': 100.0,
            'high_rise_pct': 5.0,
            'low_drop_pct': -5.0,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': 2.0,
            'sell_rise_pct': 2.0,
            'stop_loss_pct': 3.0,
        }}

        trades = strategy.simulate_trades(metrics, trade_params)

        assert len(trades) == 1
        trade = trades[0]
        assert trade['buy_fee'] == 0.0
        assert trade['sell_fee'] == 0.0
        assert trade['net_profit_pct'] == trade['profit_pct']


# ========== Property 9: 止损限制最大亏损 ==========

class TestProperty9StopLossLimitsLoss:
    """
    **Validates: Requirements AC-2.1**

    Property 9: 止损限制最大亏损
    - 当 exit_type == 'stop_loss' 时，profit_pct ≈ -stop_loss_pct
    - 对于所有交易，profit_pct >= -stop_loss_pct（允许浮点误差）
    """

    @given(
        prev_close=st.floats(min_value=50.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        stop_loss_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        low_factor=st.floats(min_value=0.85, max_value=1.0, allow_nan=False, allow_infinity=False),
        high_factor=st.floats(min_value=1.0, max_value=1.10, allow_nan=False, allow_infinity=False),
        close_factor=st.floats(min_value=0.90, max_value=1.05, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300)
    def test_loss_bounded_by_stop_loss(self, prev_close, buy_dip_pct, stop_loss_pct,
                                        low_factor, high_factor, close_factor):
        """亏损不超过止损比例"""
        strategy = PricePositionStrategy()

        low_price = prev_close * low_factor
        high_price = prev_close * high_factor
        close_price = prev_close * close_factor
        high_price = max(high_price, close_price, low_price)
        low_price = min(low_price, close_price, high_price)

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': prev_close,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': 2.0,
            'stop_loss_pct': stop_loss_pct,
        }}

        trades = strategy.simulate_trades(metrics, trade_params)

        for trade in trades:
            # 毛盈亏不应低于 -stop_loss_pct（允许浮点误差 0.1%）
            assert trade['profit_pct'] >= -(stop_loss_pct + 0.1), \
                f"profit_pct {trade['profit_pct']} < -stop_loss_pct {-stop_loss_pct}"

            if trade['exit_type'] == 'stop_loss':
                # 止损时盈亏应约等于 -stop_loss_pct
                assert abs(trade['profit_pct'] - (-stop_loss_pct)) < 0.15, \
                    f"Stop loss profit {trade['profit_pct']} != expected {-stop_loss_pct}"


# ========== Property 10: 情绪分类完备性 ==========

class TestProperty10SentimentClassification:
    """
    **Validates: Requirements AC-1.3**

    Property 1 (Sentiment): 情绪分类完备性
    - classify_sentiment 对任意输入返回有效等级
    - 分类结果与阈值一致
    """

    @given(
        sentiment_pct=st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        bearish_th=st.floats(min_value=-5.0, max_value=-0.1, allow_nan=False, allow_infinity=False),
        bullish_th=st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=500)
    def test_always_returns_valid_level(self, sentiment_pct, bearish_th, bullish_th):
        """任意涨跌幅和有效阈值都返回三个等级之一"""
        assume(bearish_th < bullish_th)
        thresholds = {'bearish_threshold': bearish_th, 'bullish_threshold': bullish_th}
        result = PricePositionStrategy.classify_sentiment(sentiment_pct, thresholds)
        assert result in SENTIMENT_LEVELS, f"Got invalid level: {result}"

    @given(
        sentiment_pct=st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        bearish_th=st.floats(min_value=-5.0, max_value=-0.1, allow_nan=False, allow_infinity=False),
        bullish_th=st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=500)
    def test_classification_consistent_with_thresholds(self, sentiment_pct, bearish_th, bullish_th):
        """分类结果与阈值一致"""
        assume(bearish_th < bullish_th)
        thresholds = {'bearish_threshold': bearish_th, 'bullish_threshold': bullish_th}
        result = PricePositionStrategy.classify_sentiment(sentiment_pct, thresholds)

        if sentiment_pct < bearish_th:
            assert result == SENTIMENT_BEARISH, \
                f"pct={sentiment_pct} < bearish_th={bearish_th} but got {result}"
        elif sentiment_pct > bullish_th:
            assert result == SENTIMENT_BULLISH, \
                f"pct={sentiment_pct} > bullish_th={bullish_th} but got {result}"
        else:
            assert result == SENTIMENT_NEUTRAL, \
                f"pct={sentiment_pct} in [{bearish_th}, {bullish_th}] but got {result}"

    def test_default_thresholds(self):
        """默认阈值 ±1% 的边界测试"""
        assert PricePositionStrategy.classify_sentiment(-1.5) == SENTIMENT_BEARISH
        assert PricePositionStrategy.classify_sentiment(-1.0) == SENTIMENT_NEUTRAL  # -1.0 不 < -1.0
        assert PricePositionStrategy.classify_sentiment(0.0) == SENTIMENT_NEUTRAL
        assert PricePositionStrategy.classify_sentiment(1.0) == SENTIMENT_NEUTRAL   # 1.0 不 > 1.0
        assert PricePositionStrategy.classify_sentiment(1.5) == SENTIMENT_BULLISH


# ========== Property 11: 情绪调整方向正确性 ==========

class TestProperty11SentimentAdjustmentDirection:
    """
    **Validates: Requirements AC-2.2, AC-2.3, AC-2.4**

    Property 2 (Sentiment): 情绪调整方向正确性
    - bearish: buy_dip 放大, sell_rise 缩小
    - bullish: buy_dip 缩小, sell_rise 放大
    - neutral: 不变
    """

    @given(
        buy_dip=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
        sell_rise=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
        stop_loss=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300)
    def test_bearish_increases_buy_dip_decreases_sell_rise(self, buy_dip, sell_rise, stop_loss):
        """弱势时买入门槛提高、卖出更快（受 min_adjusted_sell_rise 钳制保护）"""
        params = {'buy_dip_pct': buy_dip, 'sell_rise_pct': sell_rise, 'stop_loss_pct': stop_loss}
        adjusted = PricePositionStrategy.apply_sentiment_adjustment(params, SENTIMENT_BEARISH)

        assert adjusted['buy_dip_pct'] >= buy_dip - 0.001, \
            f"Bearish buy_dip {adjusted['buy_dip_pct']} < original {buy_dip}"
        # sell_rise 调整后可能被钳制到 min_adjusted_sell_rise（默认 0.8）
        # 当原始值 < 0.8 时，钳制后可能反而更大；当原始值 >= 0.8 时，应 <= 原值
        min_sell_rise = 0.8  # 默认钳制下限
        if sell_rise >= min_sell_rise:
            assert adjusted['sell_rise_pct'] <= sell_rise + 0.001, \
                f"Bearish sell_rise {adjusted['sell_rise_pct']} > original {sell_rise}"
        else:
            # 钳制场景：调整后至少为 min_sell_rise
            assert adjusted['sell_rise_pct'] >= min_sell_rise - 0.001, \
                f"Bearish sell_rise {adjusted['sell_rise_pct']} < min {min_sell_rise}"
        assert adjusted['stop_loss_pct'] == stop_loss, \
            "Stop loss should not change"

    @given(
        buy_dip=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
        sell_rise=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
        stop_loss=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300)
    def test_bullish_decreases_buy_dip_increases_sell_rise(self, buy_dip, sell_rise, stop_loss):
        """强势时买入门槛降低、卖出更慢（受 min_adjusted_sell_rise 钳制保护）"""
        params = {'buy_dip_pct': buy_dip, 'sell_rise_pct': sell_rise, 'stop_loss_pct': stop_loss}
        adjusted = PricePositionStrategy.apply_sentiment_adjustment(params, SENTIMENT_BULLISH)

        assert adjusted['buy_dip_pct'] <= buy_dip + 0.001, \
            f"Bullish buy_dip {adjusted['buy_dip_pct']} > original {buy_dip}"
        # sell_rise 受 min_adjusted_sell_rise 钳制保护（默认 0.8）
        min_sell_rise = 0.8
        if sell_rise >= min_sell_rise:
            assert adjusted['sell_rise_pct'] >= sell_rise - 0.001, \
                f"Bullish sell_rise {adjusted['sell_rise_pct']} < original {sell_rise}"
        else:
            # 原值低于钳制下限时，调整后至少为 min_sell_rise
            assert adjusted['sell_rise_pct'] >= min_sell_rise - 0.001, \
                f"Bullish sell_rise {adjusted['sell_rise_pct']} < min {min_sell_rise}"
        assert adjusted['stop_loss_pct'] == stop_loss, \
            "Stop loss should not change"

    @given(
        buy_dip=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
        sell_rise=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
        stop_loss=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300)
    def test_neutral_no_change(self, buy_dip, sell_rise, stop_loss):
        """中性时参数不变（受 min_adjusted_sell_rise 钳制保护）"""
        params = {'buy_dip_pct': buy_dip, 'sell_rise_pct': sell_rise, 'stop_loss_pct': stop_loss}
        adjusted = PricePositionStrategy.apply_sentiment_adjustment(params, SENTIMENT_NEUTRAL)

        assert abs(adjusted['buy_dip_pct'] - buy_dip) < 0.001, \
            f"Neutral buy_dip changed: {adjusted['buy_dip_pct']} vs {buy_dip}"
        # sell_rise 受 min_adjusted_sell_rise 钳制保护（默认 0.8）
        min_sell_rise = 0.8
        if sell_rise >= min_sell_rise:
            assert abs(adjusted['sell_rise_pct'] - sell_rise) < 0.001, \
                f"Neutral sell_rise changed: {adjusted['sell_rise_pct']} vs {sell_rise}"
        else:
            assert abs(adjusted['sell_rise_pct'] - min_sell_rise) < 0.001, \
                f"Neutral sell_rise should be clamped to {min_sell_rise}, got {adjusted['sell_rise_pct']}"
        assert adjusted['stop_loss_pct'] == stop_loss


# ========== Property 12: 情绪映射表完整性 ==========

class TestProperty12SentimentMapCompleteness:
    """
    **Validates: Requirements AC-1.2, AC-1.3**

    Property 4 (Sentiment): 情绪映射表完整性
    - 条目数 = K线数据条数 - 1
    - 每个条目包含 sentiment_pct 和 sentiment_level
    - sentiment_level 是三个等级之一
    """

    @given(
        n_days=st.integers(min_value=2, max_value=30),
        base_price=st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        daily_returns=st.lists(
            st.floats(min_value=-0.05, max_value=0.05, allow_nan=False, allow_infinity=False),
            min_size=1, max_size=29,
        ),
    )
    @settings(max_examples=200)
    def test_map_entry_count_and_fields(self, n_days, base_price, daily_returns):
        """映射表条目数 = n_days - 1，且每条包含必要字段"""
        # 生成 ETF K线数据
        kline_data = []
        price = base_price
        for i in range(min(n_days, len(daily_returns) + 1)):
            kline_data.append({
                'time_key': f'2025-01-{i+1:02d}',
                'open_price': price,
                'high_price': price * 1.01,
                'low_price': price * 0.99,
                'close_price': price,
                'volume': 1000,
            })
            if i < len(daily_returns):
                price = price * (1 + daily_returns[i])
                price = max(0.01, price)

        sentiment_map = PricePositionStrategy.build_sentiment_map(kline_data)

        # 条目数 = len(kline_data) - 1
        assert len(sentiment_map) == len(kline_data) - 1, \
            f"Expected {len(kline_data) - 1} entries, got {len(sentiment_map)}"

        # 每条包含必要字段
        for date_str, info in sentiment_map.items():
            assert 'sentiment_pct' in info, f"Missing sentiment_pct for {date_str}"
            assert 'sentiment_level' in info, f"Missing sentiment_level for {date_str}"
            assert isinstance(info['sentiment_pct'], float), \
                f"sentiment_pct should be float, got {type(info['sentiment_pct'])}"
            assert info['sentiment_level'] in SENTIMENT_LEVELS, \
                f"Invalid sentiment_level: {info['sentiment_level']}"


# ========== Property 13: 情绪开关一致性 ==========

class TestProperty13SentimentToggleConsistency:
    """
    **Validates: Requirements AC-3.3**

    Property 3 (Sentiment): 情绪开关一致性
    - use_sentiment=False 时，买卖价格与不传情绪参数时一致
    """

    @given(
        prev_close=st.floats(min_value=10.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        sell_rise_pct=st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_disabled_sentiment_matches_original(self, prev_close, buy_dip_pct, sell_rise_pct):
        """禁用情绪时，买卖价格与原策略一致"""
        strategy = PricePositionStrategy()

        buy_price = prev_close * (1 - buy_dip_pct / 100)
        sell_target = prev_close * (1 + sell_rise_pct / 100)
        low_price = buy_price * 0.99
        high_price = sell_target * 1.01
        close_price = prev_close

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': prev_close,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
            'sentiment_level': SENTIMENT_BEARISH,  # 即使有情绪数据
            'sentiment_pct': -2.5,
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': sell_rise_pct,
            'stop_loss_pct': 50.0,
        }}

        # 不启用情绪
        trades_off = strategy.simulate_trades(
            metrics, trade_params, use_sentiment=False,
            sentiment_adjustments=DEFAULT_SENTIMENT_ADJUSTMENTS,
        )
        # 默认调用（也不启用）
        trades_default = strategy.simulate_trades(metrics, trade_params)

        assert len(trades_off) == len(trades_default)
        if trades_off:
            assert abs(trades_off[0]['buy_price'] - trades_default[0]['buy_price']) < 0.01
            assert abs(trades_off[0]['sell_target'] - trades_default[0]['sell_target']) < 0.01


# ========== Property 14: 交易记录情绪字段完整性 ==========

class TestProperty14TradeRecordSentimentFields:
    """
    **Validates: Requirements AC-5.3**

    Property 5 (Sentiment): 交易记录情绪字段完整性
    - use_sentiment=True 时每条记录包含情绪字段
    """

    @given(
        prev_close=st.floats(min_value=10.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        sell_rise_pct=st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
        sentiment_level=st.sampled_from(SENTIMENT_LEVELS),
        sentiment_pct=st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_sentiment_fields_present_when_enabled(
        self, prev_close, buy_dip_pct, sell_rise_pct, sentiment_level, sentiment_pct
    ):
        """启用情绪时，每条交易记录包含情绪字段"""
        strategy = PricePositionStrategy()

        buy_price = prev_close * (1 - buy_dip_pct / 100)
        low_price = buy_price * 0.99
        high_price = prev_close * 1.10
        close_price = prev_close

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': prev_close,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
            'sentiment_level': sentiment_level,
            'sentiment_pct': sentiment_pct,
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': sell_rise_pct,
            'stop_loss_pct': 50.0,
        }}

        trades = strategy.simulate_trades(
            metrics, trade_params,
            use_sentiment=True,
            sentiment_adjustments=DEFAULT_SENTIMENT_ADJUSTMENTS,
        )

        for trade in trades:
            assert 'sentiment_level' in trade, "Missing sentiment_level"
            assert trade['sentiment_level'] in SENTIMENT_LEVELS, \
                f"Invalid sentiment_level: {trade['sentiment_level']}"
            assert 'sentiment_pct' in trade, "Missing sentiment_pct"
            assert isinstance(trade['sentiment_pct'], float), \
                f"sentiment_pct should be float, got {type(trade['sentiment_pct'])}"
            assert 'effective_buy_dip_pct' in trade, "Missing effective_buy_dip_pct"
            assert trade['effective_buy_dip_pct'] > 0, \
                f"effective_buy_dip_pct should be > 0, got {trade['effective_buy_dip_pct']}"
            assert 'effective_sell_rise_pct' in trade, "Missing effective_sell_rise_pct"
            assert trade['effective_sell_rise_pct'] > 0, \
                f"effective_sell_rise_pct should be > 0, got {trade['effective_sell_rise_pct']}"


# 双锚点相关常量
DEFAULT_OPEN_ANCHOR_PARAMS = _pp_mod.DEFAULT_OPEN_ANCHOR_PARAMS


# ========== Property 15: 双锚点互斥性 ==========

class TestProperty15DualAnchorMutualExclusivity:
    """
    **Validates: Requirements AC-6.1**

    Property 6 (Dual-Anchor): 双锚点互斥性
    - 如果主锚点（prev_close）触发了买入，则不会使用开盘价锚点
    - 开盘价锚点只在主锚点未触发且情绪为 bullish 时才可能触发
    - 同一天同一只股票不会同时产生两种锚点的交易
    """

    @given(
        prev_close=st.floats(min_value=10.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        sell_rise_pct=st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
        low_factor=st.floats(min_value=0.90, max_value=1.0, allow_nan=False, allow_infinity=False),
        high_factor=st.floats(min_value=1.0, max_value=1.10, allow_nan=False, allow_infinity=False),
        close_factor=st.floats(min_value=0.95, max_value=1.05, allow_nan=False, allow_infinity=False),
        open_factor=st.floats(min_value=0.98, max_value=1.05, allow_nan=False, allow_infinity=False),
        sentiment_level=st.sampled_from(SENTIMENT_LEVELS),
    )
    @settings(max_examples=500)
    def test_main_anchor_triggered_excludes_open_anchor(
        self, prev_close, buy_dip_pct, sell_rise_pct,
        low_factor, high_factor, close_factor, open_factor, sentiment_level
    ):
        """主锚点触发时，anchor_type 必为 prev_close；开盘价锚点只在 bullish 时出现"""
        strategy = PricePositionStrategy()

        open_price = prev_close * open_factor
        low_price = prev_close * low_factor
        high_price = prev_close * high_factor
        close_price = prev_close * close_factor
        high_price = max(high_price, close_price, low_price, open_price)
        low_price = min(low_price, close_price, high_price)

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': open_price,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
            'sentiment_level': sentiment_level,
            'sentiment_pct': 2.0 if sentiment_level == SENTIMENT_BULLISH else 0.0,
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': sell_rise_pct,
            'stop_loss_pct': 3.0,
        }}

        trades = strategy.simulate_trades(
            metrics, trade_params,
            use_sentiment=True,
            sentiment_adjustments=DEFAULT_SENTIMENT_ADJUSTMENTS,
            enable_open_anchor=True,
            open_anchor_params=DEFAULT_OPEN_ANCHOR_PARAMS,
        )

        # 每天最多一笔交易
        assert len(trades) <= 1, f"Expected at most 1 trade per day, got {len(trades)}"

        if trades:
            trade = trades[0]
            main_buy_price = prev_close * (1 - trade['effective_buy_dip_pct'] / 100)

            if trade['anchor_type'] == 'prev_close':
                # 主锚点触发 → low_price 必须 <= 主锚点买入价
                assert low_price <= main_buy_price + 0.01, \
                    f"prev_close anchor but low {low_price} > buy_price {main_buy_price}"
            elif trade['anchor_type'] == 'open_price':
                # 开盘价锚点 → 情绪必须是 bullish
                assert sentiment_level == SENTIMENT_BULLISH, \
                    f"open_price anchor but sentiment is {sentiment_level}, expected bullish"

    @given(
        prev_close=st.floats(min_value=50.0, max_value=300.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=2.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300)
    def test_main_anchor_triggers_first(self, prev_close, buy_dip_pct):
        """当主锚点能触发时，即使是 bullish 天也用主锚点"""
        strategy = PricePositionStrategy()

        # 构造主锚点一定触发的场景：low_price 远低于 buy_price
        buy_price = prev_close * (1 - buy_dip_pct / 100)
        open_price = prev_close * 1.02  # 高开
        low_price = buy_price * 0.98  # 低于主锚点买入价
        high_price = prev_close * 1.08
        close_price = prev_close * 1.01

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': open_price,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
            'sentiment_level': SENTIMENT_BULLISH,
            'sentiment_pct': 2.5,
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': 2.0,
            'stop_loss_pct': 3.0,
        }}

        trades = strategy.simulate_trades(
            metrics, trade_params,
            use_sentiment=True,
            sentiment_adjustments=DEFAULT_SENTIMENT_ADJUSTMENTS,
            enable_open_anchor=True,
            open_anchor_params=DEFAULT_OPEN_ANCHOR_PARAMS,
        )

        assert len(trades) == 1, f"Expected 1 trade, got {len(trades)}"
        # 主锚点触发了，所以 anchor_type 必须是 prev_close
        assert trades[0]['anchor_type'] == 'prev_close', \
            f"Expected prev_close anchor when main anchor triggers, got {trades[0]['anchor_type']}"


# ========== Property 16: 锚点类型标记正确性 ==========

class TestProperty16AnchorTypeCorrectness:
    """
    **Validates: Requirements AC-6.5**

    Property 7 (Dual-Anchor): 锚点类型标记正确性
    - anchor_type 值为 'prev_close' 或 'open_price' 之一
    - anchor_type='open_price' 的交易，其 sentiment_level 必然为 'bullish'
    - anchor_price 与 anchor_type 一致
    """

    @given(
        prev_close=st.floats(min_value=10.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        sell_rise_pct=st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
        low_factor=st.floats(min_value=0.88, max_value=1.0, allow_nan=False, allow_infinity=False),
        high_factor=st.floats(min_value=1.0, max_value=1.12, allow_nan=False, allow_infinity=False),
        close_factor=st.floats(min_value=0.93, max_value=1.07, allow_nan=False, allow_infinity=False),
        open_factor=st.floats(min_value=0.98, max_value=1.06, allow_nan=False, allow_infinity=False),
        sentiment_level=st.sampled_from(SENTIMENT_LEVELS),
    )
    @settings(max_examples=500)
    def test_anchor_type_is_valid_and_consistent(
        self, prev_close, buy_dip_pct, sell_rise_pct,
        low_factor, high_factor, close_factor, open_factor, sentiment_level
    ):
        """anchor_type 值有效，且 open_price 锚点只在 bullish 时出现"""
        strategy = PricePositionStrategy()

        open_price = prev_close * open_factor
        low_price = prev_close * low_factor
        high_price = prev_close * high_factor
        close_price = prev_close * close_factor
        high_price = max(high_price, close_price, low_price, open_price)
        low_price = min(low_price, close_price, high_price)

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': open_price,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
            'sentiment_level': sentiment_level,
            'sentiment_pct': 2.0 if sentiment_level == SENTIMENT_BULLISH else (-2.0 if sentiment_level == SENTIMENT_BEARISH else 0.0),
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': sell_rise_pct,
            'stop_loss_pct': 3.0,
        }}

        trades = strategy.simulate_trades(
            metrics, trade_params,
            use_sentiment=True,
            sentiment_adjustments=DEFAULT_SENTIMENT_ADJUSTMENTS,
            enable_open_anchor=True,
            open_anchor_params=DEFAULT_OPEN_ANCHOR_PARAMS,
        )

        for trade in trades:
            # anchor_type 必须是两个值之一
            assert trade['anchor_type'] in ('prev_close', 'open_price'), \
                f"Invalid anchor_type: {trade['anchor_type']}"

            # anchor_price 必须是正数
            assert trade['anchor_price'] > 0, \
                f"anchor_price should be > 0, got {trade['anchor_price']}"

            if trade['anchor_type'] == 'prev_close':
                # anchor_price 应等于 prev_close
                assert abs(trade['anchor_price'] - prev_close) < 0.01, \
                    f"prev_close anchor but anchor_price {trade['anchor_price']} != prev_close {prev_close}"
            elif trade['anchor_type'] == 'open_price':
                # anchor_price 应等于 open_price
                assert abs(trade['anchor_price'] - round(open_price, 3)) < 0.01, \
                    f"open_price anchor but anchor_price {trade['anchor_price']} != open_price {open_price}"
                # 必须是 bullish 天
                assert trade['sentiment_level'] == SENTIMENT_BULLISH, \
                    f"open_price anchor requires bullish, got {trade['sentiment_level']}"

    @given(
        prev_close=st.floats(min_value=50.0, max_value=300.0, allow_nan=False, allow_infinity=False),
        open_buy_dip=st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False),
        open_sell_rise=st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300)
    def test_open_anchor_uses_open_price_as_base(self, prev_close, open_buy_dip, open_sell_rise):
        """开盘价锚点的买卖价格基于 open_price 计算"""
        strategy = PricePositionStrategy()

        # 构造：高开（主锚点不触发）+ bullish + 开盘价锚点触发
        open_price = prev_close * 1.03  # 高开3%
        oa_buy_price = open_price * (1 - open_buy_dip / 100)
        oa_sell_target = open_price * (1 + open_sell_rise / 100)

        # 确保主锚点不触发（low > prev_close based buy price）
        # 用默认 bullish 调整后的 buy_dip: 2.0 * 0.7 = 1.4%
        main_buy_price = prev_close * (1 - 2.0 * 0.7 / 100)

        low_price = max(main_buy_price + 0.5, oa_buy_price * 0.99)  # 高于主锚点买入价，低于开盘价锚点买入价
        # 如果 low_price 仍然 <= main_buy_price，跳过
        if low_price <= main_buy_price:
            return

        high_price = max(oa_sell_target * 1.01, open_price * 1.05)
        close_price = open_price * 1.01

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': open_price,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
            'sentiment_level': SENTIMENT_BULLISH,
            'sentiment_pct': 2.5,
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': 2.0,
            'sell_rise_pct': 2.0,
            'stop_loss_pct': 3.0,
        }}

        oa_params = {
            'open_buy_dip_pct': open_buy_dip,
            'open_sell_rise_pct': open_sell_rise,
            'stop_loss_pct': 3.0,
        }

        trades = strategy.simulate_trades(
            metrics, trade_params,
            use_sentiment=True,
            sentiment_adjustments=DEFAULT_SENTIMENT_ADJUSTMENTS,
            enable_open_anchor=True,
            open_anchor_params=oa_params,
        )

        if trades and trades[0]['anchor_type'] == 'open_price':
            trade = trades[0]
            expected_buy = open_price * (1 - open_buy_dip / 100)
            assert abs(trade['buy_price'] - round(expected_buy, 3)) < 0.02, \
                f"Open anchor buy_price {trade['buy_price']} != expected {expected_buy:.3f}"


# ========== Property 17: 开盘类型分类完备性 ==========

class TestProperty17OpenTypeClassification:
    """
    **Validates: Requirements AC-1.2**

    Property 8 (Open-Type): 开盘类型分类完备性
    - classify_open_type 对任意有效输入返回 gap_up/flat/gap_down 之一
    - 分类结果与阈值一致：gap_up 当且仅当 open_gap_pct > threshold
    """

    @given(
        open_price=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
        prev_close=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
        gap_threshold=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=500)
    def test_always_returns_valid_type(self, open_price, prev_close, gap_threshold):
        """任意正价格和正阈值都返回三个类型之一"""
        result = PricePositionStrategy.classify_open_type(open_price, prev_close, gap_threshold)
        assert result in OPEN_TYPES, f"Got invalid type: {result}"

    @given(
        open_price=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
        prev_close=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
        gap_threshold=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=500)
    def test_classification_consistent_with_threshold(self, open_price, prev_close, gap_threshold):
        """分类结果与阈值一致"""
        result = PricePositionStrategy.classify_open_type(open_price, prev_close, gap_threshold)
        open_gap_pct = (open_price - prev_close) / prev_close * 100

        if open_gap_pct > gap_threshold:
            assert result == OPEN_TYPE_GAP_UP, \
                f"gap_pct={open_gap_pct:.4f} > threshold={gap_threshold} but got {result}"
        elif open_gap_pct < -gap_threshold:
            assert result == OPEN_TYPE_GAP_DOWN, \
                f"gap_pct={open_gap_pct:.4f} < -{gap_threshold} but got {result}"
        else:
            assert result == OPEN_TYPE_FLAT, \
                f"gap_pct={open_gap_pct:.4f} in [-{gap_threshold}, {gap_threshold}] but got {result}"

    def test_default_threshold_boundaries(self):
        """默认阈值 ±0.5% 的边界测试"""
        prev_close = 100.0
        # 高开 > 0.5%
        assert PricePositionStrategy.classify_open_type(101.0, prev_close) == OPEN_TYPE_GAP_UP
        # 平开 = 0.5% (不 > 0.5)
        assert PricePositionStrategy.classify_open_type(100.5, prev_close) == OPEN_TYPE_FLAT
        # 平开 = 0
        assert PricePositionStrategy.classify_open_type(100.0, prev_close) == OPEN_TYPE_FLAT
        # 平开 = -0.5% (不 < -0.5)
        assert PricePositionStrategy.classify_open_type(99.5, prev_close) == OPEN_TYPE_FLAT
        # 低开 < -0.5%
        assert PricePositionStrategy.classify_open_type(99.0, prev_close) == OPEN_TYPE_GAP_DOWN

    def test_metrics_contain_open_type_fields(self):
        """calculate_daily_metrics 输出包含 open_type 和 open_gap_pct 字段"""
        strategy = PricePositionStrategy(lookback_days=2)
        klines = []
        for i in range(4):
            klines.append(make_kline(
                f'2025-01-{i+1:02d}', 100.0, 102.0, 98.0, 100.0
            ))
        # 第5天高开
        klines.append(make_kline('2025-01-05', 102.0, 104.0, 99.0, 101.0))

        metrics = strategy.calculate_daily_metrics(klines)
        for m in metrics:
            assert 'open_type' in m, "Missing open_type field"
            assert m['open_type'] in OPEN_TYPES, f"Invalid open_type: {m['open_type']}"
            assert 'open_gap_pct' in m, "Missing open_gap_pct field"
            assert isinstance(m['open_gap_pct'], float), \
                f"open_gap_pct should be float, got {type(m['open_gap_pct'])}"


# ========== Property 18: 开盘类型锚点选择正确性 ==========

class TestProperty18OpenTypeAnchorSelection:
    """
    **Validates: Requirements AC-2.1, AC-2.2, AC-2.3**

    Property 9 (Open-Type): 开盘类型锚点选择正确性
    当 enable_open_type_anchor=True 时：
    - gap_up 交易的 anchor_type 必然为 'open_price'
    - flat 交易的 anchor_type 必然为 'prev_close'
    - gap_down 交易的 anchor_type 必然为 'prev_close'
    """

    @given(
        prev_close=st.floats(min_value=50.0, max_value=300.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        sell_rise_pct=st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
        gap_up_buy_dip=st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False),
        gap_up_sell_rise=st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False),
        open_factor=st.floats(min_value=0.93, max_value=1.07, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=500)
    def test_anchor_type_matches_open_type(
        self, prev_close, buy_dip_pct, sell_rise_pct,
        gap_up_buy_dip, gap_up_sell_rise, open_factor
    ):
        """anchor_type 与 open_type 一致"""
        strategy = PricePositionStrategy()

        open_price = prev_close * open_factor
        # 确定 open_type
        open_gap_pct = (open_price - prev_close) / prev_close * 100
        if open_gap_pct > DEFAULT_GAP_THRESHOLD:
            expected_open_type = OPEN_TYPE_GAP_UP
        elif open_gap_pct < -DEFAULT_GAP_THRESHOLD:
            expected_open_type = OPEN_TYPE_GAP_DOWN
        else:
            expected_open_type = OPEN_TYPE_FLAT

        # 构造一定触发买入的场景
        if expected_open_type == OPEN_TYPE_GAP_UP:
            anchor = open_price
            bdp = gap_up_buy_dip
        else:
            anchor = prev_close
            bdp = buy_dip_pct

        buy_price = anchor * (1 - bdp / 100)
        low_price = buy_price * 0.99  # 确保触发
        high_price = max(prev_close * 1.10, open_price * 1.10)
        close_price = prev_close

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': open_price,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'high_rise_pct': (high_price - prev_close) / prev_close * 100,
            'low_drop_pct': (low_price - prev_close) / prev_close * 100,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
            'open_type': expected_open_type,
            'open_gap_pct': round(open_gap_pct, 4),
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': sell_rise_pct,
            'stop_loss_pct': 50.0,
        }}

        open_type_params = {
            'gap_up': {
                'buy_dip_pct': gap_up_buy_dip,
                'sell_rise_pct': gap_up_sell_rise,
                'stop_loss_pct': 50.0,
            },
        }

        trades = strategy.simulate_trades(
            metrics, trade_params,
            enable_open_type_anchor=True,
            open_type_params=open_type_params,
        )

        for trade in trades:
            assert 'open_type' in trade, "Missing open_type in trade record"
            assert trade['open_type'] in OPEN_TYPES, f"Invalid open_type: {trade['open_type']}"

            if trade['open_type'] == OPEN_TYPE_GAP_UP:
                assert trade['anchor_type'] == 'open_price', \
                    f"gap_up should use open_price anchor, got {trade['anchor_type']}"
                assert abs(trade['anchor_price'] - round(open_price, 3)) < 0.01, \
                    f"gap_up anchor_price {trade['anchor_price']} != open_price {open_price}"
            elif trade['open_type'] == OPEN_TYPE_FLAT:
                assert trade['anchor_type'] == 'prev_close', \
                    f"flat should use prev_close anchor, got {trade['anchor_type']}"
            elif trade['open_type'] == OPEN_TYPE_GAP_DOWN:
                assert trade['anchor_type'] == 'prev_close', \
                    f"gap_down should use prev_close anchor, got {trade['anchor_type']}"

    def test_gap_up_uses_open_price_anchor(self):
        """高开日使用 open_price 锚点"""
        strategy = PricePositionStrategy()
        prev_close = 100.0
        open_price = 102.0  # 高开 2%

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': open_price,
            'high_price': 105.0,
            'low_price': 98.0,
            'close_price': 103.0,
            'high_rise_pct': 5.0,
            'low_drop_pct': -2.0,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
            'open_type': OPEN_TYPE_GAP_UP,
            'open_gap_pct': 2.0,
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': 2.0,
            'sell_rise_pct': 2.0,
            'stop_loss_pct': 3.0,
        }}

        open_type_params = {
            'gap_up': {
                'buy_dip_pct': 2.0,
                'sell_rise_pct': 1.5,
                'stop_loss_pct': 50.0,
            },
        }

        trades = strategy.simulate_trades(
            metrics, trade_params,
            enable_open_type_anchor=True,
            open_type_params=open_type_params,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade['anchor_type'] == 'open_price'
        assert trade['open_type'] == OPEN_TYPE_GAP_UP
        # buy_price = 102 * (1 - 2/100) = 99.96
        expected_buy = open_price * (1 - 2.0 / 100)
        assert abs(trade['buy_price'] - round(expected_buy, 3)) < 0.01

    def test_flat_uses_prev_close_anchor(self):
        """平开日使用 prev_close 锚点"""
        strategy = PricePositionStrategy()
        prev_close = 100.0
        open_price = 100.2  # 平开 0.2%

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': open_price,
            'high_price': 105.0,
            'low_price': 95.0,
            'close_price': 101.0,
            'high_rise_pct': 5.0,
            'low_drop_pct': -5.0,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
            'open_type': OPEN_TYPE_FLAT,
            'open_gap_pct': 0.2,
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': 2.0,
            'sell_rise_pct': 2.0,
            'stop_loss_pct': 50.0,
        }}

        trades = strategy.simulate_trades(
            metrics, trade_params,
            enable_open_type_anchor=True,
            open_type_params={'gap_up': {'buy_dip_pct': 1.0, 'sell_rise_pct': 1.0, 'stop_loss_pct': 2.0}},
        )

        assert len(trades) == 1
        assert trades[0]['anchor_type'] == 'prev_close'
        assert trades[0]['open_type'] == OPEN_TYPE_FLAT


# ========== Property 19: 低开日跳过一致性 ==========

class TestProperty19GapDownSkipConsistency:
    """
    **Validates: Requirements AC-6.2**

    Property 10 (Open-Type): 低开日跳过一致性
    当 skip_gap_down=True 时：
    - simulate_trades() 返回的交易记录中不包含 open_type == 'gap_down' 的记录
    """

    @given(
        prev_close=st.floats(min_value=50.0, max_value=300.0, allow_nan=False, allow_infinity=False),
        buy_dip_pct=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        sell_rise_pct=st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
        open_types=st.lists(
            st.sampled_from(OPEN_TYPES),
            min_size=1, max_size=10,
        ),
    )
    @settings(max_examples=300)
    def test_no_gap_down_trades_when_skip(
        self, prev_close, buy_dip_pct, sell_rise_pct, open_types
    ):
        """skip_gap_down=True 时无 gap_down 交易"""
        strategy = PricePositionStrategy()

        metrics = []
        for i, ot in enumerate(open_types):
            if ot == OPEN_TYPE_GAP_UP:
                op = prev_close * 1.02
            elif ot == OPEN_TYPE_GAP_DOWN:
                op = prev_close * 0.98
            else:
                op = prev_close * 1.001

            buy_price_target = prev_close * (1 - buy_dip_pct / 100)
            metrics.append({
                'date': f'2025-01-{(i % 28) + 1:02d}',
                'stock_code': 'HK.00700',
                'prev_close': prev_close,
                'open_price': op,
                'high_price': prev_close * 1.08,
                'low_price': buy_price_target * 0.98,
                'close_price': prev_close,
                'high_rise_pct': 8.0,
                'low_drop_pct': -8.0,
                'price_position': 50.0,
                'zone': '中位(40-60%)',
                'open_type': ot,
                'open_gap_pct': (op - prev_close) / prev_close * 100,
            })

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': buy_dip_pct,
            'sell_rise_pct': sell_rise_pct,
            'stop_loss_pct': 50.0,
        }}

        trades = strategy.simulate_trades(
            metrics, trade_params,
            enable_open_type_anchor=True,
            skip_gap_down=True,
        )

        for trade in trades:
            assert trade['open_type'] != OPEN_TYPE_GAP_DOWN, \
                f"Found gap_down trade on {trade['date']} when skip_gap_down=True"

    def test_gap_down_trades_present_when_not_skip(self):
        """skip_gap_down=False 时允许 gap_down 交易"""
        strategy = PricePositionStrategy()
        prev_close = 100.0

        metrics = [{
            'date': '2025-01-15',
            'stock_code': 'HK.00700',
            'prev_close': prev_close,
            'open_price': 98.0,
            'high_price': 105.0,
            'low_price': 94.0,
            'close_price': 99.0,
            'high_rise_pct': 5.0,
            'low_drop_pct': -6.0,
            'price_position': 50.0,
            'zone': '中位(40-60%)',
            'open_type': OPEN_TYPE_GAP_DOWN,
            'open_gap_pct': -2.0,
        }]

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': 2.0,
            'sell_rise_pct': 2.0,
            'stop_loss_pct': 50.0,
        }}

        trades = strategy.simulate_trades(
            metrics, trade_params,
            enable_open_type_anchor=True,
            skip_gap_down=False,
        )

        assert len(trades) == 1
        assert trades[0]['open_type'] == OPEN_TYPE_GAP_DOWN

    def test_skip_gap_down_vs_not_skip(self):
        """skip_gap_down=True 比 False 少 gap_down 交易"""
        strategy = PricePositionStrategy()
        prev_close = 100.0

        metrics = []
        for i, ot in enumerate([OPEN_TYPE_GAP_UP, OPEN_TYPE_FLAT, OPEN_TYPE_GAP_DOWN]):
            if ot == OPEN_TYPE_GAP_UP:
                op = 102.0
            elif ot == OPEN_TYPE_GAP_DOWN:
                op = 98.0
            else:
                op = 100.0
            metrics.append({
                'date': f'2025-01-{i+15:02d}',
                'stock_code': 'HK.00700',
                'prev_close': prev_close,
                'open_price': op,
                'high_price': 108.0,
                'low_price': 93.0,
                'close_price': 100.0,
                'high_rise_pct': 8.0,
                'low_drop_pct': -7.0,
                'price_position': 50.0,
                'zone': '中位(40-60%)',
                'open_type': ot,
                'open_gap_pct': (op - prev_close) / prev_close * 100,
            })

        trade_params = {'中位(40-60%)': {
            'buy_dip_pct': 2.0,
            'sell_rise_pct': 2.0,
            'stop_loss_pct': 50.0,
        }}

        ot_params = {
            'gap_up': {'buy_dip_pct': 1.5, 'sell_rise_pct': 1.5, 'stop_loss_pct': 50.0},
        }

        trades_skip = strategy.simulate_trades(
            metrics, trade_params,
            enable_open_type_anchor=True,
            open_type_params=ot_params,
            skip_gap_down=True,
        )
        trades_no_skip = strategy.simulate_trades(
            metrics, trade_params,
            enable_open_type_anchor=True,
            open_type_params=ot_params,
            skip_gap_down=False,
        )

        skip_types = [t['open_type'] for t in trades_skip]
        no_skip_types = [t['open_type'] for t in trades_no_skip]

        assert OPEN_TYPE_GAP_DOWN not in skip_types
        assert OPEN_TYPE_GAP_DOWN in no_skip_types