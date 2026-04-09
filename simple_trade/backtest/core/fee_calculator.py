#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易手续费计算器
支持港股和美股的手续费计算
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from enum import Enum


class Market(Enum):
    """市场类型"""
    HK = "HK"
    US = "US"


@dataclass
class FeeDetail:
    """手续费明细"""
    commission: float = 0.0        # 佣金
    platform_fee: float = 0.0      # 平台费
    stamp_duty: float = 0.0        # 印花税
    transaction_levy: float = 0.0  # 交易征费
    trading_fee: float = 0.0       # 交易费
    settlement_fee: float = 0.0    # 结算费
    sec_fee: float = 0.0           # SEC费用（美股）
    finra_taf: float = 0.0         # FINRA TAF（美股）
    total: float = 0.0             # 总费用

    def to_dict(self) -> Dict[str, float]:
        return {
            'commission': self.commission,
            'platform_fee': self.platform_fee,
            'stamp_duty': self.stamp_duty,
            'transaction_levy': self.transaction_levy,
            'trading_fee': self.trading_fee,
            'settlement_fee': self.settlement_fee,
            'sec_fee': self.sec_fee,
            'finra_taf': self.finra_taf,
            'total': self.total
        }


class FeeCalculator:
    """交易手续费计算器"""

    # 默认港股费率配置
    DEFAULT_HK_FEES = {
        'commission_rate': 0.0003,      # 佣金率 0.03%
        'min_commission': 3.0,          # 最低佣金 3港币
        'platform_fee': 15.0,           # 平台费 15港币/笔
        'stamp_duty_rate': 0.0013,      # 印花税 0.13%
        'transaction_levy': 0.00005,    # 交易征费 0.005%
        'trading_fee': 0.0000565,       # 交易费 0.00565%
        'settlement_fee_rate': 0.00002, # 结算费 0.002%
        'min_settlement_fee': 2.0,      # 最低结算费 2港币
        'max_settlement_fee': 100.0     # 最高结算费 100港币
    }

    # 默认美股费率配置
    DEFAULT_US_FEES = {
        'commission_rate': 0.0,
        'fixed_commission': 0.99,       # 固定佣金
        'sec_fee_rate': 0.0000278,      # SEC费用
        'finra_taf_rate': 0.000119      # FINRA TAF
    }

    def __init__(self, fee_config: Optional[Dict[str, Any]] = None):
        """
        初始化手续费计算器

        Args:
            fee_config: 手续费配置，格式为 {'HK': {...}, 'US': {...}}
        """
        self.fee_config = fee_config or {}

    def get_market_config(self, market: str) -> Dict[str, float]:
        """获取指定市场的费率配置"""
        if market == 'HK':
            config = self.DEFAULT_HK_FEES.copy()
            if 'HK' in self.fee_config:
                config.update(self.fee_config['HK'])
            return config
        elif market == 'US':
            config = self.DEFAULT_US_FEES.copy()
            if 'US' in self.fee_config:
                config.update(self.fee_config['US'])
            return config
        else:
            return self.DEFAULT_HK_FEES.copy()

    def calculate_hk_fee(
        self,
        amount: float,
        is_buy: bool = True
    ) -> FeeDetail:
        """
        计算港股交易手续费

        Args:
            amount: 交易金额（港币）
            is_buy: 是否为买入

        Returns:
            FeeDetail 手续费明细
        """
        config = self.get_market_config('HK')
        fee = FeeDetail()

        # 1. 佣金
        commission = amount * config['commission_rate']
        fee.commission = max(commission, config['min_commission'])

        # 2. 平台费
        fee.platform_fee = config['platform_fee']

        # 3. 印花税（买卖双向）
        fee.stamp_duty = amount * config['stamp_duty_rate']

        # 4. 交易征费
        fee.transaction_levy = amount * config['transaction_levy']

        # 5. 交易费
        fee.trading_fee = amount * config['trading_fee']

        # 6. 结算费
        settlement = amount * config['settlement_fee_rate']
        fee.settlement_fee = max(
            min(settlement, config['max_settlement_fee']),
            config['min_settlement_fee']
        )

        # 计算总费用
        fee.total = (
            fee.commission +
            fee.platform_fee +
            fee.stamp_duty +
            fee.transaction_levy +
            fee.trading_fee +
            fee.settlement_fee
        )

        return fee

    def calculate_us_fee(
        self,
        amount: float,
        shares: int,
        is_buy: bool = True
    ) -> FeeDetail:
        """
        计算美股交易手续费

        Args:
            amount: 交易金额（美元）
            shares: 股数
            is_buy: 是否为买入

        Returns:
            FeeDetail 手续费明细
        """
        config = self.get_market_config('US')
        fee = FeeDetail()

        # 1. 佣金（固定费用）
        fee.commission = config.get('fixed_commission', 0.99)

        # 2. SEC费用（仅卖出）
        if not is_buy:
            fee.sec_fee = amount * config['sec_fee_rate']

        # 3. FINRA TAF（仅卖出）
        if not is_buy:
            fee.finra_taf = shares * config['finra_taf_rate']

        # 计算总费用
        fee.total = fee.commission + fee.sec_fee + fee.finra_taf

        return fee

    def calculate_fee(
        self,
        market: str,
        amount: float,
        shares: int = 0,
        is_buy: bool = True
    ) -> FeeDetail:
        """
        计算交易手续费（通用接口）

        Args:
            market: 市场类型 ('HK' 或 'US')
            amount: 交易金额
            shares: 股数（美股需要）
            is_buy: 是否为买入

        Returns:
            FeeDetail 手续费明细
        """
        if market == 'US':
            return self.calculate_us_fee(amount, shares, is_buy)
        else:
            return self.calculate_hk_fee(amount, is_buy)

    def calculate_round_trip_fee(
        self,
        market: str,
        buy_amount: float,
        sell_amount: float,
        shares: int = 0
    ) -> Dict[str, Any]:
        """
        计算一次完整交易（买入+卖出）的总手续费

        Args:
            market: 市场类型
            buy_amount: 买入金额
            sell_amount: 卖出金额
            shares: 股数

        Returns:
            {
                'buy_fee': FeeDetail,
                'sell_fee': FeeDetail,
                'total_fee': float,
                'fee_rate': float  # 手续费占比
            }
        """
        buy_fee = self.calculate_fee(market, buy_amount, shares, is_buy=True)
        sell_fee = self.calculate_fee(market, sell_amount, shares, is_buy=False)

        total_fee = buy_fee.total + sell_fee.total
        avg_amount = (buy_amount + sell_amount) / 2
        fee_rate = (total_fee / avg_amount * 100) if avg_amount > 0 else 0

        return {
            'buy_fee': buy_fee,
            'sell_fee': sell_fee,
            'total_fee': total_fee,
            'fee_rate': fee_rate
        }

    def estimate_breakeven_profit(
        self,
        market: str,
        trade_amount: float
    ) -> float:
        """
        估算盈亏平衡所需的最低收益率

        Args:
            market: 市场类型
            trade_amount: 交易金额

        Returns:
            盈亏平衡收益率（%）
        """
        # 假设买入卖出金额相同
        result = self.calculate_round_trip_fee(
            market, trade_amount, trade_amount
        )
        return result['fee_rate']
