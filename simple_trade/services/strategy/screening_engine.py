#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略筛选引擎

职责：
- 通过 StrategyDispatcher 执行所有已注册策略
- 信号检测和条件匹配
- 持仓止损检查（委托给 PositionStopLossChecker）
- 生成筛选结果
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from ...database.core.db_manager import DatabaseManager
from ...core.coordination.strategy_dispatcher import StrategyDispatcher
from .position_stop_loss import PositionStopLossChecker, StopLossParams


@dataclass
class ScreeningResult:
    """筛选结果"""
    stock_code: str
    stock_name: str
    plate_name: str
    signal_type: str  # BUY / SELL / NONE
    signal_reason: str
    strategy_name: str
    strategy_data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'plate_name': self.plate_name,
            'signal_type': self.signal_type,
            'signal_reason': self.signal_reason,
            'strategy_name': self.strategy_name,
            'strategy_data': self.strategy_data,
            'timestamp': self.timestamp
        }


class ScreeningEngine:
    """
    策略筛选引擎

    负责执行具体的策略筛选逻辑，包括：
    1. 通过 StrategyDispatcher 执行所有已注册策略
    2. 合并多策略结果，取最强信号
    3. 持仓止损检查（委托给 PositionStopLossChecker）
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        strategy_dispatcher: StrategyDispatcher,
        stop_loss_params: StopLossParams = None,
    ):
        self.db_manager = db_manager
        self.strategy_dispatcher = strategy_dispatcher
        self.stop_loss_checker = PositionStopLossChecker(
            db_manager, stop_loss_params
        )
        logging.info("策略筛选引擎初始化完成")

    def screen_single_stock(
        self,
        quote: Dict[str, Any],
        position_info: Optional[Dict[str, Any]] = None
    ) -> ScreeningResult:
        """
        筛选单只股票

        Args:
            quote: 实时报价数据
            position_info: 持仓信息（包含成本价），可选

        Returns:
            筛选结果
        """
        stock_code = quote.get('code', '')

        # 构建股票数据元组（与策略期望的格式匹配）
        stock_data = (
            quote.get('id', 0),
            stock_code,
            quote.get('name', ''),
            quote.get('last_price', 0),
            quote.get('change_percent', 0),
            quote.get('volume', 0),
            quote.get('high_price', 0),
            quote.get('low_price', 0),
            quote.get('open_price', 0),
            quote.get('plate_name', '')
        )

        # 通过调度器执行所有已注册策略
        condition_results = self.strategy_dispatcher.dispatch_conditions(stock_data)

        # 合并多策略结果：取最强信号
        signal_type, signal_reason, strategy_name, strategy_data = (
            self._merge_condition_results(condition_results)
        )

        # 对于持仓股票，检查趋势未延续止损
        if signal_type == 'NONE' and position_info:
            stop_loss_result = self.stop_loss_checker.check(
                stock_code, quote, position_info
            )
            if stop_loss_result.get('should_stop_loss', False):
                signal_type = 'SELL'
                signal_reason = stop_loss_result.get('reason', '趋势未延续止损')
                strategy_data['stop_loss_check'] = stop_loss_result

        return ScreeningResult(
            stock_code=stock_code,
            stock_name=quote.get('name', ''),
            plate_name=quote.get('plate_name', ''),
            signal_type=signal_type,
            signal_reason=signal_reason,
            strategy_name=strategy_name,
            strategy_data=strategy_data,
        )

    @staticmethod
    def _merge_condition_results(
        results: list,
    ) -> tuple:
        """合并多策略条件检查结果

        冲突检测逻辑：
        - 同时存在 BUY 和 SELL 时，按信号强度决定
        - 强度差距 < 0.2 → 标记为 CONFLICT，建议观望
        - 强度差距 >= 0.2 → 取强者

        Returns:
            (signal_type, signal_reason, strategy_name, strategy_data)
        """
        buy_results = []
        sell_results = []

        for cr in results:
            if getattr(cr, 'buy_signal', False):
                buy_results.append(cr)
            elif getattr(cr, 'sell_signal', False):
                sell_results.append(cr)

        # 冲突检测：同时存在 BUY 和 SELL
        if buy_results and sell_results:
            return ScreeningEngine._resolve_conflict(buy_results, sell_results)

        # 无冲突：取最强信号
        if buy_results:
            cr = buy_results[0]
            return (
                'BUY',
                getattr(cr, 'reason', ''),
                getattr(cr, 'strategy_name', ''),
                getattr(cr, 'strategy_data', {}),
            )

        if sell_results:
            cr = sell_results[0]
            return (
                'SELL',
                getattr(cr, 'reason', ''),
                getattr(cr, 'strategy_name', ''),
                getattr(cr, 'strategy_data', {}),
            )

        # 无信号
        if results:
            first = results[0]
            return (
                'NONE',
                getattr(first, 'reason', ''),
                getattr(first, 'strategy_name', ''),
                getattr(first, 'strategy_data', {}),
            )
        return 'NONE', '', '', {}

    @staticmethod
    def _resolve_conflict(buy_results: list, sell_results: list) -> tuple:
        """解决 BUY/SELL 信号冲突"""
        def _get_strength(cr) -> float:
            sr = getattr(cr, 'strategy_result', None)
            return sr.signal_strength if sr else 0

        best_buy = max(buy_results, key=_get_strength)
        best_sell = max(sell_results, key=_get_strength)
        buy_strength = _get_strength(best_buy)
        sell_strength = _get_strength(best_sell)

        # 强度差距 < 0.2 → 冲突，建议观望
        if abs(buy_strength - sell_strength) < 0.2:
            return (
                'CONFLICT',
                f'多策略信号冲突(买{buy_strength:.2f}/卖{sell_strength:.2f})，建议观望',
                '',
                {
                    'conflict': True,
                    'buy_strength': buy_strength,
                    'sell_strength': sell_strength,
                },
            )

        # 强度差距 >= 0.2 → 取强者
        if buy_strength > sell_strength:
            cr = best_buy
            signal_type = 'BUY'
        else:
            cr = best_sell
            signal_type = 'SELL'

        return (
            signal_type,
            getattr(cr, 'reason', ''),
            getattr(cr, 'strategy_name', ''),
            getattr(cr, 'strategy_data', {}),
        )

    def check_position_stop_loss(
        self,
        stock_code: str,
        quote: Dict[str, Any],
        position_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """检查持仓止损（向后兼容接口，委托给 PositionStopLossChecker）"""
        return self.stop_loss_checker.check(stock_code, quote, position_info)
