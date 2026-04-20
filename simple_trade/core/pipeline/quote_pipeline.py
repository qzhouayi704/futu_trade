#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行情处理管道 - 报价获取与监控逻辑分离

提供两个独立周期：
- run_quote_cycle(): 报价获取 + 缓存更新 + 广播（系统启动即运行）
- run_monitoring_cycle(): 价格监控 + 策略检测 + 信号追踪（仅监控启动后运行）
"""

import logging
import asyncio
from typing import List, Dict, Tuple
from ...utils.logger import get_flow_logger

from .pipeline_broadcast import PipelineBroadcast


class QuotePipeline:
    """统一行情处理管道"""

    def __init__(
        self,
        container,
        socket_manager,
        state_manager,
        risk_coordinator=None,
        price_monitor=None,
        strategy_monitor=None,
        # A6: 显式依赖注入（逐步替代 container.xxx）
        subscription_manager=None,
        stock_data_service=None,
        alert_service=None,
        kline_service=None,
    ):
        """
        初始化行情管道

        Args:
            container: 服务容器（逐步废弃，仅用于向后兼容）
            socket_manager: WebSocket管理器
            state_manager: 状态管理器
            risk_coordinator: 风控协调器（可选）
            price_monitor: 价格监控服务（可选）
            strategy_monitor: 策略监控服务（可选）
            subscription_manager: 订阅管理器（显式注入）
            stock_data_service: 股票数据服务（显式注入）
            alert_service: 告警服务（显式注入）
            kline_service: K线服务（显式注入）
        """
        self.container = container
        self.socket_manager = socket_manager
        self.state_manager = state_manager

        # 显式依赖注入
        self.risk_coordinator = risk_coordinator
        self.price_monitor = price_monitor
        self.strategy_monitor = strategy_monitor

        # A6: 新增显式依赖（优先使用，fallback 到 container）
        self.subscription_manager = subscription_manager or getattr(container, 'subscription_manager', None)
        self.stock_data_service = stock_data_service or getattr(container, 'stock_data_service', None)
        self.alert_service = alert_service or getattr(container, 'alert_service', None)
        self.kline_service = kline_service or getattr(container, 'kline_service', None)

        self.push_interval = 10
        self.strategy_check_interval = 60
        self._loop_count = 0
        self.signal_tracker = None
        # 异步任务引用（防止 GC 回收和异常丢失）
        self._pending_tasks: set = set()

        # 广播处理器（提取的广播和状态更新逻辑）
        self._broadcaster = PipelineBroadcast(
            container, socket_manager, state_manager,
            alert_service=self.alert_service,
            kline_service=self.kline_service
        )

        if container.config:
            self.push_interval = getattr(container.config, 'quote_push_interval', 5)
            self.strategy_check_interval = getattr(
                container.config, 'strategy_check_interval', 60
            )

        self._init_signal_tracker()

    async def run_quote_cycle(self) -> List[Dict]:
        """报价获取周期 - 系统启动即运行，不依赖监控

        获取实时报价 → 更新缓存 → 广播报价数据。

        Returns:
            获取到的报价列表，无数据时返回空列表
        """
        self._loop_count += 1

        quotes = await self._fetch_quotes()
        if not quotes:
            return []

        self.state_manager.update_quotes_cache(quotes)

        # 更新全局报价缓存（供板块热度等消费方使用）
        quote_cache = getattr(self.container, 'quote_cache', None)
        if quote_cache:
            quote_cache.update_from_quotes(quotes)

        await self._broadcaster.broadcast(quotes, [], [])
        self.state_manager.set_last_update()

        if self._loop_count % 12 == 1:
            logging.debug(f"【报价周期】第 {self._loop_count} 次，{len(quotes)} 只股票")

        return quotes

    async def run_monitoring_cycle(self, quotes: List[Dict]):
        """监控周期 - 仅在监控启动后运行

        价格监控 → 策略检测 → 信号追踪 → 广播信号。

        Args:
            quotes: 报价数据列表（从 QuoteCache 获取）
        """
        if not quotes:
            return

        await self._check_price_triggers(quotes)

        # 日内高抛低吸信号检查（仅持仓股）
        intraday_signals = await self._check_intraday_profit(quotes)

        trade_actions: List[Dict] = []
        trade_actions.extend(intraday_signals)
        conditions: List[Dict] = []
        conditions_updated = False
        if self._should_run_strategy():
            trade_actions_strategy, conditions = await self._run_strategy_detection(quotes)
            trade_actions.extend(trade_actions_strategy)
            conditions_updated = True
            self._start_signal_tracking(trade_actions_strategy)

        await self._update_signal_tracking(quotes)

        if trade_actions:
            flow = get_flow_logger("策略信号")
            for a in trade_actions:
                flow.step(f"{a['signal_type']} {a['stock_code']}",
                          price=a['price'], reason=a.get('reason', '')[:40])
            flow.end(signals=len(trade_actions))
            # 异步发送企业微信通知（不阻塞管道）
            self._notify_trade_signals(trade_actions)

        if trade_actions or conditions or conditions_updated:
            await self._broadcaster.broadcast(quotes, trade_actions, conditions)

    async def run_pipeline(self):
        """执行完整管道（兼容方法，内部调用两个独立周期）"""
        quotes = await self.run_quote_cycle()
        await self.run_monitoring_cycle(quotes)

    def _should_run_strategy(self) -> bool:
        """判断是否应该执行策略条件检测（与 auto_trade 开关解耦，条件展示始终可用）

        启动预热期（前 180 秒 / 36 个循环）跳过策略检测，
        避免 fetch_kline 与 Scalping 订阅/CentralScheduler 同时竞争 OpenD 资源。
        """
        # 启动预热：前 36 个周期 (约 180 秒) 不执行策略，等 OpenD 稳定
        warmup_cycles = max(1, 180 // self.push_interval)
        if self._loop_count <= warmup_cycles:
            if self._loop_count == 1:
                logging.info(
                    f"【策略预热】跳过前 {warmup_cycles} 个周期的策略检测 "
                    f"(约 {warmup_cycles * self.push_interval} 秒)，等待 OpenD 稳定"
                )
            return False

        cycles = max(1, self.strategy_check_interval // self.push_interval)
        return cycles == 1 or self._loop_count % cycles == 1

    def _get_target_stocks(self) -> List[Dict]:
        """获取已订阅的目标股票列表"""
        subscribed_codes = self.subscription_manager.subscribed_stocks
        if not subscribed_codes:
            return []
        stock_pool_data = self.state_manager.get_stock_pool()
        return [s for s in stock_pool_data['stocks'] if s['code'] in subscribed_codes]

    async def _fetch_quotes(self) -> List[Dict]:
        """获取实时报价（唯一的报价获取点，含重试）"""
        target_stocks = self._get_target_stocks()
        if not target_stocks:
            logging.debug("没有订阅股票，跳过本次管道执行")
            return []

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    self.stock_data_service.get_real_quotes_from_subscribed,
                    target_stocks
                )
                if result:
                    return result
                # 返回空但没有异常，不重试
                return []
            except Exception as e:
                if attempt < max_retries:
                    backoff = 0.5 * (2 ** attempt)  # 0.5s, 1.0s
                    logging.warning(
                        f"【行情管道】获取报价失败(第{attempt+1}次)，{backoff}s后重试: {e}"
                    )
                    await asyncio.sleep(backoff)
                else:
                    logging.error(f"【行情管道】获取报价异常({max_retries+1}次均失败): {e}")
        return []

    async def _run_in_executor(self, func, *args):
        """在线程池中执行同步方法的通用包装"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, func, *args)

    async def _check_price_triggers(self, quotes: List[Dict]):
        """检查价格触发条件（委托给 RiskCoordinator 统一协调）"""
        try:
            if self.risk_coordinator:
                # 获取持仓信息供动态止损和策略止损使用
                positions = await self._get_positions_dict()
                await self._run_in_executor(
                    self.risk_coordinator.check_all_risks, quotes, positions
                )
            else:
                await self._check_price_triggers_legacy(quotes)
        except Exception as e:
            logging.error(f"【行情管道】检查价格触发条件异常: {e}", exc_info=True)


    async def _get_positions_dict(self) -> dict:
        """获取持仓信息字典 {stock_code: position_info}"""
        try:
            futu_trade = getattr(self.container, 'futu_trade_service', None)
            if not futu_trade:
                return {}
            result = await self._run_in_executor(futu_trade.get_positions)
            if result and result.get('success'):
                return {
                    pos['stock_code']: pos
                    for pos in result.get('positions', [])
                    if pos.get('qty', 0) > 0
                }
        except Exception as e:
            logging.debug(f"获取持仓信息失败: {e}")
        return {}

    async def _check_price_triggers_legacy(self, quotes: List[Dict]):
        """降级方案：RiskCoordinator 不可用时直接调用各服务"""
        if self.price_monitor:
            await self._run_in_executor(self.price_monitor.check_prices, quotes)
        # 其他监控服务可以通过container访问（保持向后兼容）
        svc = self.container
        if getattr(svc, 'lot_take_profit_service', None):
            await self._run_in_executor(svc.lot_take_profit_service.check_prices, quotes)
        if getattr(svc, 'lot_order_take_profit_service', None):
            await self._run_in_executor(svc.lot_order_take_profit_service.check_prices, quotes)
            await self._run_in_executor(svc.lot_order_take_profit_service.check_triggered_orders)

    async def _check_intraday_profit(self, quotes: List[Dict]) -> List[Dict]:
        """检查日内高抛低吸信号（仅持仓股）"""
        taker = getattr(self.container, 'intraday_profit_taker', None)
        if not taker:
            return []
        try:
            positions = await self._get_positions_dict()
            if not positions:
                return []
            return await self._run_in_executor(taker.check, quotes, positions)
        except Exception as e:
            logging.debug(f"日内高抛低吸检查异常: {e}")
            return []

    async def _run_strategy_detection(self, quotes: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """执行策略检测（自动交易 + 多策略信号），返回 (trade_actions, conditions)"""
        trade_actions: List[Dict] = []
        conditions: List[Dict] = []

        try:
            target_stocks = self._get_target_stocks()
            stock_pool = [
                {
                    'id': s.get('id', 0), 'code': s['code'], 'name': s['name'],
                    'market': s['market'], 'plate_name': s.get('plate_name', '')
                }
                for s in target_stocks
            ]

            auto_trade_result = await self._run_in_executor(
                self.container.trade_service.auto_trade, stock_pool
            )

            trade_actions = auto_trade_result['trade_actions']
            conditions_data = auto_trade_result['conditions_data']

            for action in trade_actions:
                conditions.append({
                    'stock_code': action['stock_code'],
                    'stock_name': action['stock_name'],
                    'signal_type': action['signal_type'],
                    'condition_text': action['message'],
                    'timestamp': action['timestamp'],
                    'price': action['price'],
                    'reason': action['reason']
                })

            self._broadcaster.update_trading_conditions(conditions_data)
            self._broadcaster.update_trade_signals(trade_actions, quotes)

        except Exception as e:
            logging.error(f"【行情管道】策略检测异常: {e}", exc_info=True)

        # 多策略并行信号检测
        await self._run_multi_strategy_detection(quotes)

        return trade_actions, conditions

    async def _run_multi_strategy_detection(self, quotes: List[Dict]):
        """执行多策略并行信号检测，将分组信号存储到 state"""
        if not self.strategy_monitor:
            return
        try:
            kline_data = self.state_manager.get_kline_cache() if hasattr(
                self.state_manager, 'get_kline_cache') else {}
            signals_by_strategy = await self._run_in_executor(
                self.strategy_monitor.check_signals_all, quotes, kline_data
            )
            self.state_manager.set_signals_by_strategy(signals_by_strategy)
        except Exception as e:
            logging.error(f"【行情管道】多策略信号检测异常: {e}")


    def _notify_trade_signals(self, trade_actions: List[Dict]):
        """异步发送交易信号的企业微信通知（保存 task 引用）"""
        wechat = getattr(self.container, 'wechat_alert_service', None)
        if not wechat or not wechat.enabled:
            return
        for action in trade_actions:
            task = asyncio.create_task(
                wechat.alert_trade_signal(
                    stock_code=action['stock_code'],
                    signal_type=action['signal_type'],
                    price=action['price'],
                    reason=action.get('reason', ''),
                )
            )
            self._pending_tasks.add(task)
            task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task):
        """异步任务完成回调：移除引用 + 记录异常"""
        self._pending_tasks.discard(task)
        if not task.cancelled() and task.exception():
            logging.error(
                f"企业微信通知任务异常: {task.exception()}",
                exc_info=task.exception()
            )

    def _init_signal_tracker(self):
        """初始化信号追踪器"""
        try:
            if getattr(self.container, 'signal_tracker', None):
                self.signal_tracker = self.container.signal_tracker
            elif getattr(self.container, 'db_manager', None):
                from ...services.strategy.signal_tracker import SignalTracker
                self.signal_tracker = SignalTracker(self.container.db_manager)
                logging.info("行情管道已初始化信号追踪器")
        except Exception as e:
            logging.warning(f"信号追踪器初始化失败，追踪功能不可用: {e}")

    def _start_signal_tracking(self, trade_actions: List[Dict]):
        """为新产生的信号启动追踪"""
        if not self.signal_tracker or not trade_actions:
            return
        for action in trade_actions:
            signal_id = action.get('signal_id')
            if not signal_id:
                continue
            try:
                self.signal_tracker.start_tracking(
                    signal_id=signal_id,
                    stock_code=action['stock_code'],
                    signal_type=action['signal_type'],
                    signal_price=action['price'],
                    strategy_id=action.get('strategy_id'),
                )
            except Exception as e:
                logging.error(f"启动信号追踪失败 {signal_id}: {e}")

    async def _update_signal_tracking(self, quotes: List[Dict]):
        """更新所有活跃信号的追踪数据"""
        if not self.signal_tracker:
            return
        try:
            if hasattr(self.signal_tracker, 'async_update_tracking'):
                await self.signal_tracker.async_update_tracking(quotes)
            else:
                await self._run_in_executor(self.signal_tracker.update_tracking, quotes)
        except Exception as e:
            logging.error(f"更新信号追踪失败: {e}")
