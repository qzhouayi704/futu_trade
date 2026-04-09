#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动日内交易 - 数据模型与纯函数

包含 AutoTradeTask 数据类和无副作用的计算/判断函数。
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from datetime import datetime, date


# 有效的状态转换
VALID_TRANSITIONS = {
    'waiting_buy': {'bought', 'stopped'},
    'bought': {'completed', 'stop_loss', 'stopped'},
    'completed': set(),
    'stop_loss': set(),
    'stopped': set(),
}


@dataclass
class AutoTradeTask:
    """单只股票的自动交易任务"""
    stock_code: str
    quantity: int
    zone: str
    buy_dip_pct: float
    sell_rise_pct: float
    stop_loss_pct: float
    prev_close: float
    buy_target: float = 0.0
    sell_target: float = 0.0
    stop_price: float = 0.0
    status: str = 'waiting_buy'
    buy_price_actual: float = 0.0
    sell_price_actual: float = 0.0
    buy_date: Optional[date] = None
    created_at: str = ''
    updated_at: str = ''
    message: str = ''

    def __post_init__(self):
        self.buy_target = round(self.prev_close * (1 - self.buy_dip_pct / 100), 3)
        self.sell_target = round(self.prev_close * (1 + self.sell_rise_pct / 100), 3)
        self.stop_price = round(self.buy_target * (1 - self.stop_loss_pct / 100), 3)
        now = datetime.now().isoformat()
        self.created_at = now
        self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        return {
            'stock_code': self.stock_code,
            'quantity': self.quantity,
            'zone': self.zone,
            'buy_dip_pct': self.buy_dip_pct,
            'sell_rise_pct': self.sell_rise_pct,
            'stop_loss_pct': self.stop_loss_pct,
            'prev_close': self.prev_close,
            'buy_target': self.buy_target,
            'sell_target': self.sell_target,
            'stop_price': self.stop_price,
            'status': self.status,
            'buy_price_actual': self.buy_price_actual,
            'sell_price_actual': self.sell_price_actual,
            'buy_date': self.buy_date.isoformat() if self.buy_date else None,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'message': self.message,
        }


def calculate_targets(prev_close: float, buy_dip_pct: float,
                      sell_rise_pct: float, stop_loss_pct: float) -> Dict[str, float]:
    """
    计算目标价格（纯函数，便于测试）

    Args:
        prev_close: 前收盘价
        buy_dip_pct: 买入跌幅百分比
        sell_rise_pct: 卖出涨幅百分比
        stop_loss_pct: 止损百分比

    Returns:
        {'buy_target': float, 'sell_target': float, 'stop_price': float}
    """
    buy_target = prev_close * (1 - buy_dip_pct / 100)
    sell_target = prev_close * (1 + sell_rise_pct / 100)
    stop_price = buy_target * (1 - stop_loss_pct / 100)
    return {
        'buy_target': buy_target,
        'sell_target': sell_target,
        'stop_price': stop_price,
    }


def should_buy(price: float, buy_target: float) -> bool:
    """判断是否应该买入"""
    return price <= buy_target


def check_sell_condition(price: float, sell_target: float,
                         stop_price: float) -> Optional[str]:
    """
    检查卖出条件（止损优先）

    Returns:
        'stop_loss' | 'profit' | None
    """
    if price <= stop_price:
        return 'stop_loss'
    if price >= sell_target:
        return 'profit'
    return None


def is_valid_transition(current: str, target: str) -> bool:
    """检查状态转换是否有效"""
    return target in VALID_TRANSITIONS.get(current, set())
