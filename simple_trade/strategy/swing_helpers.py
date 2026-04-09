#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
低吸高抛策略 - 辅助方法模块

从 swing_strategy.py 中提取的辅助方法：
- 信号强度计算
- 策略条件描述
- 策略描述信息
"""

import logging
from typing import Dict, Any, List


# 策略参数默认值（集中管理）
SWING_DEFAULTS = {
    'lookback_days': 12,
    'stop_loss_pct': -10.0,
    'stop_loss_min_rise_pct': 5.0,
    'stop_loss_check_days': 3,
    'narrow_range_enabled': True,
    'narrow_range_amplitude_threshold': 3.0,
    'narrow_range_check_days': 5,
    'narrow_range_daily_rise_threshold': 1.0,
    'narrow_range_min_position': 70.0,
}


class SwingStrategyHelpers:
    """SwingStrategy 的辅助方法 Mixin"""

    def get_buy_conditions(self) -> List[str]:
        return [
            f'今日最低价 > 昨日最低价',
            f'昨日最低价 = 近{self.lookback_days}日最低点'
        ]

    def get_sell_conditions(self) -> List[str]:
        """获取卖出条件列表（包含经典卖点和窄幅震荡卖点）"""
        conditions = [
            f'【经典卖点】今日最高价 < 昨日最高价 且 昨日最高价 = 近{self.lookback_days}日最高点'
        ]
        if self.narrow_range_enabled:
            conditions.append(
                f'【窄幅震荡卖点】价格位于30日高位(>={self.narrow_range_min_position:.0f}%) + '
                f'近{self.narrow_range_check_days}天平均振幅<{self.narrow_range_amplitude_threshold:.1f}% + '
                f'连续{self.narrow_range_check_days}天涨幅<{self.narrow_range_daily_rise_threshold:.1f}%'
            )
        return conditions

    def get_required_kline_days(self) -> int:
        return self.lookback_days

    def calculate_signal_strength(self, result) -> float:
        """计算信号强度（0-1之间）"""
        try:
            strength = 0.5 if result.has_signal else 0.0
            strategy_data = result.strategy_data

            if strategy_data.get('kline_count', 0) >= self.lookback_days:
                strength += 0.2

            today_high = strategy_data.get('today_high', 0)
            today_low = strategy_data.get('today_low', 0)
            max_high_nd = strategy_data.get('max_high_nd', 0)
            min_low_nd = strategy_data.get('min_low_nd', 0)

            if max_high_nd > min_low_nd:
                current_avg = (today_high + today_low) / 2
                price_position = (current_avg - min_low_nd) / (max_high_nd - min_low_nd)
                if result.buy_signal and price_position < 0.3:
                    strength += 0.3
                elif result.sell_signal and price_position > 0.7:
                    strength += 0.3

            return min(strength, 1.0)
        except Exception as e:
            logging.error(f"计算信号强度失败: {e}")
            return 0.0

    def get_strategy_description(self) -> Dict[str, Any]:
        """获取策略描述信息（兼容旧版本接口）"""
        return {
            'name': self.name,
            'description': self.description,
            'buy_conditions': self.get_buy_conditions(),
            'sell_conditions': self.get_sell_conditions(),
            'stop_loss_conditions': self.get_stop_loss_conditions(),
            'narrow_range_sell_conditions': self.get_narrow_range_sell_conditions(),
            'narrow_range_enabled': self.narrow_range_enabled,
            'additional_filters': [
                '股票价格在合理范围内（0.10-1000元）',
                f'历史数据充足（≥{self.lookback_days}天K线数据）'
            ],
            'risk_notice': '该策略基于技术分析，存在投资风险，仅供参考'
        }
