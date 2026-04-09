#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SwingStrategy.check_signals() 重构等价性测试

验证重构后的 check_signals 方法对各种输入产生与预期一致的信号结果。
"""

import unittest
from simple_trade.strategy.swing_strategy import SwingStrategy


def make_kline(date: str, high: float, low: float, close: float, open_p: float = 0) -> dict:
    """构造K线数据"""
    return {
        'date': date,
        'high': high,
        'low': low,
        'close': close if close else (high + low) / 2,
        'open': open_p if open_p else low,
        'volume': 1000
    }


def make_kline_series(n: int, base_high: float = 10.0, base_low: float = 8.0) -> list:
    """构造N天K线序列，最后一天为极值点"""
    klines = []
    for i in range(n):
        day_offset = i - n + 1
        klines.append(make_kline(
            date=f'2025-01-{15 + day_offset:02d}',
            high=base_high + (i * 0.1),
            low=base_low + (i * 0.1),
            close=(base_high + base_low) / 2 + (i * 0.1)
        ))
    return klines


class TestCheckSignalsBuyLogic(unittest.TestCase):
    """买入信号检查测试"""

    def setUp(self):
        self.strategy = SwingStrategy(config={'lookback_days': 12})

    def test_buy_signal_triggered(self):
        """昨日最低价=12日最低点 且 今日最低价>昨日最低价 → 买入信号"""
        # 构造：最后一天的low是所有天中最低的
        klines = []
        for i in range(12):
            klines.append(make_kline(
                date=f'2025-01-{i + 1:02d}',
                high=10.0 + i * 0.1,
                low=8.5 + i * 0.05,  # 递增，第一天最低=8.5
                close=9.0 + i * 0.05
            ))
        # 最后一天low最低
        klines[-1] = make_kline(date='2025-01-12', high=10.5, low=8.0, close=9.0)

        quote = {'high_price': 11.0, 'low_price': 8.1}  # 今日low > 昨日low(8.0)
        result = self.strategy.check_signals('TEST.HK', quote, klines)

        self.assertTrue(result.buy_signal)
        self.assertIn('低吸信号', result.buy_reason)

    def test_buy_signal_not_triggered_low_not_min(self):
        """今日最低价>昨日最低价 但昨日最低价不是12日最低点 → 无买入信号"""
        klines = []
        for i in range(12):
            klines.append(make_kline(
                date=f'2025-01-{i + 1:02d}',
                high=10.0,
                low=8.0 + i * 0.1,  # 递增，第一天最低
                close=9.0
            ))
        # 最后一天low=9.1，不是最低点（第一天8.0才是）
        quote = {'high_price': 11.0, 'low_price': 9.2}
        result = self.strategy.check_signals('TEST.HK', quote, klines)

        self.assertFalse(result.buy_signal)

    def test_buy_signal_not_triggered_today_low_equal(self):
        """昨日最低价是12日最低点 但今日最低价=昨日最低价（持平）→ 无买入信号"""
        klines = []
        for i in range(12):
            klines.append(make_kline(
                date=f'2025-01-{i + 1:02d}',
                high=10.0,
                low=8.5,
                close=9.0
            ))
        klines[-1] = make_kline(date='2025-01-12', high=10.0, low=8.0, close=9.0)

        quote = {'high_price': 11.0, 'low_price': 8.0}  # 持平
        result = self.strategy.check_signals('TEST.HK', quote, klines)

        self.assertFalse(result.buy_signal)
        self.assertIn('持平', result.buy_reason)


class TestCheckSignalsSellLogic(unittest.TestCase):
    """卖出信号检查测试"""

    def setUp(self):
        self.strategy = SwingStrategy(config={'lookback_days': 12})

    def test_sell_signal_triggered(self):
        """昨日最高价=12日最高点 且 今日最高价<昨日最高价 → 卖出信号"""
        klines = []
        for i in range(12):
            klines.append(make_kline(
                date=f'2025-01-{i + 1:02d}',
                high=10.0 - i * 0.05,  # 递减
                low=8.0,
                close=9.0
            ))
        # 最后一天high最高
        klines[-1] = make_kline(date='2025-01-12', high=12.0, low=8.0, close=10.0)

        quote = {'high_price': 11.9, 'low_price': 8.5}  # 今日high < 昨日high(12.0)
        result = self.strategy.check_signals('TEST.HK', quote, klines)

        self.assertTrue(result.sell_signal)
        self.assertIn('高抛信号', result.sell_reason)

    def test_sell_signal_not_triggered_high_not_max(self):
        """今日最高价<昨日最高价 但昨日最高价不是12日最高点 → 无卖出信号"""
        klines = []
        for i in range(12):
            klines.append(make_kline(
                date=f'2025-01-{i + 1:02d}',
                high=12.0 - i * 0.1,  # 递减，第一天最高
                low=8.0,
                close=9.0
            ))
        # 最后一天high=10.9，不是最高点
        quote = {'high_price': 10.8, 'low_price': 8.5}
        result = self.strategy.check_signals('TEST.HK', quote, klines)

        self.assertFalse(result.sell_signal)


class TestCheckSignalsSellPriority(unittest.TestCase):
    """卖出优先级测试：传统高抛优先于窄幅震荡"""

    def setUp(self):
        self.strategy = SwingStrategy(config={
            'lookback_days': 12,
            'narrow_range_enabled': True,
        })

    def test_traditional_sell_blocks_narrow_range(self):
        """传统高抛卖出触发时，不应检查窄幅震荡"""
        klines = []
        for i in range(30):
            klines.append(make_kline(
                date=f'2025-01-{i + 1:02d}' if i < 28 else f'2025-02-{i - 27:02d}',
                high=10.0 - i * 0.02,
                low=8.0,
                close=9.0
            ))
        # 最后一天high最高 → 触发传统卖出
        klines[-1] = make_kline(date='2025-02-02', high=12.0, low=8.0, close=10.0)

        quote = {'high_price': 11.9, 'low_price': 8.5}
        result = self.strategy.check_signals('TEST.HK', quote, klines)

        self.assertTrue(result.sell_signal)
        self.assertIn('高抛信号', result.sell_reason)
        # narrow_range_check 应该为 None（未检查）
        self.assertIsNone(result.strategy_data.get('narrow_range_check'))


class TestCheckSignalsDataInsufficient(unittest.TestCase):
    """数据不足测试"""

    def setUp(self):
        self.strategy = SwingStrategy(config={'lookback_days': 12})

    def test_insufficient_data(self):
        """K线数据不足时返回数据不足提示"""
        klines = [make_kline('2025-01-01', 10.0, 8.0, 9.0) for _ in range(5)]
        quote = {'high_price': 10.0, 'low_price': 8.0}
        result = self.strategy.check_signals('TEST.HK', quote, klines)

        self.assertFalse(result.buy_signal)
        self.assertFalse(result.sell_signal)
        self.assertIn('数据不足', result.buy_reason)
        self.assertIn('数据不足', result.sell_reason)


class TestCheckSignalsStrategyData(unittest.TestCase):
    """strategy_data 完整性测试"""

    def setUp(self):
        self.strategy = SwingStrategy(config={'lookback_days': 12})

    def test_strategy_data_fields(self):
        """验证 strategy_data 包含所有必要字段"""
        klines = make_kline_series(15)
        quote = {'high_price': 11.0, 'low_price': 9.0}
        result = self.strategy.check_signals('TEST.HK', quote, klines)

        expected_keys = [
            'today_high', 'today_low', 'yesterday_high', 'yesterday_low',
            'max_high_nd', 'min_low_nd', 'kline_count', 'lookback_days',
            'kline_last_date', 'kline_outdated',
            'price_position_30d', 'max_high_30d', 'min_low_30d',
            'narrow_range_check'
        ]
        for key in expected_keys:
            self.assertIn(key, result.strategy_data, f"缺少字段: {key}")


class TestCalculatePricePosition30d(unittest.TestCase):
    """_calculate_price_position_30d 辅助方法测试"""

    def setUp(self):
        self.strategy = SwingStrategy(config={'lookback_days': 12})

    def test_position_with_30d_data(self):
        """30天数据时正确计算价格位置"""
        klines = []
        for i in range(30):
            klines.append(make_kline(
                date=f'2025-01-{i + 1:02d}' if i < 28 else f'2025-02-{i - 27:02d}',
                high=10.0 + i * 0.1,  # 最高=12.9
                low=8.0 + i * 0.05,   # 最低=8.0
                close=9.0
            ))
        # 当前价格在中间
        pos, max_h, min_l = self.strategy._calculate_price_position_30d(klines, 10.0, 9.0)
        self.assertGreater(pos, 0)
        self.assertLess(pos, 100)
        self.assertGreater(max_h, 0)
        self.assertGreater(min_l, 0)

    def test_position_insufficient_data(self):
        """数据不足12天时返回默认值"""
        klines = [make_kline('2025-01-01', 10.0, 8.0, 9.0) for _ in range(5)]
        pos, max_h, min_l = self.strategy._calculate_price_position_30d(klines, 10.0, 8.0)
        self.assertEqual(pos, 50.0)
        self.assertEqual(max_h, 0.0)
        self.assertEqual(min_l, 0.0)


if __name__ == '__main__':
    unittest.main()
