#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险管理协调器

统一调度所有止盈止损检查，按优先级去重，避免同一只股票被多个模块重复触发卖出。

协调的模块（按优先级）：
1. PriceMonitorService - 价格监控任务（目标价买卖）  urgency=9
2. DynamicStopLossStrategy - 动态止损（市场环境驱动） urgency=8
3. LotTakeProfitService - 分仓止盈                   urgency=7
4. LotOrderTakeProfitService - 单笔订单止盈           urgency=6
5. ScreeningEngine - 策略趋势止损                     urgency=5
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class RiskDecision:
    """统一的风险决策结果"""
    stock_code: str
    action: str          # PRICE_MONITOR / DYNAMIC_STOP_LOSS / LOT_TAKE_PROFIT / ...
    source: str          # 决策来源模块名称
    urgency: int = 5     # 紧急程度 0-10
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'stock_code': self.stock_code,
            'action': self.action,
            'source': self.source,
            'urgency': self.urgency,
            'details': self.details,
        }


class RiskCoordinator:
    """
    风险管理协调器

    统一调度所有止盈止损检查模块，确保：
    1. 同一只股票不会被多个模块重复触发卖出
    2. 按优先级执行检查（价格监控 > 动态止损 > 分仓止盈 > 单笔订单止盈 > 策略止损）
    3. 集中记录所有风险决策日志
    4. 非价格监控模块有频率控制，避免高频重复检查
    """

    # 非价格监控模块的最小检查间隔（秒）
    _MIN_CHECK_INTERVAL: float = 10.0

    def __init__(
        self,
        price_monitor_service=None,
        lot_take_profit_service=None,
        lot_order_take_profit_service=None,
        dynamic_stop_loss_strategy=None,
        screening_engine=None,
    ):
        self.price_monitor_service = price_monitor_service
        self.lot_tp_service = lot_take_profit_service
        self.lot_order_tp_service = lot_order_take_profit_service
        self.dynamic_stop_loss = dynamic_stop_loss_strategy
        self.screening_engine = screening_engine
        self.logger = logging.getLogger(__name__)

        # 频率控制：stock_code -> 上次检查时间戳（仅用于非价格监控模块）
        self._last_check_time: Dict[str, float] = {}

    def check_all_risks(
        self,
        quotes: List[Dict[str, Any]],
        positions: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[RiskDecision]:
        """
        统一检查所有风险条件。

        执行顺序（按优先级）：
        1. 价格监控（用户手动设置的目标价）     urgency=9
        2. 动态止损（市场环境驱动）             urgency=8
        3. 分仓止盈（FIFO 仓位止盈）           urgency=7
        4. 单笔订单止盈（deal 级别止盈）        urgency=6
        5. 策略趋势止损（趋势未延续止损）       urgency=5

        同一只股票如果已被高优先级模块触发卖出，低优先级模块将跳过。

        Args:
            quotes: 实时报价列表
            positions: 持仓信息字典 {stock_code: position_info}，可选

        Returns:
            所有触发的风险决策列表
        """
        if not quotes:
            return []

        decisions: List[RiskDecision] = []
        triggered_stocks: set = set()

        # 1. 价格监控（最高优先级 - 用户手动设置，不受频率限制）
        self._check_price_monitor(quotes, decisions, triggered_stocks)

        # 2. 动态止损（市场环境驱动）
        self._check_dynamic_stop_loss(quotes, positions, decisions, triggered_stocks)

        # 3. 分仓止盈
        self._check_lot_take_profit(quotes, decisions, triggered_stocks)

        # 4. 单笔订单止盈 + 已触发订单成交检查
        self._check_lot_order_take_profit(quotes, decisions, triggered_stocks)

        # 5. 策略趋势止损
        self._check_strategy_stop_loss(quotes, positions, decisions, triggered_stocks)

        if decisions:
            self.logger.info(
                f"【风险协调】本轮触发 {len(decisions)} 个决策，"
                f"涉及 {len(triggered_stocks)} 只股票"
            )

        return decisions

    def _should_skip_check(self, stock_code: str) -> bool:
        """频率控制：非价格监控模块跳过最近 N 秒内已检查过的股票"""
        now = time.time()
        last_time = self._last_check_time.get(stock_code, 0)
        if now - last_time < self._MIN_CHECK_INTERVAL:
            return True
        self._last_check_time[stock_code] = now
        return False

    def _check_price_monitor(
        self,
        quotes: List[Dict[str, Any]],
        decisions: List[RiskDecision],
        triggered_stocks: set,
    ):
        """执行价格监控检查（不受频率限制）"""
        if not self.price_monitor_service:
            return
        try:
            results = self.price_monitor_service.check_prices(quotes)
            for r in results:
                code = r.get('stock_code', '')
                if code and code not in triggered_stocks:
                    triggered_stocks.add(code)
                    decisions.append(RiskDecision(
                        stock_code=code,
                        action='PRICE_MONITOR',
                        source='PriceMonitorService',
                        urgency=9,
                        details=r,
                    ))
        except Exception as e:
            self.logger.error(f"【风险协调】价格监控检查异常: {e}", exc_info=True)

    def _check_dynamic_stop_loss(
        self,
        quotes: List[Dict[str, Any]],
        positions: Optional[Dict[str, Dict[str, Any]]],
        decisions: List[RiskDecision],
        triggered_stocks: set,
    ):
        """执行动态止损检查（仅对持仓股票）"""
        if not self.dynamic_stop_loss or not positions:
            return
        try:
            for quote in quotes:
                code = quote.get('code', '')
                if not code or code in triggered_stocks:
                    continue
                if code not in positions:
                    continue
                if self._should_skip_check(code):
                    continue

                pos = positions[code]
                cost_price = pos.get('cost_price', 0)
                current_price = quote.get('last_price', 0)
                if cost_price <= 0 or current_price <= 0:
                    continue

                # 计算当前收益率
                return_pct = ((current_price - cost_price) / cost_price) * 100

                # 获取动态风险配置
                from .dynamic_stop_loss import MarketContext
                context = MarketContext(
                    turnover_rate=quote.get('turnover_rate', 0.0),
                )
                risk_config = self.dynamic_stop_loss.calculate_dynamic_risk_config(
                    code, context=None  # 让它自动构建完整上下文
                )

                # 检查是否触发动态止损
                if return_pct <= risk_config.fixed_stop_loss_pct:
                    triggered_stocks.add(code)
                    decisions.append(RiskDecision(
                        stock_code=code,
                        action='DYNAMIC_STOP_LOSS',
                        source='DynamicStopLossStrategy',
                        urgency=8,
                        details={
                            'stock_code': code,
                            'cost_price': cost_price,
                            'current_price': current_price,
                            'return_pct': round(return_pct, 2),
                            'stop_loss_pct': risk_config.fixed_stop_loss_pct,
                            'reason': (
                                f"动态止损触发: 收益{return_pct:.1f}% "
                                f"<= 止损线{risk_config.fixed_stop_loss_pct}%"
                            ),
                        },
                    ))
        except Exception as e:
            self.logger.error(f"【风险协调】动态止损检查异常: {e}", exc_info=True)

    def _check_lot_take_profit(
        self,
        quotes: List[Dict[str, Any]],
        decisions: List[RiskDecision],
        triggered_stocks: set,
    ):
        """执行分仓止盈检查"""
        if not self.lot_tp_service:
            return
        try:
            results = self.lot_tp_service.check_prices(quotes)
            for r in results:
                code = r.get('stock_code', '')
                if code and code not in triggered_stocks:
                    triggered_stocks.add(code)
                    decisions.append(RiskDecision(
                        stock_code=code,
                        action='LOT_TAKE_PROFIT',
                        source='LotTakeProfitService',
                        urgency=7,
                        details=r,
                    ))
        except Exception as e:
            self.logger.error(f"【风险协调】分仓止盈检查异常: {e}", exc_info=True)

    def _check_lot_order_take_profit(
        self,
        quotes: List[Dict[str, Any]],
        decisions: List[RiskDecision],
        triggered_stocks: set,
    ):
        """执行单笔订单止盈检查 + 已触发订单成交确认"""
        if not self.lot_order_tp_service:
            return
        try:
            # 价格触发检查（仅对未被高优先级触发的股票）
            filtered_quotes = [
                q for q in quotes
                if q.get('code', '') not in triggered_stocks
            ]
            if filtered_quotes:
                results = self.lot_order_tp_service.check_prices(filtered_quotes)
                for r in results:
                    code = r.get('stock_code', '')
                    if code:
                        triggered_stocks.add(code)
                        decisions.append(RiskDecision(
                            stock_code=code,
                            action='LOT_ORDER_TAKE_PROFIT',
                            source='LotOrderTakeProfitService',
                            urgency=6,
                            details=r,
                        ))

            # 已触发订单的成交确认（不受去重限制，必须执行）
            self.lot_order_tp_service.check_triggered_orders()

        except Exception as e:
            self.logger.error(f"【风险协调】单笔订单止盈检查异常: {e}", exc_info=True)

    def _check_strategy_stop_loss(
        self,
        quotes: List[Dict[str, Any]],
        positions: Optional[Dict[str, Dict[str, Any]]],
        decisions: List[RiskDecision],
        triggered_stocks: set,
    ):
        """执行策略趋势止损检查（最低优先级，仅对持仓股票）"""
        if not self.screening_engine or not positions:
            return
        try:
            for quote in quotes:
                code = quote.get('code', '')
                if not code or code in triggered_stocks:
                    continue
                if code not in positions:
                    continue
                if self._should_skip_check(code):
                    continue

                pos = positions[code]
                stop_result = self.screening_engine.check_position_stop_loss(
                    code, quote, pos
                )
                if stop_result.get('should_stop_loss', False):
                    triggered_stocks.add(code)
                    decisions.append(RiskDecision(
                        stock_code=code,
                        action='STRATEGY_STOP_LOSS',
                        source='ScreeningEngine',
                        urgency=5,
                        details={
                            'stock_code': code,
                            'reason': stop_result.get('reason', '策略趋势止损'),
                            **stop_result,
                        },
                    ))
        except Exception as e:
            self.logger.error(f"【风险协调】策略趋势止损检查异常: {e}", exc_info=True)
