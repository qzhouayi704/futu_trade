#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行情处理管道 - 报价获取与监控逻辑分离

提供两个独立周期：
- run_quote_cycle(): 报价获取 + 缓存更新 + 广播（系统启动即运行）
- run_monitoring_cycle(): 价格监控 + 策略检测 + 信号追踪（仅监控启动后运行）
"""

import logging
import asyncio
import os
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from ...utils.logger import get_flow_logger

from .pipeline_broadcast import PipelineBroadcast
from .signal_arbitrator import SignalArbitrator

import re as _re

# 实时推送质量地板：非持仓买入若"流入不大/占日均过低/多日选股语"=低质噪声，源头不推企微
# （仍进 DB/前端）。置 False 即还原旧行为(可逆)。默认 OFF，治理器上线观察一节后再开。
REALTIME_QUALITY_FLOOR = False
_MARGINAL_OCCUPY_MAX = 1.5  # "占日均X%" 中 X 低于此值视为边际信号
_MARGINAL_OCCUPY_RE = _re.compile(r"占日均\s*([0-9.]+)\s*%")


def _is_marginal_signal(reason: str) -> bool:
    """判断一条买入 reason 是否为低质边际信号（用于实时推送降噪，不影响 DB/前端）。"""
    if not reason:
        return False
    if "流入不大" in reason:
        return True
    # 多日选股语：日频结果，非盘中可操作
    if ("连续" in reason and "日资金净流入" in reason) or "前日大涨" in reason:
        return True
    m = _MARGINAL_OCCUPY_RE.search(reason)
    if m:
        try:
            if float(m.group(1)) < _MARGINAL_OCCUPY_MAX:
                return True
        except ValueError:
            pass
    return False


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
        self._signal_arbitrator = SignalArbitrator()
        self.legacy_strategy_detection_enabled = self._legacy_strategy_detection_enabled(container)
        self._legacy_strategy_skipped_logged = False
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

    @staticmethod
    def _legacy_strategy_detection_enabled(container) -> bool:
        """Return whether the legacy BaseStrategy detector may run."""
        raw = os.getenv("ENABLE_LEGACY_STRATEGY")
        if raw is None:
            config = getattr(container, "config", None)
            raw = getattr(config, "enable_legacy_strategy", False) if config else False
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

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

        # P2-1: 仅在监控未启动时广播报价（监控启动时由 run_monitoring_cycle 统一广播，避免双重推送）
        if not self.state_manager.is_running():
            task = asyncio.create_task(self._broadcaster.broadcast(quotes, [], []))
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
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

        # 一次性获取持仓，避免各子函数重复调用 Futu API
        positions = await self._get_positions_dict()

        await self._check_price_triggers(quotes, positions)

        # 日内高抛低吸信号检查（仅持仓股）
        intraday_signals = await self._check_intraday_profit(quotes, positions)
        
        # 日内自动化防砸盘风控与真空区止盈（新增）
        risk_actions = await self._check_intraday_risks(quotes, positions)

        # 开盘持仓即时风险（持仓股专用·绕过策略预热盲区·仅用已取报价的昨收/开盘价/现价，
        # 零额外 OpenD 调用）：专治"开盘想卖却干等信号"——09:30 就能报低开/跌破昨收/高开低走。
        open_risk_actions = await self._check_open_risk(quotes, positions)
        # 开盘一次性"持仓检查"全仓快照（每个交易日一次，全绿也推，给确定答复而非沉默）
        await self._push_open_check_once(quotes, positions)

        # 信号检测/策略检测仅对"所属市场此刻真正在交易"的报价进行（每60s，每轮算一次共用）：
        # _should_run_strategy 用 is_any_market_trading（任意市场），美股时段(北京 21:30~04:00)
        # 也会放行，但监控池是港股、夜间只有昨收快照——不过滤就会拿陈旧数据反复触发
        # R2/R3/R10 等 SELL 规则、并让策略用昨收重跑，凌晨广播出"防守触发"等假信号。
        trading_quotes = self._filter_trading_quotes(quotes) if self._should_run_strategy() else []

        # 资金流向信号检查（与策略检测同频）
        flow_signals = []
        absorption_alerts = []
        if trading_quotes:
            flow_signals = await self._check_capital_flow_signals(trading_quotes, positions)
            absorption_alerts = await self._check_absorption(trading_quotes)

        trade_actions: List[Dict] = []
        trade_actions.extend(intraday_signals)
        trade_actions.extend(risk_actions)
        trade_actions.extend(open_risk_actions)
        trade_actions.extend(flow_signals)
        trade_actions.extend(absorption_alerts)

        # 日内波段卖后跟踪买回检查（每轮都检查，不受 strategy_check_interval 限制）
        swing_signals = await self._check_swing_buyback(quotes)
        trade_actions.extend(swing_signals)

        # 持仓做T助手（高抛低吸；每轮检查，绕开开新仓门卫；默认告警模式，开关在 system_config）
        t_trade_actions = await self._check_t_trade(quotes, positions)
        trade_actions.extend(t_trade_actions)

        # 将 R13 卖出信号送入卖后跟踪器
        self._feed_sell_signals_to_swing_tracker(flow_signals + intraday_signals)
        conditions: List[Dict] = []
        conditions_updated = False
        if trading_quotes:
            trade_actions_strategy, conditions = await self._run_strategy_detection(trading_quotes)
            trade_actions.extend(trade_actions_strategy)
            conditions_updated = True
            self._start_signal_tracking(trade_actions_strategy)

        await self._update_signal_tracking(quotes)

        if trade_actions:
            # === 信号一致性仲裁：消除矛盾信号 ===
            trade_actions = self._signal_arbitrator.arbitrate(trade_actions)

            flow = get_flow_logger("策略信号")
            for a in trade_actions:
                flow.step(f"{a['signal_type']} {a['stock_code']}",
                          price=a['price'], reason=a.get('reason', '')[:40])
            flow.end(signals=len(trade_actions))
            # 异步发送企业微信通知（不阻塞管道）
            self._notify_trade_signals(trade_actions, positions)

        # 始终广播报价（quote_cycle 在监控运行时不再广播，由此处统一负责）
        await self._broadcaster.broadcast(quotes, trade_actions, conditions)

    async def run_pipeline(self):
        """执行完整管道（兼容方法，内部调用两个独立周期）"""
        quotes = await self.run_quote_cycle()
        await self.run_monitoring_cycle(quotes)

    def _should_run_strategy(self) -> bool:
        """判断是否应该执行策略条件检测（与 auto_trade 开关解耦，条件展示始终可用）

        启动预热期（前 180 秒 / 36 个循环）跳过策略检测，
        避免 fetch_kline 与 CentralScheduler 同时竞争 OpenD 资源。
        非交易时段跳过策略检测，避免用陈旧数据反复产生无意义信号。
        """
        # 非交易时段守卫：无市场真正交易时跳过策略评估
        from ...utils.market_helper import MarketTimeHelper
        if not MarketTimeHelper.is_any_market_trading():
            return False

        # 启动预热：前 12 个周期 (约 60 秒) 不执行策略，等 OpenD 稳定
        warmup_cycles = max(1, 60 // self.push_interval)
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

    async def _check_price_triggers(self, quotes: List[Dict], positions: dict = None):
        """检查价格触发条件（委托给 RiskCoordinator 统一协调）"""
        try:
            if self.risk_coordinator:
                if positions is None:
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

    @staticmethod
    def _mins_since_hk_open() -> Optional[int]:
        """距港股 09:30 开盘的分钟数（服务器=北京时间=HK）。盘前为负、午后很大。"""
        try:
            from datetime import datetime
            now = datetime.now()
            return (now.hour * 60 + now.minute) - (9 * 60 + 30)
        except Exception:
            return None

    async def _check_open_risk(self, quotes: List[Dict], positions: dict) -> List[Dict]:
        """开盘持仓即时风险（持仓股专用快路径）。

        只读本周期已取的 quotes(昨收/开盘价/现价) + 少量持仓 + 预设离场计划，**零额外 OpenD
        调用**（不碰策略预热闸所保护的 fetch_kline 资源），故可绕过预热盲区在 09:30 即出信号。
        仅 red(或 push_on_amber 时的 amber) 产出一条 SELL action → 自动走 _push_position_sell_alert
        的持仓推送通道（含去重）。每只持仓每个交易日只报一次，避免 5min 冷却内反复刷。
        """
        if not positions:
            return []
        try:
            from ...utils.market_helper import MarketTimeHelper
            if not MarketTimeHelper.is_market_trading('HK'):
                return []
            db = getattr(self.container, 'db_manager', None)
            if not db:
                return []
            from ...services.trading.exit_timing import ExitTimingService
            from ...database.queries.exit_plan_queries import ExitPlanQueries

            svc = ExitTimingService(db)
            th = svc.th
            # 即时风险快路径只在开盘窗内生效（之后盘中数据已足，交回常规 R规则/狙击）
            mins = self._mins_since_hk_open()
            if mins is None or mins < 0 or mins > th.open_window_min:
                return []

            today = MarketTimeHelper.get_market_today('HK')
            # 每个交易日重置"已报"集合
            if getattr(self, '_open_risk_date', None) != today:
                self._open_risk_date = today
                self._open_risk_fired = set()

            codes = list(positions.keys())
            qmap = {q.get('code'): q for q in quotes if q.get('code')}
            try:
                plans = ExitPlanQueries(db).get_active_plans_map(codes, today)
            except Exception:
                plans = {}
            result = svc.open_check(list(positions.values()), qmap, plans, regime=None)

            actions: List[Dict] = []
            for it in result.get('items', []):
                code = it['stock_code']
                hit = it['light'] == 'red' or (th.push_on_amber and it['light'] == 'amber')
                if not hit or code in self._open_risk_fired:
                    continue
                self._open_risk_fired.add(code)
                actions.append({
                    'stock_code': code,
                    'stock_name': it.get('stock_name', code),
                    'signal_type': 'SELL',
                    'price': it.get('last_price') or 0,
                    'reason': f"[OPEN] 开盘风险 {it['label']}：{it['reason']}",
                    'strategy_id': 'open_check',
                    'source': 'open_check',
                })
            return actions
        except Exception as e:
            logging.debug(f"开盘持仓即时风险检查异常: {e}")
            return []

    async def _push_open_check_once(self, quotes: List[Dict], positions: dict):
        """每个交易日一次：把每只持仓的开盘判读组成单条"📋 开盘持仓检查"推送（全绿也推）。

        给用户一个开盘的确定答复，而非沉默——把被动等信号变成执行计划。
        幂等：实例属性按 HK 交易日键控，次日自动复位；日期级 dedup_key 二次兜底。
        """
        wechat = getattr(self.container, 'wechat_alert_service', None)
        if not wechat or not getattr(wechat, 'enabled', False) or not positions:
            return
        try:
            from ...utils.market_helper import MarketTimeHelper
            if not MarketTimeHelper.is_market_trading('HK'):
                return
            today = MarketTimeHelper.get_market_today('HK')
            if getattr(self, '_open_check_pushed_date', None) == today:
                return
            db = getattr(self.container, 'db_manager', None)
            if not db:
                return
            from ...services.trading.exit_timing import ExitTimingService
            from ...database.queries.exit_plan_queries import ExitPlanQueries
            from ...services.alert.wechat_alert import AlertLevel

            codes = list(positions.keys())
            qmap = {q.get('code'): q for q in quotes if q.get('code')}
            try:
                plans = ExitPlanQueries(db).get_active_plans_map(codes, today)
            except Exception:
                plans = {}
            svc = ExitTimingService(db)
            result = svc.open_check(list(positions.values()), qmap, plans,
                                    regime=svc.market_regime(today))

            icon = {'red': '🔴', 'amber': '🟡', 'green': '🟢'}
            lines, any_red = [], False
            for it in result.get('items', []):
                if it['light'] == 'red':
                    any_red = True
                tag = ' ·已设计划' if it.get('has_plan') else ''
                lines.append(
                    f"- {it['stock_name']}({it['stock_code']}) "
                    f"{icon.get(it['light'], '⚪')} {it['label']}：{it['reason']}{tag}")
            if not lines:
                return

            rg = result.get('regime') or {}
            head = f"今日{rg.get('hint', '')}({rg.get('breadth', '')})\n" if rg.get('hint') else ''
            content = (head + "\n".join(lines)
                       + "\n> 纯咨询·不下单：按你盘前的离场计划执行，别干等信号")
            level = AlertLevel.WARNING if any_red else AlertLevel.INFO

            # 同步置位幂等标志（此前无 await，不会与下一周期交错）
            self._open_check_pushed_date = today
            task = asyncio.create_task(
                wechat.send(level, "📋 开盘持仓检查", content,
                            dedup_key=f"open_check:{today}"))
            self._pending_tasks.add(task)
            task.add_done_callback(self._on_task_done)
        except Exception as e:
            logging.error(f"开盘持仓检查推送失败: {e}")

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

    async def _check_intraday_profit(self, quotes: List[Dict], positions: dict = None) -> List[Dict]:
        """检查日内高抛低吸信号（仅持仓股）"""
        taker = getattr(self.container, 'intraday_profit_taker', None)
        if not taker:
            return []
        try:
            if positions is None:
                positions = await self._get_positions_dict()
            if not positions:
                return []
            return await self._run_in_executor(taker.check, quotes, positions)
        except Exception as e:
            logging.debug(f"日内高抛低吸检查异常: {e}")
            return []

    async def _check_intraday_risks(self, quotes: List[Dict], positions: dict = None) -> List[Dict]:
        """检查日内自动化风控（跌破强支撑/真空区止盈/大单骤降逃顶）"""
        actions = []
        try:
            # 延迟初始化
            if not hasattr(self, '_intraday_risk_manager'):
                futu_trade = getattr(self.container, 'futu_trade_service', None)
                futu_client = getattr(self.container, 'futu_client', None)
                db_manager = getattr(self.container, 'db_manager', None)
                levels_service = getattr(self.container, 'intraday_levels_service', None)
                
                if futu_client and db_manager and levels_service:
                    from ...services.trading.profit.intraday_risk_manager import IntradayRiskManager
                    self._intraday_risk_manager = IntradayRiskManager(db_manager, futu_client, levels_service, futu_trade)
                else:
                    self._intraday_risk_manager = None

            if not self._intraday_risk_manager:
                return actions

            if positions is None:
                positions = await self._get_positions_dict()
            if not positions:
                return actions

            # 资金流缓存用于大单占比监测
            capital_flow_engine = getattr(self.container, 'capital_flow_signal_engine', None)
            # 批量读取持仓股的资金流缓存（修复：原 engine.cache 属性不存在）
            position_codes = [c for c in positions.keys()]
            capital_flow_map = {}
            if capital_flow_engine and position_codes:
                try:
                    capital_flow_map = capital_flow_engine._fetch_capital_flows(position_codes)
                except Exception:
                    pass

            for quote in quotes:
                stock_code = quote.get('code')
                if stock_code in positions:
                    capital_flow = capital_flow_map.get(stock_code)
                    
                    # check_risks 是 async 的，需要 await
                    new_actions = await self._intraday_risk_manager.check_risks(
                        stock_code, quote, positions[stock_code], capital_flow
                    )
                    if new_actions:
                        actions.extend(new_actions)
        except Exception as e:
            logging.error(f"日内自动化风控检查异常: {e}")
            
        return actions

    async def _check_absorption(self, quotes: List[Dict]) -> List[Dict]:
        """检查量价异常（吸收压单 + 真正拉升）"""
        try:
            # 延迟初始化
            if not hasattr(self, '_absorption_scanner'):
                db = getattr(self.container, 'db_manager', None)
                if db:
                    from ...services.analysis.absorption_scanner import AbsorptionScanner
                    self._absorption_scanner = AbsorptionScanner(db)
                else:
                    self._absorption_scanner = None

            if not self._absorption_scanner:
                return []

            # 使用已订阅的股票代码
            stock_codes = [q.get('code') for q in quotes if q.get('code')]
            if not stock_codes:
                return []

            alerts = await self._run_in_executor(
                self._absorption_scanner.scan_all, stock_codes
            )

            # 转换为 strategy_signal 格式（复用前端 Toast 展示）
            actions = []
            for alert in alerts:
                alert_type = alert.get('alert_type', 'absorption')
                if alert_type == 'rally':
                    # 拉升 → 机会提醒
                    emoji = '🚀' if alert['severity'] == 'high' else '📈'
                    signal_type = 'BUY'
                    reason = f"{emoji} 量价齐升: {alert['message']}"
                else:
                    # [2026-06-15] 买入吸收/放量下跌降级为中性观察：去掉🚨看跌措辞，
                    # 但保留 ALERT 类型(→ signal_pipeline direction=WARN)持续落库，供数日后复跑回测。
                    emoji = '👀'
                    signal_type = 'ALERT'
                    reason = f"{emoji} 量价观察: {alert['message']}"

                actions.append({
                    'stock_code': alert['stock_code'],
                    'stock_name': alert.get('stock_name', ''),
                    'signal_type': signal_type,
                    'price': alert.get('end_price', 0),
                    'reason': reason,
                    'message': alert['message'],
                    'severity': alert.get('severity', ''),  # high(🚀强拉升)/其它(📈) — 供推送质量门
                    'timestamp': datetime.now().isoformat(),
                    'strategy_id': 'absorption_scanner',
                })

            return actions
        except Exception as e:
            logging.debug(f"量价异常检查异常: {e}")
            return []

    def _filter_trading_quotes(self, quotes: List[Dict]) -> List[Dict]:
        """过滤出"所属市场此刻确实在交易"的报价。

        杜绝在非本市场交易时段用陈旧昨收快照反复跑信号（例如美股时段拿港股昨收
        触发资金流 SELL 规则）。按 stock_code 前缀判定市场，逐市场缓存当轮判断结果。
        """
        from ...utils.market_helper import MarketTimeHelper
        trading_by_market: Dict[str, bool] = {}
        result: List[Dict] = []
        for q in quotes:
            code = q.get('code', '')
            if not code:
                continue
            market = MarketTimeHelper.get_market_from_code(code)
            is_trading = trading_by_market.get(market)
            if is_trading is None:
                is_trading = MarketTimeHelper.is_market_trading(market)
                trading_by_market[market] = is_trading
            if is_trading:
                result.append(q)
        if not result and quotes:
            logging.debug(
                f"【行情管道】本轮 {len(quotes)} 只报价所属市场均未在交易，跳过信号检测"
            )
        return result

    async def _check_capital_flow_signals(self, quotes: List[Dict], positions: dict = None) -> List[Dict]:
        """检查资金流向信号（基于操盘规则）"""
        engine = getattr(self.container, 'capital_flow_signal_engine', None)
        if not engine:
            return []
        try:
            if positions is None:
                positions = await self._get_positions_dict()
            return await self._run_in_executor(
                engine.check_signals, quotes, positions
            )
        except Exception as e:
            logging.debug(f"资金流向信号检查异常: {e}")
            return []

    async def _check_swing_buyback(self, quotes: List[Dict]) -> List[Dict]:
        """检查日内波段卖后跟踪的买回条件"""
        try:
            if not hasattr(self, '_swing_tracker'):
                self._swing_tracker = None
                try:
                    from ...services.trading.intraday import IntradaySwingTracker
                    self._swing_tracker = IntradaySwingTracker()
                    logging.info("【行情管道】日内波段跟踪器已初始化")
                except Exception as e:
                    logging.debug(f"日内波段跟踪器初始化失败: {e}")

            if not self._swing_tracker:
                return []

            watching_codes = self._swing_tracker.get_watching_codes()
            if not watching_codes:
                return []

            # 获取资金流数据
            capital_flows = {}
            engine = getattr(self.container, 'capital_flow_signal_engine', None)
            if engine:
                analyzer = getattr(engine, '_analyzer', None)
                if analyzer:
                    capital_flows = analyzer.batch_read_cache_only(watching_codes)

            # 获取5分钟动量数据
            momentum_map = {}
            if engine:
                momentum_analyzer = getattr(engine, '_momentum_analyzer', None)
                if momentum_analyzer:
                    momentum_map = momentum_analyzer.analyze_batch(watching_codes)

            return self._swing_tracker.check_buyback(
                quotes, capital_flows, momentum_map
            )
        except Exception as e:
            logging.debug(f"日内波段买回检查异常: {e}")
            return []

    async def _check_t_trade(self, quotes: List[Dict], positions: dict = None) -> List[Dict]:
        """持仓做T助手：高位+主力净流出→高抛；回落+资金转入→买回。复用资金流/动量读取。

        与 _check_swing_buyback 同源拿 capital_flows / momentum，但只针对当前持仓股，
        且自带"高抛"触发（不依赖 R13），先对账(Phase 2)再评估、过收盘截点失效。
        默认告警模式（system_config: t_trade.enabled=false）；关时整段早退、零开销。
        """
        try:
            if not positions:
                return []
            from ...utils.market_helper import MarketTimeHelper
            if not MarketTimeHelper.is_market_trading('HK'):
                return []
            assistant = getattr(self.container, 't_trade_assistant', None)
            if not assistant:
                return []

            position_codes = [c for c in positions.keys() if c]
            if not position_codes:
                return []

            # 资金流 + 5分钟动量（与波段买回同一读取方式）
            capital_flows = {}
            momentum_map = {}
            engine = getattr(self.container, 'capital_flow_signal_engine', None)
            if engine:
                analyzer = getattr(engine, '_analyzer', None)
                if analyzer:
                    capital_flows = analyzer.batch_read_cache_only(position_codes)
                momentum_analyzer = getattr(engine, '_momentum_analyzer', None)
                if momentum_analyzer:
                    momentum_map = momentum_analyzer.analyze_batch(position_codes)

            # 先对账真实成交（alert 模式无挂单，安全空跑），再评估，最后过截点失效
            def _run():
                try:
                    assistant.expire_eod()
                except Exception as e:
                    logging.debug(f"做T收盘失效检查异常: {e}")
                return assistant.evaluate_cycle(
                    quotes, positions, capital_flows, momentum_map
                )
            return await self._run_in_executor(_run)
        except Exception as e:
            logging.debug(f"持仓做T检查异常: {e}")
            return []

    def _feed_sell_signals_to_swing_tracker(self, signals: List[Dict]):
        """将卖出信号送入卖后跟踪器"""
        tracker = getattr(self, '_swing_tracker', None)
        if not tracker:
            return
        for sig in signals:
            if sig.get('signal_type') == 'SELL':
                source = sig.get('source', '') or sig.get('action', '')
                # R13 波段高抛信号 或 IntradayProfitTaker 信号
                if 'swing' in source or 'R13' in sig.get('reason', '') or 'intraday' in source:
                    tracker.on_sell_signal(
                        stock_code=sig.get('stock_code', ''),
                        stock_name=sig.get('stock_name', ''),
                        sell_price=sig.get('price', 0),
                        reason=sig.get('reason', ''),
                    )

    async def _run_strategy_detection(self, quotes: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """执行策略检测（多策略信号），返回 (trade_actions, conditions)

        注意：旧系统策略 (trade_service.auto_trade) 已注销。
        交易信号现由 DecisionEngine + IntradaySniper + StockScorer 流水线统一管理。
        """
        trade_actions: List[Dict] = []
        conditions: List[Dict] = []

        # 多策略并行信号检测（保留）
        await self._run_multi_strategy_detection(quotes)

        return trade_actions, conditions

    async def _run_multi_strategy_detection(self, quotes: List[Dict]):
        """执行多策略并行信号检测，将分组信号存储到 state"""
        if not self.strategy_monitor:
            return
        if not self.legacy_strategy_detection_enabled:
            if hasattr(self.state_manager, 'set_signals_by_strategy'):
                self.state_manager.set_signals_by_strategy({})
            if not self._legacy_strategy_skipped_logged:
                logging.info(
                    "Legacy BaseStrategy detection disabled; "
                    "set ENABLE_LEGACY_STRATEGY=true to re-enable temporarily"
                )
                self._legacy_strategy_skipped_logged = True
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


    def _notify_trade_signals(self, trade_actions: List[Dict], positions: dict = None):
        """异步发送交易信号的企业微信通知（保存 task 引用）

        持仓股卖出信号特殊处理：
        1. 所有持仓股的SELL信号 → 高优先级专属推送
        2. R10(量价背离)/R13(波段高抛) → 异步调用 Claude AI 确认
        """
        wechat = getattr(self.container, 'wechat_alert_service', None)
        if not wechat or not wechat.enabled:
            return

        # 复用上层传入的持仓数据，避免重复调用 Futu API
        position_codes = set(positions.keys()) if positions else set()

        for action in trade_actions:
            # advisory(回测无边际,已静默的资金流买入规则 R1/R5/R11/R12/R14 等)不推企业微信,
            # 与信号流撤广播保持一致(避免无边际信号刷推送)。
            if action.get('advisory'):
                continue
            stock_code = action.get('stock_code', '')
            signal_type = action.get('signal_type', '')
            reason = action.get('reason', '')
            is_position = stock_code in position_codes

            # 做T助手专属推送（高抛/买回建议，自带文案+按 leg 去重），与普通信号区分
            if action.get('source') == 't_trade':
                task = asyncio.create_task(self._push_t_trade_alert(wechat, action))
                self._pending_tasks.add(task)
                task.add_done_callback(self._on_task_done)
                continue

            if is_position and signal_type == 'SELL':
                # 持仓股卖出信号 → 高优先级推送
                task = asyncio.create_task(
                    self._push_position_sell_alert(
                        wechat, action, reason
                    )
                )
                self._pending_tasks.add(task)
                task.add_done_callback(self._on_task_done)

                # R10/R13 高优信号 → 异步 Claude AI 确认
                is_high_priority = any(
                    tag in reason for tag in ('R10', 'R13', '量价背离', '波段高抛')
                )
                if is_high_priority:
                    ai_task = asyncio.create_task(
                        self._claude_confirm_position_signal(
                            wechat, stock_code, action
                        )
                    )
                    self._pending_tasks.add(ai_task)
                    ai_task.add_done_callback(self._on_task_done)
            else:
                # 非持仓股的卖出信号 = 不可操作(你没持仓、卖不了)的噪声：还会把企微推爆、触发频率
                # 限制(45009)从而把真正重要的"持仓风险"告警挤掉。故不推企微(仍进前端信号流/DB可查)。
                # 非持仓买入(机会)/持仓买入 仍照常推。
                if signal_type == 'SELL' and not is_position:
                    continue
                # 非持仓股的"弱"量价齐升(📈 中等)也降噪：只推高强度(🚀)机会；真正精选的买点仍走
                # sniper TOP5(盘中狙击)/入场择时。持仓股不受此限。
                if (signal_type == 'BUY' and not is_position
                        and action.get('strategy_id') == 'absorption_scanner'
                        and action.get('severity') != 'high'):
                    continue
                # 质量地板(flag,默认OFF)：非持仓买入的低质边际信号源头不推（"占日均0.9%"/"连续5日"等噪声族）
                if (REALTIME_QUALITY_FLOOR and signal_type == 'BUY' and not is_position
                        and action.get('severity') != 'high'
                        and _is_marginal_signal(reason)):
                    logging.info(f"[质量地板] 抑制低质买入 {stock_code}: {reason[:30]}")
                    continue
                # 非持仓股(强)买入 / 其它 → 普通推送
                task = asyncio.create_task(
                    wechat.alert_trade_signal(
                        stock_code=stock_code,
                        signal_type=signal_type,
                        price=action['price'],
                        reason=reason,
                        severity=action.get('severity'),
                    )
                )
                self._pending_tasks.add(task)
                task.add_done_callback(self._on_task_done)

    async def _push_t_trade_alert(self, wechat, action: dict):
        """做T助手高抛/买回建议 — 企业微信推送（按 t_{side}:{code}:{leg_id} 去重）。"""
        try:
            leg = action.get('t_leg', {}) or {}
            side = leg.get('side', 'sell')
            leg_id = leg.get('leg_id', '')
            stock_code = action.get('stock_code', '')
            stock_name = action.get('stock_name', stock_code)
            price = action.get('price', 0)
            message = action.get('message', action.get('reason', ''))
            mode = leg.get('mode', 'alert')
            mode_tip = "（告警·不下单）" if mode == 'alert' else "（点确认后下单）"
            if side == 'sell':
                title = f"🅣 做T高抛建议 - {stock_name}"
                color = "warning"
            else:
                title = f"🅣 做T买回建议 - {stock_name}"
                color = "info"
            content = (
                f"- 股票：**{stock_name}** ({stock_code})\n"
                f"- 现价：**{price:.3f}**\n"
                f"- 建议：<font color=\"{color}\">{message}</font>\n"
                f"- 模式：{mode}{mode_tip}"
            )
            await wechat.warning(
                title, content,
                dedup_key=f"t_{side}:{stock_code}:{leg_id}",
            )
        except Exception as e:
            logging.error(f"做T推送失败: {e}")

    async def _push_position_sell_alert(self, wechat, action: dict, reason: str):
        """持仓股卖出信号 — 高优先级企业微信推送"""
        try:
            stock_code = action.get('stock_code', '')
            stock_name = action.get('stock_name', stock_code)
            price = action.get('price', 0)
            rule_id = ''
            for tag in ('OPEN', 'R2', 'R3', 'R7', 'R10', 'R13'):
                if tag in reason:
                    rule_id = tag
                    break

            content = (
                f"- 股票：**{stock_name}** ({stock_code})\n"
                f"- 信号：<font color=\"warning\">**卖出**</font> {rule_id}\n"
                f"- 现价：**{price:.3f}**\n"
                f"- 原因：{reason}\n"
                f"- ⚡ 建议立即关注持仓操作"
            )
            await wechat.warning(
                f"⚠️ 持仓预警 - {stock_name}",
                content,
                dedup_key=f"pos_sell:{stock_code}:{rule_id}",
            )
        except Exception as e:
            logging.error(f"持仓卖出推送失败: {e}")

    async def _claude_confirm_position_signal(
        self, wechat, stock_code: str, action: dict
    ):
        """调用 Claude AI 确认持仓股的高优卖出信号，并追加推送"""
        try:
            # 获取 AI 分析器（复用现有 Claude 集成）
            analyzer = getattr(self.container, 'stock_ai_analyzer', None)
            if not analyzer or not analyzer.is_available():
                return

            stock_name = action.get('stock_name', stock_code)
            reason = action.get('reason', '')
            price = action.get('price', 0)

            # 聚合数据（简化版，只取关键数据避免太慢）
            from ...routers.trading.ai_analysis import (
                _get_stock_quote, _get_kline_data, _get_intraday_flow_data,
                _get_position_info,
            )
            quote = _get_stock_quote(self.container, stock_code)
            klines = _get_kline_data(self.container, stock_code)
            flow_data = _get_intraday_flow_data(self.container, stock_code)
            position_info = _get_position_info(self.container, stock_code)

            # 构建精简 prompt 给 Claude
            prompt = (
                f"你是港股量化交易师。持仓股 {stock_name}({stock_code}) "
                f"刚触发卖出信号：{reason}。现价 {price:.3f}。\n\n"
                f"持仓信息：{position_info}\n"
                f"K线数据(近5日)：{klines[-5:] if klines else '无'}\n"
                f"日内资金流：{flow_data}\n\n"
                f"请用50字以内判断：这个卖出信号是否可靠？建议操作？"
            )

            result = await analyzer.analyze_stock(
                stock_code=stock_code,
                stock_name=stock_name,
                quote=quote or {},
                klines=klines,
                position_info=position_info,
                flow_data=flow_data,
            )

            if result.get('success'):
                ai_data = result.get('data', {})
                ai_summary = ai_data.get('summary', ai_data.get('action_suggestion', ''))
                if ai_summary:
                    from ...services.alert.wechat_alert import AlertLevel
                    is_sell_confirm = (
                        'sell' in str(ai_data.get('action', '')).lower()
                        or '卖' in ai_summary or '减' in ai_summary
                    )
                    await wechat.send(
                        AlertLevel.WARNING if is_sell_confirm else AlertLevel.INFO,
                        f"🤖 AI确认 - {stock_name}",
                        f"- 规则信号：{reason[:60]}\n"
                        f"- AI判断：{ai_summary[:200]}\n"
                        f"- 建议操作：{ai_data.get('action_suggestion', '请结合规则判断')}",
                        dedup_key=f"ai_confirm:{stock_code}",
                    )
                    logging.info(
                        f"[AI确认] {stock_name}: {ai_summary[:50]}"
                    )
        except Exception as e:
            logging.error(f"Claude AI 确认失败 {stock_code}: {e}")

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
