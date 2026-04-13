#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多策略数据模型

定义多策略并行监控所需的数据结构。
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from ...strategy.base_strategy import BaseStrategy


@dataclass
class EnabledStrategyInfo:
    """已启用策略的运行时信息

    包含策略实例和实时统计数据，用于内存中管理已启用策略。
    """
    strategy_id: str
    strategy_name: str
    preset_name: str
    instance: BaseStrategy
    signal_detector: Any = None  # SignalDetector，避免循环导入
    signal_count_buy: int = 0
    signal_count_sell: int = 0

    def reset_signal_counts(self):
        """重置信号计数"""
        self.signal_count_buy = 0
        self.signal_count_sell = 0

    def to_dict(self) -> dict:
        """转换为 API 响应格式"""
        return {
            'strategy_id': self.strategy_id,
            'strategy_name': self.strategy_name,
            'preset_name': self.preset_name,
            'signal_count_buy': self.signal_count_buy,
            'signal_count_sell': self.signal_count_sell,
        }


@dataclass
class EnabledStrategyConfig:
    """已启用策略的持久化配置

    用于 config.json 的序列化/反序列化，不包含运行时实例。
    """
    strategy_id: str
    preset_name: str

    def to_dict(self) -> dict:
        """转换为可序列化的字典"""
        return {
            'strategy_id': self.strategy_id,
            'preset_name': self.preset_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Optional['EnabledStrategyConfig']:
        """从字典创建实例，数据无效时返回 None"""
        strategy_id = data.get('strategy_id')
        preset_name = data.get('preset_name')
        if not strategy_id or not preset_name:
            return None
        return cls(strategy_id=strategy_id, preset_name=preset_name)


# 默认策略配置（当 config.json 中无策略配置时使用）
DEFAULT_STRATEGIES: dict = {
    'trend_reversal': {
        'id': 'trend_reversal',
        'name': '高抛低吸策略',
        'description': '基于趋势反转的买卖点检测（追踪止盈+高抛兜底）',
        'active_preset': 'B-建议',
        'presets': {
            'A-保守': {
                'name': 'A-保守', 'description': '高门槛，信号少但精准',
                'lookback_days': 10, 'min_drop_pct': 15.0, 'min_rise_pct': 15.0,
                'min_reversal_pct': 3.0, 'max_up_ratio_buy': 0.4,
                'min_up_ratio_sell': 0.6, 'stop_loss_pct': -10.0, 'stop_loss_days': 5,
            },
            'B-建议': {
                'name': 'B-建议', 'description': '回测验证最优配置（胜率84%）',
                'lookback_days': 10, 'min_drop_pct': 13.0, 'min_rise_pct': 12.0,
                'min_reversal_pct': 2.0, 'max_up_ratio_buy': 0.5,
                'min_up_ratio_sell': 0.6, 'stop_loss_pct': -10.0, 'stop_loss_days': 5,
            },
        }
    },
    'price_position_live': {
        'id': 'price_position_live',
        'name': '日内价格位置策略',
        'description': '基于回测最优参数，监控股价到达买卖点时产生信号',
        'active_preset': '默认',
        'presets': {
            '默认': {
                'name': '默认', 'description': '使用回测自动优化的参数',
            },
        }
    },
    'aggressive': {
        'id': 'aggressive',
        'name': '激进交易策略',
        'description': '专注于强势板块中的热门龙头股，进行当日或隔日短线交易',
        'active_preset': '默认',
        'presets': {
            '默认': {
                'name': '默认', 'description': '基于回测优化的参数',
                'min_plate_strength': 70.0,
                'max_plate_rank': 3,
                'min_up_ratio': 0.6,
                'min_change_pct': 2.5,
                'max_change_pct': 5.0,
                'min_volume': 5000000,
                'min_price_position': 0,
                'max_price_position': 40,
                'target_profit_pct': 8.0,
                'trailing_trigger_pct': 6.0,
                'trailing_callback_pct': 2.0,
                'fixed_stop_loss_pct': -5.0,
                'quick_stop_loss_pct': -3.0,
                'plate_rank_threshold': 5,
                'max_holding_days': 1,
                'max_daily_signals': 2,
                'min_signal_strength': 0.7,
                'prefer_intraday': True,
            },
        }
    }
}
