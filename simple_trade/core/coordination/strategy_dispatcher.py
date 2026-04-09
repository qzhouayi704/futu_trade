#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一策略调度器

管理所有策略的注册、执行和信号汇总。
所有服务中的策略执行逻辑统一委托给 StrategyDispatcher 调度。
"""

import logging
from typing import Dict, List, Any

from ...strategy.base_strategy import (
    BaseStrategy,
    StrategyResult,
    TradingConditionResult,
)


class StrategyDispatcher:
    """统一策略调度器

    负责：
    - 注册和管理策略实例
    - 对单只/多只股票执行所有已注册策略
    - 汇总各策略产生的信号
    """

    def __init__(self):
        self._strategies: List[BaseStrategy] = []

    # ==================== 注册 ====================

    def register(self, strategy: BaseStrategy) -> None:
        """注册一个策略实例"""
        self._strategies.append(strategy)
        logging.debug(f"策略调度器已注册策略: {strategy.name}")

    @property
    def strategies(self) -> List[BaseStrategy]:
        """已注册的策略列表（只读）"""
        return list(self._strategies)

    @property
    def count(self) -> int:
        """已注册策略数量"""
        return len(self._strategies)

    # ==================== 调度：check_signals 接口 ====================

    def dispatch(
        self,
        stock_code: str,
        quote_data: Dict[str, Any],
        kline_data: List[Dict[str, Any]],
    ) -> List[StrategyResult]:
        """对单只股票执行所有已注册策略（check_signals 接口）

        按注册顺序依次执行，单个策略异常不影响其他策略。

        Args:
            stock_code: 股票代码
            quote_data: 实时报价数据
            kline_data: K线数据列表

        Returns:
            各策略的 StrategyResult 列表，顺序与注册顺序一致
        """
        results: List[StrategyResult] = []
        for strategy in self._strategies:
            try:
                result = strategy.check_signals(stock_code, quote_data, kline_data)
                result.strategy_data['strategy_name'] = strategy.name
                results.append(result)
            except Exception as e:
                logging.error(f"策略 {strategy.name} 执行失败: {e}")
                # 异常策略返回空结果
                results.append(StrategyResult(
                    stock_code=stock_code,
                    buy_reason=f"策略执行异常: {e}",
                    sell_reason=f"策略执行异常: {e}",
                ))
        return results

    def dispatch_batch(
        self,
        stocks_data: List[tuple],
    ) -> Dict[str, List[StrategyResult]]:
        """批量执行策略检测（check_signals 接口）

        Args:
            stocks_data: [(stock_code, quote_data, kline_data), ...]

        Returns:
            {stock_code: [StrategyResult, ...]}
        """
        all_results: Dict[str, List[StrategyResult]] = {}
        for stock_code, quote_data, kline_data in stocks_data:
            all_results[stock_code] = self.dispatch(stock_code, quote_data, kline_data)
        return all_results

    # ==================== 调度：check_stock_conditions 接口 ====================

    def dispatch_conditions(
        self,
        enhanced_stock: tuple,
    ) -> List[TradingConditionResult]:
        """对单只股票执行所有已注册策略（check_stock_conditions 接口）

        适用于 TradeService.auto_trade() 等使用 enhanced_stock 元组的场景。

        Args:
            enhanced_stock: 股票数据元组
                (id, code, name, price, change_pct, volume, high, low, open, plate_name)

        Returns:
            各策略的 TradingConditionResult 列表，顺序与注册顺序一致
        """
        results: List[TradingConditionResult] = []
        code = enhanced_stock[1] if len(enhanced_stock) > 1 else "unknown"

        for strategy in self._strategies:
            try:
                result = strategy.check_stock_conditions(enhanced_stock)
                results.append(result)
            except Exception as e:
                logging.error(f"策略 {strategy.name} 条件检查失败({code}): {e}")
                results.append(TradingConditionResult(
                    stock_code=code,
                    strategy_name=strategy.name,
                    reason=f"策略执行异常: {e}",
                ))
        return results

    def get_max_required_kline_days(self) -> int:
        """获取所有已注册策略中最大的K线天数需求"""
        if not self._strategies:
            return 30  # 默认值
        return max(s.get_required_kline_days() for s in self._strategies)
