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

from ....utils import env_flag


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

        # 移动止盈：追踪每只持仓股的峰值价格
        self._peak_prices: Dict[str, float] = {}  # stock_code -> peak_price

        # 移动止盈参数
        self._TRAILING_ACTIVATE_PCT = 5.0   # 默认：涨超5%后激活移动止盈
        self._TRAILING_STOP_PCT = 3.0       # 默认：从峰值回撤3%卖出

        # Sniper驱动的移动止盈参数（回测验证: mega_buy后中位高点+2.89%）
        self._SNIPER_TRAILING_STOP_PCT = 2.5      # mega_buy激活: 回撤2.5%卖出
        self._SNIPER_CONSECUTIVE_STOP_PCT = 3.0   # 连续mega_buy: 放宽到3.0%
        self._sniper_activated: Dict[str, dict] = {}  # stock_code -> {activated_at, mega_buy_count}

        # 已触发订单成交确认的频率控制（30秒间隔 + 启动冷却）
        self._TRIGGERED_ORDER_CHECK_INTERVAL: float = 30.0
        # 初始化为当前时间：首次检查需等待一个完整间隔（启动冷却期）
        self._last_triggered_order_check: float = time.time()

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

        # 2.5 智能持仓管理（分批止盈 + ATR止损 + 趋势保护）
        self._check_smart_position(quotes, decisions, triggered_stocks)

        # 2.8 移动止盈（Trailing Stop）
        self._check_trailing_stop(quotes, positions, decisions, triggered_stocks)

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
                    liquidity_level=quote.get('liquidity_level', 'B'),
                    liquidity_score=quote.get('liquidity_score', 50.0),
                )
                risk_config = self.dynamic_stop_loss.calculate_dynamic_risk_config(
                    code, context=context
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

            # 已触发订单的成交确认（频率控制：每30秒检查一次，启动后10秒冷却）
            now = time.time()
            if now - self._last_triggered_order_check >= self._TRIGGERED_ORDER_CHECK_INTERVAL:
                self._last_triggered_order_check = now
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

    def on_sniper_signal(self, stock_code: str, signal_type: str):
        """接收Sniper信号，驱动移动止盈

        mega_buy: 激活移动止盈追踪（从当前价开始记录峰值）
        mega_sell: 标记立即止盈（下次检查时触发卖出）
        """
        if signal_type == 'mega_buy':
            if stock_code in self._sniper_activated:
                self._sniper_activated[stock_code]['mega_buy_count'] += 1
                self.logger.info(
                    f"【Sniper止盈】{stock_code} 连续mega_buy "
                    f"#{self._sniper_activated[stock_code]['mega_buy_count']} → 回撤放宽到{self._SNIPER_CONSECUTIVE_STOP_PCT}%"
                )
            else:
                self._sniper_activated[stock_code] = {
                    'activated_at': time.time(),
                    'mega_buy_count': 1,
                    'mega_sell': False,
                }
                self.logger.info(f"【Sniper止盈】{stock_code} mega_buy → 激活移动止盈追踪")

        elif signal_type == 'mega_sell':
            if stock_code in self._sniper_activated:
                self._sniper_activated[stock_code]['mega_sell'] = True
                self.logger.info(f"【Sniper止盈】{stock_code} mega_sell → 标记立即止盈")

    def _check_trailing_stop(
        self,
        quotes: List[Dict[str, Any]],
        positions: Optional[Dict[str, Dict[str, Any]]],
        decisions: List[RiskDecision],
        triggered_stocks: set,
    ):
        """移动止盈检查（Sniper增强版）

        双模式：
          Sniper模式: mega_buy激活 → 回撤2.5%卖出 / mega_sell → 立即卖出
          默认模式:   涨超5%激活 → 回撤3%卖出
        """
        if not positions:
            return
        try:
            # 清理不再持仓的记录
            held_codes = set(positions.keys())
            for code in list(self._peak_prices.keys()):
                if code not in held_codes:
                    del self._peak_prices[code]
            for code in list(self._sniper_activated.keys()):
                if code not in held_codes:
                    del self._sniper_activated[code]

            for quote in quotes:
                code = quote.get('code', '')
                if not code or code in triggered_stocks or code not in positions:
                    continue

                pos = positions[code]
                cost_price = pos.get('cost_price', 0)
                current_price = quote.get('last_price', 0)
                if cost_price <= 0 or current_price <= 0:
                    continue

                # 更新峰值
                prev_peak = self._peak_prices.get(code, cost_price)
                if current_price > prev_peak:
                    self._peak_prices[code] = current_price
                    prev_peak = current_price

                peak_gain = (prev_peak / cost_price - 1) * 100
                drawdown = (1 - current_price / prev_peak) * 100 if prev_peak > 0 else 0
                current_gain = (current_price / cost_price - 1) * 100

                sniper_state = self._sniper_activated.get(code)

                # === Sniper模式: mega_sell立即止盈 ===
                if sniper_state and sniper_state.get('mega_sell'):
                    triggered_stocks.add(code)
                    decisions.append(RiskDecision(
                        stock_code=code,
                        action='TRAILING_STOP',
                        source='RiskCoordinator.SniperStop',
                        urgency=8,  # 高于默认移动止盈
                        details={
                            'stock_code': code,
                            'cost_price': cost_price,
                            'peak_price': round(prev_peak, 3),
                            'current_price': current_price,
                            'peak_gain_pct': round(peak_gain, 1),
                            'current_gain_pct': round(current_gain, 1),
                            'reason': (
                                f"Sniper止盈: mega_sell触发立即卖出 "
                                f"(当前{current_gain:+.1f}%)"
                            ),
                        },
                    ))
                    self.logger.info(
                        f"【Sniper止盈】{code} mega_sell → 立即卖出 "
                        f"当前{current_gain:+.1f}%"
                    )
                    continue

                # === Sniper模式: mega_buy激活的回撤止盈 ===
                if sniper_state and drawdown > 0:
                    buy_count = sniper_state.get('mega_buy_count', 1)
                    # 连续mega_buy放宽回撤
                    stop_pct = (self._SNIPER_CONSECUTIVE_STOP_PCT
                                if buy_count >= 2
                                else self._SNIPER_TRAILING_STOP_PCT)

                    if drawdown >= stop_pct:
                        triggered_stocks.add(code)
                        decisions.append(RiskDecision(
                            stock_code=code,
                            action='TRAILING_STOP',
                            source='RiskCoordinator.SniperStop',
                            urgency=7,
                            details={
                                'stock_code': code,
                                'cost_price': cost_price,
                                'peak_price': round(prev_peak, 3),
                                'current_price': current_price,
                                'peak_gain_pct': round(peak_gain, 1),
                                'drawdown_pct': round(drawdown, 1),
                                'current_gain_pct': round(current_gain, 1),
                                'mega_buy_count': buy_count,
                                'reason': (
                                    f"Sniper止盈: 峰值+{peak_gain:.1f}% "
                                    f"回撤{drawdown:.1f}%>={stop_pct}% "
                                    f"(mega_buy×{buy_count}, 当前{current_gain:+.1f}%)"
                                ),
                            },
                        ))
                        self.logger.info(
                            f"【Sniper止盈】{code} 峰值+{peak_gain:.1f}% "
                            f"回撤{drawdown:.1f}% >= {stop_pct}% → 卖出"
                        )
                        continue

                # === 默认模式: 涨超5%激活，回撤3%卖出 ===
                if peak_gain >= self._TRAILING_ACTIVATE_PCT and drawdown >= self._TRAILING_STOP_PCT:
                    triggered_stocks.add(code)
                    decisions.append(RiskDecision(
                        stock_code=code,
                        action='TRAILING_STOP',
                        source='RiskCoordinator.TrailingStop',
                        urgency=7,
                        details={
                            'stock_code': code,
                            'cost_price': cost_price,
                            'peak_price': round(prev_peak, 3),
                            'current_price': current_price,
                            'peak_gain_pct': round(peak_gain, 1),
                            'drawdown_pct': round(drawdown, 1),
                            'current_gain_pct': round(current_gain, 1),
                            'reason': (
                                f"移动止盈: 峰值+{peak_gain:.1f}% "
                                f"回撤{drawdown:.1f}% (当前+{current_gain:.1f}%)"
                            ),
                        },
                    ))
                    self.logger.info(
                        f"【移动止盈】{code} 峰值+{peak_gain:.1f}% "
                        f"回撤{drawdown:.1f}% → 触发卖出"
                    )

        except Exception as e:
            self.logger.error(f"【风险协调】移动止盈检查异常: {e}", exc_info=True)

    def _check_smart_position(
        self,
        quotes: List[Dict[str, Any]],
        decisions: List[RiskDecision],
        triggered_stocks: set,
    ):
        """
        智能持仓管理检查（分批止盈 + ATR止损 + 趋势保护）

        通过服务容器获取 SmartPositionManager，对已注册的持仓进行
        分批止盈和ATR自适应止损检查。urgency=7（介于动态止损和分仓止盈之间）
        """
        try:
            from ....dependencies import get_container
            try:
                container = get_container()
            except Exception:
                return

            mgr = container.smart_position_manager
            if not mgr:
                return

            active_positions = mgr.get_all_positions()
            if not active_positions:
                return

            for quote in quotes:
                code = quote.get('code', '')
                if code in triggered_stocks or code not in active_positions:
                    continue

                price = quote.get('last_price', 0)
                if price <= 0:
                    continue

                # 获取连续阴线数（从5分钟K线缓存，暂用0）
                consecutive_down = 0

                action = mgr.evaluate(code, price, consecutive_down)

                if action.action in ('SELL_PARTIAL', 'SELL_ALL'):
                    urgency = 8 if action.is_emergency else 7
                    decisions.append(RiskDecision(
                        stock_code=code,
                        action='SMART_POSITION_' + action.action,
                        source='SmartPositionManager',
                        urgency=urgency,
                        details={
                            'stock_code': code,
                            'reason': action.reason,
                            'qty_to_sell': action.qty_to_sell,
                            'is_emergency': action.is_emergency,
                        },
                    ))
                    if action.action == 'SELL_ALL':
                        triggered_stocks.add(code)
                    # 影子观察日志：SMART_POSITION 决策默认只记录不执行。
                    self.logger.info(
                        f"【智能持仓·影子】{code} {action.action} "
                        f"{action.qty_to_sell}股 — {action.reason}"
                    )
                    # 实盘执行：仅当 HYBRID_EXIT_LIVE 显式开启 且 该持仓为 hybrid profile 时真卖。
                    # 与 HYBRID_EXIT_ENABLED(买入侧登记)两段开关配合: 仅登记=影子, 两者都开=实盘。
                    if env_flag('HYBRID_EXIT_LIVE'):
                        self._execute_hybrid_sell(mgr, code, action, price)

        except Exception as e:
            self.logger.error(f"【风险协调】智能持仓检查异常: {e}", exc_info=True)

    def _execute_hybrid_sell(self, mgr, code: str, action, price: float):
        """实盘执行混合出场卖单(HYBRID_EXIT_LIVE 开启时)。

        安全约束: 只对 hybrid profile 持仓下单; SELL_PARTIAL 向下取整到该股真实整手
        (每手股数来自富途快照 lot_size, 取不到才回退100),
        SELL_ALL 卖全部剩余(含可能的碎股); 市价单(price=0); 报单成功后回写 remaining。
        任何异常都不向上抛(出场环不能因单只股票报错而中断)。
        """
        try:
            pos = mgr.get_position(code)
            if not pos or getattr(pos, 'exit_profile', 'standard') != 'hybrid':
                return  # 非 hybrid 持仓不在本实盘通道处理
            from ....dependencies import get_container
            fts = getattr(get_container(), 'futu_trade_service', None)
            if not fts or not fts.is_trade_ready():
                self.logger.warning(f"【混合出场·实盘】{code} 交易服务未就绪, 跳过")
                return
            qty = int(action.qty_to_sell or 0)
            if action.action == 'SELL_PARTIAL':
                from ...market_data.lot_size_provider import get_lot_size_provider
                qty = get_lot_size_provider().floor_to_lot(code, qty)  # 按该股每手取整
            if qty <= 0:
                return
            res = fts.order_manager.place_order(
                stock_code=code, trade_type='SELL', price=0, quantity=qty,
            )
            if res.get('success'):
                mgr.update_after_sell(code, qty)
                self.logger.info(
                    f"【混合出场·实盘】{code} 卖出{qty}股 "
                    f"order={res.get('futu_order_id')} — {action.reason}"
                )
            else:
                self.logger.warning(f"【混合出场·实盘】{code} 报单失败: {res.get('message')}")
        except Exception as e:
            self.logger.error(f"【混合出场·实盘】{code} 执行异常: {e}", exc_info=True)

