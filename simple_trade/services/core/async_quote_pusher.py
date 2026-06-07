#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步行情推送服务 - 系统唯一的 Pipeline 驱动器

职责：
1. 系统启动时自动订阅目标股票
2. 管理推送循环的启动/停止生命周期
3. 驱动报价获取周期（run_quote_cycle）
4. 根据监控状态条件性驱动监控周期（run_monitoring_cycle）
5. 检测并处理市场切换
"""

import logging
import asyncio
import time
from typing import Optional, Dict, Any, List

from ...utils.logger import print_status, get_flow_logger
from ...utils.market_helper import MarketTimeHelper


class AsyncQuotePusher:
    """异步行情推送服务 - 管理推送生命周期，处理逻辑委托给 QuotePipeline"""

    def __init__(self, container, socket_manager, state_manager, quote_pipeline):
        """初始化异步行情推送服务

        Args:
            container: 服务容器
            socket_manager: SocketManager实例（AsyncServer）
            state_manager: 状态管理器
            quote_pipeline: 统一行情处理管道
        """
        self.container = container
        self.socket_manager = socket_manager
        self.state_manager = state_manager
        self.quote_pipeline = quote_pipeline

        self.is_running = False
        self.push_task: Optional[asyncio.Task] = None
        self.push_interval = 5  # 推送间隔（秒）
        # 第一层防御：构造时即获取当前市场，避免首轮推送循环误判市场切换
        self.last_active_markets: List[str] = MarketTimeHelper.get_current_active_markets() or []
        self.first_quote_ready = asyncio.Event()  # 首次报价就绪事件
        self._last_refilter_time: float = time.time()  # 上次活跃度重筛时间
        self._refilter_interval: int = 1800  # 活跃度重筛间隔（秒），默认30分钟
        self._last_pool_scan_time: float = 0  # 上次全池扫描时间
        self._pool_scan_interval: int = 60  # 全池扫描间隔（秒），1分钟
        self._pool_scanner = None  # 延迟初始化
        self._market_was_closed: bool = True  # 跟踪非交易→交易切换，初始True确保首次开盘触发
        self._pending_open_refilter: float = 0  # 开盘首筛计划执行时间，0=无计划

        # 从配置获取推送间隔
        if container.config:
            self.push_interval = getattr(container.config, 'quote_push_interval', 5)

        self._loop_count = 0

    async def start(self) -> Dict[str, Any]:
        """启动行情推送服务

        Returns:
            启动结果
        """
        result = {
            'success': False,
            'message': '',
            'subscribed_count': 0
        }

        if self.is_running:
            result['message'] = '行情推送服务已在运行中'
            result['success'] = True
            result['subscribed_count'] = self.container.subscription_manager.subscribed_count
            return result

        # 检查富途API是否可用
        if not self.container.futu_client.is_available():
            result['message'] = '富途API不可用，行情推送服务启动失败'
            logging.warning(result['message'])
            return result

        try:
            flow = get_flow_logger("行情推送启动")

            # 检查是否已有订阅
            subscribed_count = self.container.subscription_manager.subscribed_count
            if subscribed_count > 0:
                flow.step("已有订阅", count=subscribed_count)
            else:
                # 没有订阅，通过 subscription_helper 订阅目标股票
                flow.step("开始订阅")
                from ...utils.market_helper import MarketTimeHelper
                current_markets = MarketTimeHelper.get_current_active_markets()
                if not current_markets:
                    current_markets = [MarketTimeHelper.get_primary_market()]

                loop = asyncio.get_running_loop()
                subscription_result = await loop.run_in_executor(
                    None,
                    self.container.subscription_helper.subscribe_target_stocks,
                    current_markets
                )

                if not subscription_result['success']:
                    flow.error("订阅失败", reason=subscription_result['message'])
                    result['message'] = f"股票订阅失败: {subscription_result['message']}"
                    flow.end(success=False)
                    return result

                subscribed_count = subscription_result.get('subscribed_count', 0)

                # 竞态保护：如果自己的订阅返回0，但其他路径（如系统协调器）
                # 已在并行完成订阅，使用实际订阅数
                if subscribed_count == 0:
                    actual_count = self.container.subscription_manager.subscribed_count
                    if actual_count > 0:
                        subscribed_count = actual_count
                        flow.step("使用已有订阅", count=actual_count)
                    else:
                        flow.step("订阅完成", count=0,
                                  markets=','.join(current_markets))
                else:
                    flow.step("订阅完成", count=subscribed_count,
                              markets=','.join(current_markets))

            # 启动推送任务
            self.is_running = True
            # 第二层防御：订阅完成后同步当前市场状态
            init_markets = MarketTimeHelper.get_current_active_markets()
            if init_markets:
                self.last_active_markets = init_markets
            self.push_task = asyncio.create_task(self._push_loop())

            result['success'] = True
            result['message'] = f"行情推送服务已启动，订阅 {subscribed_count} 只股票"
            result['subscribed_count'] = subscribed_count
            flow.end(success=True, subscribed=subscribed_count)

        except Exception as e:
            result['message'] = f"行情推送服务启动异常: {str(e)}"
            logging.error(result['message'], exc_info=True)

        return result

    async def stop(self):
        """停止行情推送服务"""
        if not self.is_running:
            return

        self.is_running = False

        if self.push_task and not self.push_task.done():
            self.push_task.cancel()
            try:
                await asyncio.gather(self.push_task, return_exceptions=True)
                logging.info("行情推送任务已成功取消")
            except asyncio.CancelledError:
                logging.info("行情推送任务已取消")
            except asyncio.TimeoutError:
                logging.warning("行情推送任务取消超时")
            except Exception as e:
                logging.error(f"停止行情推送任务时出错: {e}", exc_info=True)

        print_status("行情推送服务已停止", "info")


    async def _push_loop(self):
        """推送循环 - 报价获取 + 条件性监控"""
        print_status("【行情推送】推送循环开始", "info")

        # P1-1: 推送循环埋点
        import os, json
        from ...utils.logger import create_dedicated_logger
        _log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'logs')
        _cycle_logger = create_dedicated_logger(
            'quote_cycle_trace', os.path.join(_log_dir, 'quote_cycle.log')
        )

        first_quote_fetched = False
        first_quote_timeout = 60  # 60 秒超时
        start_time = asyncio.get_running_loop().time()
        consecutive_failures = 0  # 连续失败计数器

        while self.is_running:
            try:
                # 0. 收盘后暂停一切：不获取报价，不执行监控
                if not MarketTimeHelper.is_any_market_trading():
                    self._market_was_closed = True
                    if self._loop_count % 60 == 1:
                        logging.info("【行情推送】所有市场已收盘，暂停报价获取和策略监控")
                    await asyncio.sleep(60)  # 收盘后每60秒检查一次是否开盘
                    self._loop_count += 1
                    continue

                # 开盘首筛：检测非交易→交易时段切换
                if self._market_was_closed:
                    self._market_was_closed = False
                    delay = 90  # 等待90秒让开盘成交数据积累
                    self._pending_open_refilter = time.time() + delay
                    logging.info(
                        f"【开盘筛选】市场从休市→开盘，{delay}秒后触发活跃度首筛"
                    )

                # 开盘首筛：延迟到期后执行
                if (self._pending_open_refilter > 0
                        and time.time() >= self._pending_open_refilter):
                    self._pending_open_refilter = 0
                    self._trigger_market_open_refilter()

                # 1. 始终执行报价获取周期
                t0 = time.time()
                quotes = await self.quote_pipeline.run_quote_cycle()
                fetch_ms = (time.time() - t0) * 1000

                # 2. 仅在监控启动时执行监控周期
                t1 = time.time()
                if self.state_manager.is_running() and quotes:
                    try:
                        await self.quote_pipeline.run_monitoring_cycle(quotes)
                    except Exception as e:
                        logging.error(f"监控周期异常（不影响报价获取）: {e}", exc_info=True)
                broadcast_ms = (time.time() - t1) * 1000

                # P1-1: 记录每轮指标
                _cycle_logger.info(json.dumps({
                    "flow": "quote_cycle",
                    "fetch_ms": round(fetch_ms, 1),
                    "broadcast_ms": round(broadcast_ms, 1),
                    "quote_count": len(quotes) if quotes else 0,
                    "consecutive_failures": consecutive_failures,
                }, ensure_ascii=False))

                # 首次报价成功后设置事件
                if not first_quote_fetched and quotes:
                    first_quote_fetched = True
                    self.first_quote_ready.set()
                    print_status("【行情推送】首次报价获取成功，系统已就绪", "ok")

                # 检查首次报价超时
                if not first_quote_fetched:
                    elapsed = asyncio.get_running_loop().time() - start_time
                    if elapsed > first_quote_timeout:
                        logging.error(f"首次报价获取超时（{first_quote_timeout}秒），设置事件避免阻塞")
                        self.first_quote_ready.set()
                        first_quote_fetched = True  # 防止重复设置

                # 3. 仅在监控运行时检查市场切换和定时重筛
                if self.state_manager.is_running():
                    await self._check_market_switch()
                    self._check_periodic_refilter()
                    await self._check_pool_scan()

                # 成功时重置连续失败计数器
                consecutive_failures = 0
                await asyncio.sleep(self.push_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                backoff = min(self.push_interval * (2 ** consecutive_failures), 60)
                logging.error(
                    f"推送循环异常(连续{consecutive_failures}次): {e}",
                    exc_info=(consecutive_failures <= 3)
                )
                await asyncio.sleep(backoff)

        print_status("【行情推送】推送循环结束", "info")

    def _check_periodic_refilter(self):
        """检查是否需要定时重新筛选活跃度

        每 _refilter_interval 秒（默认30分钟）清空当天活跃度缓存并触发后台重筛。
        重筛完成后会自动重新订阅股票。
        仅在盘中执行，收盘后跳过（避免换手率为0导致活跃股被清空）。
        """
        now = time.time()
        elapsed = now - self._last_refilter_time
        if elapsed < self._refilter_interval:
            return

        # 收盘后不重筛，保留当天活跃股数据用于盘后分析
        # K线更新由 DailyKlineUpdater（16:30自动触发）负责
        active_markets = MarketTimeHelper.get_current_active_markets()
        if not active_markets:
            return

        self._last_refilter_time = now

        try:
            from ...routers.data.activity_refilter import trigger_refilter_async
            from datetime import date

            # 清空当天缓存
            today = date.today().strftime('%Y-%m-%d')
            cleared = self.container.db_manager.stock_activity_queries.clear_daily_activity_records(today)
            logging.info(
                f"【定时重筛】已清空 {cleared} 条活跃度缓存，触发后台重新筛选"
            )

            # 触发异步重筛（后台线程执行，不阻塞推送循环）
            started = trigger_refilter_async(self.container)
            if started:
                logging.info("【定时重筛】后台重筛任务已启动")
            else:
                logging.info("【定时重筛】无需重筛（正在进行中或无待检查股票）")

        except Exception as e:
            logging.error(f"【定时重筛】触发失败: {e}", exc_info=True)

    def _trigger_market_open_refilter(self):
        """开盘时触发活跃度重筛

        清空盘前/集合竞价期间的无效缓存数据，触发后台重新筛选，
        并重置30分钟定时器避免重复触发。
        """
        try:
            from ...routers.data.activity_refilter import trigger_refilter_async
            from datetime import date

            # 清空当天缓存（盘前/集合竞价的数据无效）
            today = date.today().strftime('%Y-%m-%d')
            cleared = self.container.db_manager.stock_activity_queries.clear_daily_activity_records(today)
            logging.info(f"【开盘筛选】已清空 {cleared} 条盘前活跃度缓存")

            # 重置30分钟定时器，避免开盘后很快又触发定时重筛
            self._last_refilter_time = time.time()

            # 触发异步重筛（后台线程执行，不阻塞推送循环）
            started = trigger_refilter_async(self.container)
            if started:
                logging.info("【开盘筛选】后台重筛任务已启动")
            else:
                logging.info("【开盘筛选】跳过（重筛任务已在进行中）")

        except Exception as e:
            logging.error(f"【开盘筛选】触发失败: {e}", exc_info=True)

    async def _check_pool_scan(self):
        """每3分钟执行全池快照扫描，发现异动股 → 评分 → 预警/交易"""
        now = time.time()
        if now - self._last_pool_scan_time < self._pool_scan_interval:
            return

        # 仅盘中执行
        active_markets = MarketTimeHelper.get_current_active_markets()
        if not active_markets:
            return

        self._last_pool_scan_time = now

        # 延迟初始化扫描器
        if self._pool_scanner is None:
            try:
                from ...services.market_data.pool_snapshot_scanner import PoolSnapshotScanner
                self._pool_scanner = PoolSnapshotScanner(self.container)
                logging.info("【全池扫描】扫描器初始化完成")
            except Exception as e:
                logging.error(f"【全池扫描】初始化失败: {e}")
                return

        try:
            # 在后台线程执行扫描（避免阻塞推送循环）
            anomalies = await asyncio.get_event_loop().run_in_executor(
                None, self._pool_scanner.scan
            )

            if anomalies:
                # 推送异动通知到前端
                await self._broadcast_anomalies(anomalies)

                # 尝试替换订阅（最多5只）
                rotation = self._pool_scanner.get_rotation_candidates()[:5]
                if rotation:
                    self._rotate_subscriptions(rotation)

                # 对异动股进行评分并生成预警
                await self._score_and_alert_anomalies(anomalies)

        except Exception as e:
            logging.warning(f"【全池扫描】执行失败: {e}")

    async def _score_and_alert_anomalies(self, anomalies):
        """对异动股进行评分，达标则推送预警并可选创建交易任务"""
        try:
            from ...services.strategy.stock_scorer import StockScorer, PASSING_SCORE

            db = self.container.db_manager
            scorer = getattr(self.container, 'stock_scorer', None) or StockScorer()
            scored_alerts = []

            for anomaly in anomalies:
                code = anomaly.code
                try:
                    # 构建评分指标
                    indicators = {
                        'today_change': anomaly.change_rate,
                        'vol_ratio': anomaly.volume_ratio,
                        'day_amplitude': 0,
                    }

                    # 从K线补充历史指标
                    rows = db.execute_query(
                        "SELECT close_price FROM kline_data "
                        "WHERE stock_code = ? ORDER BY time_key DESC LIMIT 6",
                        (code,)
                    )
                    if rows and len(rows) >= 2:
                        closes = [r[0] for r in rows]
                        indicators['prev_day_change'] = (
                            (closes[0] - closes[1]) / closes[1] * 100
                            if closes[1] > 0 else 0
                        )
                        if len(closes) >= 6:
                            indicators['change_5d'] = (
                                (closes[0] - closes[5]) / closes[5] * 100
                                if closes[5] > 0 else 0
                            )

                    # 从逐笔成交数据计算买卖力量比 (ticker_power)
                    ticker_svc = getattr(self.container, 'ticker_service', None)
                    if ticker_svc:
                        try:
                            ticker_data = ticker_svc.get_ticker_data(code)
                            if ticker_data and hasattr(ticker_data, 'buy_turnover') and ticker_data.sell_turnover > 0:
                                bsr = ticker_data.buy_turnover / ticker_data.sell_turnover
                                indicators['ticker_power'] = bsr - 1.0
                        except Exception:
                            pass
                    # 若无逐笔数据，回退到资金流缓存
                    if 'ticker_power' not in indicators:
                        cap_rows = db.execute_query(
                            "SELECT net_inflow_ratio FROM capital_flow_cache "
                            "WHERE stock_code = ? ORDER BY timestamp DESC LIMIT 1",
                            (code,)
                        )
                        if cap_rows and cap_rows[0][0] is not None:
                            indicators['ticker_power'] = cap_rows[0][0]

                    # 评分：使用全策略评分（TREND + BREAKOUT + MOMENTUM）
                    all_scores = scorer.score_all_strategies(code, anomaly.name, indicators)
                    result = all_scores['best']

                    if result.passed:
                        scored_alerts.append({
                            'code': code,
                            'name': anomaly.name,
                            'price': anomaly.price,
                            'change_rate': anomaly.change_rate,
                            'volume_ratio': anomaly.volume_ratio,
                            'anomaly_type': anomaly.anomaly_type,
                            'has_shrinkage': anomaly.has_shrinkage,
                            'score': result.total_score,
                            'mode': result.mode,
                            'passed': True,
                            'details': [
                                {'dim': d.dimension, 'score': d.score,
                                 'max': d.max_score, 'note': d.note}
                                for d in result.details
                            ],
                            'trade_params': result.trade_params.to_dict()
                            if result.trade_params else None,
                            'detected_at': anomaly.detected_at,
                            'cap_tier': getattr(anomaly, 'cap_tier', ''),
                            'capital_score': getattr(anomaly, 'capital_score', 0),
                            'signal_change': getattr(anomaly, 'signal_change', 0),
                        })

                        # 资金驱动信号显示资金评分，传统信号显示量比
                        if anomaly.anomaly_type in ('capital_inflow', 'big_buy_driven'):
                            logging.info(
                                f"【异动评分】{code} {anomaly.name} "
                                f"涨{anomaly.change_rate:+.1f}% 资金{getattr(anomaly, 'capital_score', 0):.0f}分 "
                                f"→ {result.mode}模式 {result.total_score}分 ✓通过"
                            )
                        else:
                            logging.info(
                                f"【异动评分】{code} {anomaly.name} "
                                f"涨{anomaly.change_rate:+.1f}% 量比{anomaly.volume_ratio:.1f} "
                                f"→ {result.mode}模式 {result.total_score}分 ✓通过"
                            )

                except Exception as e:
                    logging.debug(f"【异动评分】{code} 评分失败: {e}")

            # 推送评分预警到前端
            if scored_alerts:
                await self.socket_manager.emit('anomaly_scored', {
                    'alerts': scored_alerts,
                    'count': len(scored_alerts),
                    'scan_time': time.strftime('%H:%M:%S'),
                })
                logging.info(
                    f"【异动评分】{len(scored_alerts)}只通过评分: "
                    + ", ".join(f"{a['code']}({a['score']}分)" for a in scored_alerts[:5])
                )

                # 如果 auto_trade 已开启，自动创建交易任务
                self._try_create_anomaly_trades(scored_alerts)

        except Exception as e:
            logging.warning(f"【异动评分】评分流程失败: {e}")

    def _try_create_anomaly_trades(self, scored_alerts):
        """将评分通过的异动股信号发送到统一决策引擎"""
        try:
            engine = getattr(self.container, 'trade_decision_engine', None)
            if not engine:
                return

            for alert in sorted(scored_alerts, key=lambda x: x['score'], reverse=True)[:5]:
                asyncio.ensure_future(engine.on_anomaly_signal(alert))

        except Exception as e:
            logging.warning(f"【异动交易】发送信号失败: {e}")

    async def _broadcast_anomalies(self, anomalies):
        """通过WebSocket推送异动通知"""
        try:
            data = [{
                'code': a.code,
                'name': a.name,
                'change_rate': a.change_rate,
                'volume_ratio': a.volume_ratio,
                'turnover_rate': a.turnover_rate,
                'price': a.price,
                'anomaly_type': a.anomaly_type,
                'has_shrinkage': a.has_shrinkage,
                'detected_at': a.detected_at,
                'detail': a.detail,
            } for a in anomalies]

            await self.socket_manager.emit('pool_anomaly', {
                'anomalies': data,
                'count': len(data),
                'scan_time': time.strftime('%H:%M:%S'),
            })
        except Exception as e:
            logging.debug(f"【全池扫描】WebSocket推送失败: {e}")

    def _rotate_subscriptions(self, new_codes):
        """将异动股替换进订阅列表（含 QUOTE + TICKER 逐笔）"""
        try:
            sub_mgr = self.container.subscription_manager
            if not sub_mgr:
                return

            subscribed = sub_mgr.subscribed_stocks
            to_add = [c for c in new_codes if c not in subscribed]

            if not to_add:
                # 即使已订阅QUOTE，也检查是否需要补订TICKER
                ticker_subscribed = sub_mgr.ticker_subscribed_stocks
                need_ticker = [c for c in new_codes if c not in ticker_subscribed]
                if need_ticker:
                    try:
                        from futu import SubType
                        sub_mgr.subscribe_multi_types(need_ticker[:5], [SubType.TICKER])
                        logging.info(
                            f"【异动轮换】补订TICKER {len(need_ticker)}只: {need_ticker[:5]}"
                        )
                    except Exception as e:
                        logging.debug(f"【异动轮换】补订TICKER失败: {e}")
                return

            # 新股票：同时订阅 QUOTE + TICKER
            try:
                from futu import SubType
                result = sub_mgr.subscribe_multi_types(
                    to_add[:5], [SubType.QUOTE, SubType.TICKER]
                )
                if result.get('success'):
                    logging.info(
                        f"【异动轮换】新增订阅 {len(to_add)} 只异动股(QUOTE+TICKER): "
                        f"{to_add[:5]}"
                    )
            except ImportError:
                # futu 未安装时回退到仅 QUOTE 订阅
                result = sub_mgr.subscribe(to_add)
                if result.get('success'):
                    logging.info(
                        f"【异动轮换】新增订阅 {len(to_add)} 只异动股(仅QUOTE): "
                        f"{to_add[:5]}"
                    )
        except Exception as e:
            logging.warning(f"【异动轮换】订阅失败: {e}")

    async def _check_market_switch(self):
        """检查并处理市场切换"""
        current_markets = MarketTimeHelper.get_current_active_markets()
        if not current_markets:
            current_markets = [MarketTimeHelper.get_primary_market()]

        # 第三层防御：空列表守卫，初始状态不触发切换
        if not self.last_active_markets:
            self.last_active_markets = current_markets
            return

        if set(current_markets) != set(self.last_active_markets):
            await self._handle_market_switch(current_markets)

    async def _handle_market_switch(self, current_markets: List[str]):
        """处理市场切换 - 重新订阅新市场股票（含重试和竞态保护）"""
        old_markets = self.last_active_markets
        print_status(
            f"【行情推送】市场切换: {old_markets} -> {current_markets}",
            "info"
        )

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self.container.subscription_helper.unsubscribe_all
                )

                self.state_manager.invalidate_quotes_cache()
                self.state_manager.clear_trading_conditions()

                result = await asyncio.get_event_loop().run_in_executor(
                    None, self.container.subscription_helper.subscribe_target_stocks, current_markets
                )

                if result['success']:
                    # 订阅成功后才更新 last_active_markets
                    self.last_active_markets = current_markets
                    print_status(f"市场切换完成: {result.get('subscribed_count', 0)} 只股票已订阅", "ok")
                    return
                else:
                    logging.warning(
                        f"市场切换订阅失败(第{attempt}次): {result.get('message', '')}"
                    )
            except Exception as e:
                logging.error(f"市场切换异常(第{attempt}次): {e}")

            if attempt < max_retries:
                backoff = 2 ** attempt
                logging.info(f"市场切换重试，{backoff}秒后再试...")
                await asyncio.sleep(backoff)

        # 所有重试失败，不更新 last_active_markets，下次循环会重新尝试
        logging.error(
            f"市场切换失败（{max_retries}次重试均失败），"
            f"保留 last_active_markets={old_markets}"
        )

    def get_status(self) -> Dict[str, Any]:
        """获取行情推送服务状态

        Returns:
            服务状态信息
        """
        return {
            'is_running': self.is_running,
            'push_interval': self.push_interval,
            'subscribed_count': self.container.subscription_manager.subscribed_count,
            'subscribed_stocks': list(self.container.subscription_manager.subscribed_stocks)[:10],
            'task_alive': self.push_task and not self.push_task.done() if self.push_task else False
        }
