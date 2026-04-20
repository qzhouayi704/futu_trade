#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号检测器

负责：
1. 买入信号检测
2. 卖出信号检测
3. 信号验证
4. 信号生成
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from ...strategy.trend_reversal import TrendReversalStrategy
from ...utils.converters import get_last_price


@dataclass
class SignalRecord:
    """信号记录"""
    stock_code: str
    stock_name: str
    signal_type: str  # BUY / SELL
    price: float
    reason: str
    timestamp: str
    strategy_id: str
    preset_name: str
    strategy_data: Dict[str, Any] = field(default_factory=dict)


class SignalDetector:
    """信号检测器 - 负责检测买卖信号"""

    def __init__(
        self,
        strategy: TrendReversalStrategy,
        strategy_id: str,
        strategy_name: str,
        preset_name: str
    ):
        """
        初始化信号检测器

        Args:
            strategy: 策略实例
            strategy_id: 策略ID
            strategy_name: 策略名称
            preset_name: 预设名称
        """
        self.strategy = strategy
        self.strategy_id = strategy_id
        self.strategy_name = strategy_name
        self.preset_name = preset_name

        logging.info(f"信号检测器初始化: {strategy_name} - {preset_name}")

    def check_signals(
        self,
        quotes: List[Dict[str, Any]],
        kline_data: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        检查股票池中所有股票的买卖信号

        Args:
            quotes: 实时报价列表
            kline_data: K线数据字典 {stock_code: [kline_list]}

        Returns:
            信号列表
        """
        signals = []
        skipped_stocks = []

        for quote in quotes:
            try:
                stock_code = quote.get('code', '')
                stock_name = quote.get('name', '')

                if not stock_code:
                    continue

                # 获取该股票的K线数据
                klines = kline_data.get(stock_code, [])

                required_days = self.strategy.get_required_kline_days()
                if len(klines) < required_days:
                    skipped_stocks.append(f"{stock_name}({stock_code})")
                    continue

                # 构建报价数据
                quote_data = {
                    'last_price': get_last_price(quote),
                    'high_price': quote.get('high_price', 0),
                    'low_price': quote.get('low_price', 0),
                    'open_price': quote.get('open_price', 0)
                }

                # 检查策略信号
                signal_result = self.strategy.check_signals(stock_code, quote_data, klines)

                # 生成买入信号
                if signal_result.buy_signal:
                    signal = self._create_signal(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        signal_type='BUY',
                        price=quote_data['last_price'],
                        reason=signal_result.buy_reason,
                        strategy_data=signal_result.strategy_data
                    )
                    signals.append(signal)
                    logging.info(f"买入信号[{self.strategy_name}]: {stock_name}({stock_code}) @ {quote_data['last_price']}")

                # 生成卖出信号
                if signal_result.sell_signal:
                    signal = self._create_signal(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        signal_type='SELL',
                        price=quote_data['last_price'],
                        reason=signal_result.sell_reason,
                        strategy_data=signal_result.strategy_data
                    )
                    signals.append(signal)
                    logging.info(f"卖出信号[{self.strategy_name}]: {stock_name}({stock_code}) @ {quote_data['last_price']}")

            except Exception as e:
                logging.error(f"检查信号失败 {quote.get('code', 'unknown')}: {e}")

        if skipped_stocks:
            preview = ', '.join(skipped_stocks[:5])
            suffix = f' 等共 {len(skipped_stocks)} 只' if len(skipped_stocks) > 5 else ''
            logging.debug(
                f"[{self.strategy_name}] K线数据不足被跳过: {preview}{suffix}"
            )

        return signals

    def analyze_stock(
        self,
        quote: Dict[str, Any],
        klines: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        分析单只股票的策略状态

        Args:
            quote: 股票报价
            klines: K线数据

        Returns:
            股票的策略分析结果
        """
        stock_code = quote.get('code', '')
        stock_name = quote.get('name', '')

        result = {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'strategy_id': self.strategy_id,
            'strategy_name': self.strategy_name,
            'preset_name': self.preset_name,
            'status': 'WATCH',  # WATCH / BUY_SIGNAL / SELL_SIGNAL / NO_DATA / ERROR
            'buy_signal': False,
            'sell_signal': False,
            'strategy_data': {},
            'conditions': []
        }

        try:
            # 检查数据是否充足
            required_days = self.strategy.get_required_kline_days()
            if len(klines) < required_days:
                result['status'] = 'NO_DATA'
                result['conditions'].append(f'数据不足（需要{required_days}天）')
                return result

            # 构建报价数据
            quote_data = {
                'last_price': get_last_price(quote),
                'high_price': quote.get('high_price', 0),
                'low_price': quote.get('low_price', 0),
                'open_price': quote.get('open_price', 0)
            }

            # 检查策略信号
            signal_result = self.strategy.check_signals(stock_code, quote_data, klines)

            result['buy_signal'] = signal_result.buy_signal
            result['sell_signal'] = signal_result.sell_signal
            result['strategy_data'] = signal_result.strategy_data

            # 设置状态和条件
            if signal_result.buy_signal:
                result['status'] = 'BUY_SIGNAL'
                result['conditions'].append(signal_result.buy_reason)
            elif signal_result.sell_signal:
                result['status'] = 'SELL_SIGNAL'
                result['conditions'].append(signal_result.sell_reason)
            else:
                result['status'] = 'WATCH'
                result['conditions'].append(signal_result.buy_reason)

        except Exception as e:
            result['status'] = 'ERROR'
            result['conditions'].append(f'分析错误: {str(e)}')
            logging.error(f"分析股票失败 {stock_code}: {e}")

        return result

    def _create_signal(
        self,
        stock_code: str,
        stock_name: str,
        signal_type: str,
        price: float,
        reason: str,
        strategy_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        创建信号记录

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            signal_type: 信号类型 (BUY/SELL)
            price: 价格
            reason: 原因
            strategy_data: 策略数据

        Returns:
            信号字典
        """
        return {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'signal_type': signal_type,
            'price': price,
            'reason': reason,
            'timestamp': datetime.now().isoformat(),
            'strategy_id': self.strategy_id,
            'strategy_name': self.strategy_name,
            'preset_name': self.preset_name,
            'strategy_data': strategy_data
        }

    def update_strategy(
        self,
        strategy: TrendReversalStrategy,
        strategy_id: str,
        strategy_name: str,
        preset_name: str
    ):
        """
        更新策略配置

        Args:
            strategy: 新的策略实例
            strategy_id: 策略ID
            strategy_name: 策略名称
            preset_name: 预设名称
        """
        self.strategy = strategy
        self.strategy_id = strategy_id
        self.strategy_name = strategy_name
        self.preset_name = preset_name

        logging.info(f"信号检测器已更新: {strategy_name} - {preset_name}")
