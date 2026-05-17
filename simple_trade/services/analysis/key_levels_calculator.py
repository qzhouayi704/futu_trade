#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
关键价位计算器

盘前基于日K线计算当日交易参考价位：
- 前日高低收
- 近5日支撑/阻力位
- Fibonacci 回撤位（暴涨后回调股）
- VWAP 偏离度信号阈值（基于案例分析）
- 建议买入区间和止损位（根据股票标签调整）
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class KeyLevels:
    """关键价位"""
    # 前日价位
    prev_high: float = 0
    prev_low: float = 0
    prev_close: float = 0

    # 近5日极值
    support_5d: float = 0       # 5日最低点（支撑）
    resistance_5d: float = 0    # 5日最高点（阻力）

    # Fibonacci 回撤位（基于近期高低点）
    fib_382: float = 0          # 38.2% 回撤
    fib_500: float = 0          # 50% 回撤
    fib_618: float = 0          # 61.8% 回撤

    # 建议区间
    buy_zone_low: float = 0     # 建议买入区下界
    buy_zone_high: float = 0    # 建议买入区上界
    stop_loss: float = 0        # 建议止损位

    # VWAP 偏离度阈值（基于8个案例分析）
    vwap_buy_near: float = -2.0    # 强势回踩买点：偏离-2%以内
    vwap_buy_far: float = -5.0     # 超卖反弹买点：偏离-5%以下
    vwap_sell: float = 8.0         # 卖出区：偏离+8%以上

    def to_dict(self) -> Dict[str, Any]:
        return {
            'prev_high': round(self.prev_high, 3),
            'prev_low': round(self.prev_low, 3),
            'prev_close': round(self.prev_close, 3),
            'support_5d': round(self.support_5d, 3),
            'resistance_5d': round(self.resistance_5d, 3),
            'fib_382': round(self.fib_382, 3),
            'fib_500': round(self.fib_500, 3),
            'fib_618': round(self.fib_618, 3),
            'buy_zone_low': round(self.buy_zone_low, 3),
            'buy_zone_high': round(self.buy_zone_high, 3),
            'stop_loss': round(self.stop_loss, 3),
            'vwap_buy_near': self.vwap_buy_near,
            'vwap_buy_far': self.vwap_buy_far,
            'vwap_sell': self.vwap_sell,
        }


# VWAP偏离度阈值按标签调整
VWAP_THRESHOLDS = {
    '锁仓控盘': {'buy_near': -3.0, 'buy_far': -8.0, 'sell': 10.0},
    '暴量拉升': {'buy_near': -3.0, 'buy_far': -6.0, 'sell': 8.0},
    '仙股炒作': {'buy_near': -5.0, 'buy_far': -10.0, 'sell': 15.0},
    '明星高波动': {'buy_near': -2.0, 'buy_far': -5.0, 'sell': 8.0},
    '正常':     {'buy_near': -1.5, 'buy_far': -3.0, 'sell': 5.0},
}

# 止损比例按标签调整
STOP_LOSS_PCT = {
    '锁仓控盘': 0.10,
    '暴量拉升': 0.08,
    '仙股炒作': 0.15,
    '明星高波动': 0.08,
    '正常': 0.05,
}


class KeyLevelsCalculator:
    """关键价位计算器"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def calculate(
        self,
        klines: List[Dict[str, Any]],
        stock_label: str = "正常"
    ) -> KeyLevels:
        """
        计算关键价位

        Args:
            klines: 日K线数据（按时间升序，最新在最后），至少2天
            stock_label: 股票标签（影响VWAP阈值和止损比例）

        Returns:
            KeyLevels
        """
        levels = KeyLevels()

        if not klines or len(klines) < 2:
            return levels

        # 前日数据
        prev = klines[-1]
        levels.prev_high = prev.get('high', prev.get('high_price', 0)) or 0
        levels.prev_low = prev.get('low', prev.get('low_price', 0)) or 0
        levels.prev_close = prev.get('close', prev.get('close_price', 0)) or 0

        # 近5日支撑/阻力
        recent_5 = klines[-5:] if len(klines) >= 5 else klines
        highs = [k.get('high', k.get('high_price', 0)) or 0 for k in recent_5]
        lows = [k.get('low', k.get('low_price', 0)) or 0 for k in recent_5]
        lows = [l for l in lows if l > 0]

        levels.resistance_5d = max(highs) if highs else 0
        levels.support_5d = min(lows) if lows else 0

        # Fibonacci 回撤位
        if levels.resistance_5d > 0 and levels.support_5d > 0:
            diff = levels.resistance_5d - levels.support_5d
            levels.fib_382 = levels.resistance_5d - diff * 0.382
            levels.fib_500 = levels.resistance_5d - diff * 0.500
            levels.fib_618 = levels.resistance_5d - diff * 0.618

        # 建议买入区间（支撑位附近 ±1%）
        support = levels.support_5d if levels.support_5d > 0 else levels.prev_low
        if support > 0:
            levels.buy_zone_low = support * 0.99
            levels.buy_zone_high = support * 1.01

        # 止损位（按标签调整）
        stop_pct = STOP_LOSS_PCT.get(stock_label, 0.05)
        if support > 0:
            levels.stop_loss = support * (1 - stop_pct)

        # VWAP 偏离度阈值（按标签调整）
        thresholds = VWAP_THRESHOLDS.get(stock_label, VWAP_THRESHOLDS['正常'])
        levels.vwap_buy_near = thresholds['buy_near']
        levels.vwap_buy_far = thresholds['buy_far']
        levels.vwap_sell = thresholds['sell']

        return levels
