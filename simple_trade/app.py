#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 应用入口

迁移阶段：与 Flask 并行运行
- Flask 运行在原有端口 5000
- FastAPI 可独立测试，后续整合

重构说明：
- 拆分自原 app.py (418行 → 3个文件)
- _initialize_system_data → core/initialization.py
- 本文件只保留: 日志配置、lifespan、create_app
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config.config import ConfigManager
from .core import get_state_manager, ServiceContainer, SystemCoordinator
from .core.pipeline import QuotePipeline
from .core.exceptions.exception_handlers import register_exception_handlers
from .core.initialization import initialize_system_data
from . import dependencies
from .utils.logger import print_status, setup_logging
import logging
import os

# 初始化日志系统
log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "backend.log")

# 从配置读取日志级别
config = ConfigManager.load_config()
log_config = config.logging
setup_logging(
    log_file=log_file,
    log_level=log_config['file_level'],
    console_level=log_config['console_level'],
    use_rotation=True
)

# 额外抑制 socketio 和 engineio 的详细日志
logging.getLogger('socketio').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('socketio.server').setLevel(logging.WARNING)
logging.getLogger('engineio.server').setLevel(logging.WARNING)




@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    quote_pusher_started = False
    quote_pusher = None
    v2_runtime = None
    background_tasks: list[asyncio.Task] = []

    def _track(coro, name: str) -> asyncio.Task:
        """创建后台任务并追踪引用，注册异常回调"""
        task = asyncio.create_task(coro, name=name)
        background_tasks.append(task)
        task.add_done_callback(lambda t: (
            logging.error(f"后台任务 {t.get_name()} 异常: {t.exception()}", exc_info=t.exception())
            if not t.cancelled() and t.exception() else None
        ))
        return task

    try:
        # 版本标识 - 自动从 git 获取
        import subprocess as _sp
        try:
            BUILD_VERSION = _sp.check_output(
                ['git', 'describe', '--tags', '--always', '--dirty'],
                cwd=os.path.dirname(os.path.dirname(__file__)),
                stderr=_sp.DEVNULL, text=True
            ).strip()
        except Exception:
            BUILD_VERSION = "unknown"
        print_status(f"代码版本: {BUILD_VERSION}", "ok")
        logging.info(f"===== 系统启动 BUILD={BUILD_VERSION} =====")

        # P5-1: 阻塞启动计时
        import time as _time
        _t_startup = _time.monotonic()

        # 启动时初始化
        config = ConfigManager.load_config("simple_trade/config.json")
        state_manager = get_state_manager()
        state_manager.set_quotes_ttl(config.update_interval)

        # 市场判断：默认走真实交易时段/周末/节假日判断。
        # 仅当显式设置 FORCE_MARKET=HK|US 时才强制覆盖（用于测试/回放），
        # 否则绝不强制——否则会短路 is_market_trading 的周末/时段守卫，
        # 导致非交易时段（如周末美股段）用陈旧昨收跑出主力资金/防守等假信号。
        from .utils.market_helper import MarketTimeHelper
        _force_market = os.environ.get("FORCE_MARKET", "").strip().upper()
        if _force_market in ("HK", "US"):
            MarketTimeHelper.set_force_market(_force_market)
            logging.warning(f"[市场覆盖] FORCE_MARKET={_force_market} 已生效，跳过真实交易时段判断")

        # 初始化服务容器（异步版本，不阻塞事件循环）
        container = ServiceContainer(config, app=None)
        await container.async_initialize_all()

        # 注入主事件循环到参数缓存管理器（使其能从工作线程安全提交协程）
        if hasattr(container, 'strategy_monitor_service') and container.strategy_monitor_service:
            container.strategy_monitor_service.params_cache_manager.set_event_loop(
                asyncio.get_running_loop()
            )

        # 获取 Socket 管理器（全局单例）
        from .websocket import get_socket_manager as _get_socket_manager
        socket_manager = _get_socket_manager()

        # 初始化统一行情处理管道（A6: 显式依赖注入）
        quote_pipeline = QuotePipeline(
            container=container,
            socket_manager=socket_manager,
            state_manager=state_manager,
            risk_coordinator=getattr(container, 'risk_coordinator', None),
            price_monitor=getattr(container, 'price_monitor_service', None),
            strategy_monitor=getattr(container, 'strategy_monitor_service', None),
            # 显式注入核心依赖
            subscription_manager=container.subscription_manager,
            stock_data_service=container.stock_data_service,
            alert_service=container.alert_service,
            kline_service=container.kline_service,
        )

        # 初始化系统协调器（替代旧的 MonitorCoordinator 和 BroadcastCoordinator）
        system_coordinator = SystemCoordinator(
            container, state_manager
        )

        # 通过 container 统一管理所有顶层服务引用（A1 重构）
        container.quote_pipeline = quote_pipeline
        container.system_coordinator = system_coordinator
        container.state_manager = state_manager

        # 注册 container 到 dependencies（唯一的 setter）
        dependencies.set_container(container)

        # V2 内核：shadow 只落库；alert 可提醒；本阶段不允许券商下单。
        # 配置错误或启动失败只关闭 V2，不能影响现有 V1 生产链路。
        try:
            from .v2.application.runtime import V2Runtime
            from .v2.config.models import V2Config
            from .v2.infrastructure.candidate_subscription_adapter import (
                LegacyCandidateSubscriptionAdapter,
            )

            v2_config = V2Config.from_env()
            v2_alerting = v2_config.mode.value == "alert"
            v2_runtime = V2Runtime(
                container.db_manager,
                v2_config,
                position_source=getattr(container, "futu_trade_service", None),
                socket_manager=socket_manager if v2_alerting else None,
                wechat_service=(
                    getattr(container, "wechat_alert_service", None) if v2_alerting else None
                ),
                frequency_guard=(
                    getattr(container, "trade_frequency_guard", None) if v2_alerting else None
                ),
                candidate_subscription_port=LegacyCandidateSubscriptionAdapter(
                    container.subscription_helper
                ),
            )
            container.v2_runtime = v2_runtime
            if await v2_runtime.start():
                logging.info(
                    "V2 影子内核已启动: mode=%s strategy_version=%s",
                    v2_config.mode.value,
                    v2_config.strategy_version,
                )
            else:
                logging.info("V2 影子内核未启用 (V2_ENABLED=0)")
        except Exception as e:
            v2_runtime = None
            container.v2_runtime = None
            logging.error("V2 影子内核启动失败，V1 继续运行: %s", e, exc_info=True)

        # ========== 系统数据初始化（与 Flask 模式一致）==========
        init_success = await initialize_system_data(container, state_manager)

        # ========== 创建并启动 AsyncQuotePusher ==========
        from .services.core import AsyncQuotePusher
        quote_pusher = AsyncQuotePusher(
            container=container,
            socket_manager=socket_manager,
            state_manager=state_manager,
            quote_pipeline=quote_pipeline
        )
        container.quote_pusher = quote_pusher

        # P2-11: 连接缓存过期回调，过期时日志提示（推送循环自身的 sleep 间隔已足够快速刷新）
        def _on_cache_expire():
            logging.debug("报价缓存过期，下一次推送循环将自动刷新")
        state_manager.quote_cache.set_on_expire_callback(_on_cache_expire)

        # 启动行情推送（放到后台任务，不阻塞服务器启动）
        async def _start_quote_pusher_background():
            """后台启动行情推送，避免阻塞 HTTP 服务"""
            nonlocal quote_pusher_started
            try:
                result = await quote_pusher.start()
                if result['success']:
                    quote_pusher_started = True
                    print_status("【行情推送】后台任务已启动", "ok")
                else:
                    logging.error(f"行情推送启动失败: {result['message']}")
                    print_status(f"【行情推送】启动失败: {result['message']}", "error")
            except Exception as e:
                logging.error(f"行情推送后台启动异常: {e}", exc_info=True)

        if init_success:
            _track(_start_quote_pusher_background(), name="quote_pusher_startup")
            print_status("【行情推送】正在后台启动订阅（HTTP 服务已就绪）...", "info")

            # 启动全局连接监控（Phase 3）
            if hasattr(container, 'global_connection_manager') and container.global_connection_manager:
                _track(container.global_connection_manager.start_monitoring(), name="global_connection_monitor")
                logging.info("全局连接监控已启动")

            # 启动 Phase 4-6 异步服务
            if hasattr(container, 'unified_cache') and container.unified_cache:
                _track(container.unified_cache.start_monitoring(), name="unified_cache_monitor")
                logging.info("统一缓存监控已启动")

            if hasattr(container, 'global_monitoring_dashboard') and container.global_monitoring_dashboard:
                _track(container.global_monitoring_dashboard.start_monitoring(), name="global_monitoring")
                logging.info("全局监控面板已启动")

            # P1-2: 链路健康监控
            from .core.monitoring.link_health import LinkHealthMonitor
            link_monitor = LinkHealthMonitor()
            container.link_health_monitor = link_monitor
            _track(link_monitor.start_monitoring(), name="link_health_monitor")
            logging.info("链路健康监控已启动")

            # P1-2: 订阅一致性巡检
            from .core.monitoring.subscription_checker import SubscriptionChecker
            sub_checker = SubscriptionChecker(container.futu_client, container.subscription_manager)
            container.subscription_checker = sub_checker
            _track(sub_checker.start(), name="subscription_checker")
            logging.info("订阅一致性巡检已启动")

            # 启动活跃个股后台预计算（大单追踪 + 量比）
            try:
                from .services.market_data.high_turnover_enricher import HighTurnoverEnricher
                enricher = HighTurnoverEnricher(container)
                async def _delayed_enricher():
                    await asyncio.sleep(60)  # 延迟 60 秒，等 OpenD 稳定后再启动
                    await enricher.start()
                _track(_delayed_enricher(), name="high_turnover_enricher")
                logging.info("HighTurnoverEnricher 将在 60 秒后启动")
            except Exception as e:
                logging.warning(f"HighTurnoverEnricher 启动失败（活跃个股大单数据不可用）: {e}")

            # 启动每日K线自动更新任务（收盘后16:30自动更新）
            try:
                from .services.market_data.kline.daily_kline_updater import DailyKlineUpdater
                daily_kline_updater = DailyKlineUpdater(container)
                _track(daily_kline_updater.start(), name="daily_kline_updater")
                logging.info("每日K线自动更新任务已注册（16:30触发）")
            except Exception as e:
                logging.warning(f"每日K线自动更新任务启动失败: {e}")

            # 启动每日板块成分股自动更新任务（收盘后16:40，补入新股）
            try:
                from .services.market_data.plate.daily_plate_updater import DailyPlateUpdater
                daily_plate_updater = DailyPlateUpdater(container)
                _track(daily_plate_updater.start(), name="daily_plate_updater")
                logging.info("每日板块成分股自动更新任务已注册（16:40触发）")
            except Exception as e:
                logging.warning(f"每日板块成分股自动更新任务启动失败: {e}")

            # 启动逐笔分钟归档器（把 ticker_data 聚合成长期保留的 ticker_minute，供盘中回测；
            # 原始逐笔只留7天，分钟级小5~7倍可长留）
            try:
                from .services.market_data.ticker_minute_archiver import TickerMinuteArchiver
                ticker_minute_archiver = TickerMinuteArchiver(container)
                container.ticker_minute_archiver = ticker_minute_archiver
                async def _start_ticker_archiver():
                    await asyncio.sleep(120)  # 等系统稳定再追赶归档
                    await ticker_minute_archiver.start()
                _track(_start_ticker_archiver(), name="ticker_minute_archiver")
                logging.info("逐笔分钟归档器已注册（启动追赶现存7天 + 每小时巡检）")
            except Exception as e:
                logging.warning(f"逐笔分钟归档器启动失败: {e}")

            # 启动动量引擎（BSR + Delta 实时信号）
            try:
                from .services.momentum import MomentumEngine
                momentum_engine = MomentumEngine(container)
                container.momentum_engine = momentum_engine
                async def _start_momentum():
                    await asyncio.sleep(5)  # 等待订阅稳定
                    await momentum_engine.start()
                _track(_start_momentum(), name="momentum_engine")
                logging.info("动量引擎已注册启动")
            except Exception as e:
                logging.warning(f"动量引擎启动失败: {e}")

            # 逐笔主力资金累加器（推送驱动；默认 OFF，CAPITAL_TICK_ACCUMULATOR_ENABLED=1 启用）
            # 挂在 TICKER 推送链上逐笔累加主力净流入（全天累计 + 滚动窗口），与富途口径双跑对照。
            # 大单分级按每股自适应：threshold_provider 查 BaselineService 标定门槛（MINIMAX≈300万、
            # 翼菲≈15万），冷启动回退 kline 日均成交额代理。
            try:
                from .services.analysis.flow.tick_capital_accumulator import (
                    TickCapitalAccumulator, TickCapitalConfig,
                )

                def _capital_threshold_provider(code):
                    try:
                        bs = getattr(container, 'baseline_service', None)
                        if bs is None:
                            return None
                        large, sup, _scale = bs.get_capital_tiers(code)
                        return (large, sup) if large and large > 0 else None
                    except Exception:
                        return None

                container.tick_capital_accumulator = TickCapitalAccumulator(
                    TickCapitalConfig.from_env(),
                    threshold_provider=_capital_threshold_provider)
                if container.tick_capital_accumulator.enabled:
                    logging.info("逐笔主力资金累加器已启用 (CAPITAL_TICK_ACCUMULATOR_ENABLED=1)")

                    # 启动 seed：从 tick_capital_flow 当日最新快照重建累加器状态，治后端
                    # 重启清空内存→丢当日累积(cum/peak/计数)→看板回退富途口径、capital_trend
                    # 回落判读失真。seed 是增量合并+按 last_seq 去重，与 live 推送线程竞态安全。
                    def _seed_tick_accumulator_sync():
                        acc = getattr(container, 'tick_capital_accumulator', None)
                        db = getattr(container, 'db_manager', None)
                        if not acc or not getattr(acc, 'enabled', False) or not db:
                            return
                        try:
                            from .utils.market_helper import MarketTimeHelper
                            today = MarketTimeHelper.get_market_today("HK")
                        except Exception:
                            today = None
                        if not today:
                            return
                        rows = db.execute_query(
                            "SELECT stock_code, trade_date, cum_main_net, window_main_net, "
                            "super_large_buy, super_large_sell, large_buy, large_sell, "
                            "big_order_buy_ratio, cum_peak, cum_trough, big_buy_count, "
                            "big_sell_count, last_seq FROM tick_capital_flow WHERE id IN ("
                            "  SELECT MAX(id) FROM tick_capital_flow WHERE trade_date=? "
                            "  GROUP BY stock_code)", (today,)) or []
                        n = 0
                        for r in rows:
                            acc.seed({
                                "stock_code": r[0], "trade_date": r[1],
                                "super_large_buy": r[4], "super_large_sell": r[5],
                                "large_buy": r[6], "large_sell": r[7],
                                "cum_peak": r[9], "cum_trough": r[10],
                                "big_buy_count": r[11], "big_sell_count": r[12],
                                "last_seq": r[13],
                            })
                            n += 1
                        if n:
                            logging.info(f"逐笔累加器已从快照恢复 {n} 只当日状态(治重启丢累积)")

                    async def _seed_tick_accumulator():
                        await asyncio.sleep(5)  # 让 DB/容器就绪；seed 竞态安全,无需赶在推送前
                        try:
                            await asyncio.to_thread(_seed_tick_accumulator_sync)
                        except Exception as e:
                            logging.warning(f"逐笔累加器 seed 失败: {e}")
                    _track(_seed_tick_accumulator(), name="tick_accumulator_seed")
            except Exception as e:
                logging.warning(f"逐笔主力资金累加器初始化失败: {e}")

            # 主力资金趋势检测器（信息型提醒：上升/回落 + 流入额/力度/涨幅/第几次大单；
            # 默认 OFF，CAPITAL_TREND_ALERT_ENABLED=1 启用；依赖累加器一起开）。
            try:
                from .services.analysis.flow.capital_trend_detector import (
                    CapitalTrendDetector, CapitalTrendConfig,
                )
                container.capital_trend_detector = CapitalTrendDetector(
                    CapitalTrendConfig.from_env())
                if container.capital_trend_detector.enabled:
                    logging.info("主力资金趋势检测器已启用 (CAPITAL_TREND_ALERT_ENABLED=1)")
            except Exception as e:
                logging.warning(f"主力资金趋势检测器初始化失败: {e}")

            # 启动一次性大单门槛/力度基准标定（仅累加器或检测器启用时；放线程池不阻塞事件循环）
            try:
                acc_on = getattr(getattr(container, 'tick_capital_accumulator', None), 'enabled', False)
                det_on = getattr(getattr(container, 'capital_trend_detector', None), 'enabled', False)
                if acc_on or det_on:
                    def _calibrate_capital_thresholds_sync():
                        from .services.baseline import CapitalThresholdCalibrator
                        db = getattr(container, 'db_manager', None)
                        if not db:
                            return
                        cal = CapitalThresholdCalibrator(db)
                        latest = db.execute_query(
                            "SELECT trade_date FROM ticker_data GROUP BY trade_date "
                            "ORDER BY trade_date DESC LIMIT 1")
                        if not latest:
                            return
                        codes = [r[0] for r in (db.execute_query(
                            "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date=?",
                            (latest[0][0],)) or [])]
                        n = sum(1 for c in codes if _safe_calibrate(cal, c))
                        logging.info(f"主力资金大单门槛标定完成: {n}/{len(codes)} 只")

                    def _safe_calibrate(cal, c):
                        try:
                            return cal.calibrate(c)
                        except Exception:
                            return False

                    async def _calibrate_capital_thresholds():
                        await asyncio.sleep(120)  # 等订阅/逐笔积累
                        try:
                            await asyncio.to_thread(_calibrate_capital_thresholds_sync)
                        except Exception as e:
                            logging.warning(f"主力资金门槛标定失败: {e}")
                    _track(_calibrate_capital_thresholds(), name="capital_threshold_calibration")
            except Exception as e:
                logging.warning(f"主力资金门槛标定调度失败: {e}")

            # 启动盘中狙击手引擎（IntradaySniper）
            try:
                from .services.sniper.intraday_sniper import IntradaySniper
                sniper = IntradaySniper(container)
                container.intraday_sniper = sniper
                async def _start_sniper():
                    await asyncio.sleep(90)  # 等待逐笔数据积累
                    await sniper.start()
                _track(_start_sniper(), name="intraday_sniper")
                logging.info("IntradaySniper 将在 90 秒后启动")
            except Exception as e:
                logging.warning(f"IntradaySniper 启动失败: {e}")

            # 启动入场择时信号录制（实验·只读）：周期性把 🟢/🔴 触发落库，供"全部信号"历史页复盘
            try:
                async def _entry_timing_recorder():
                    await asyncio.sleep(100)  # 等逐笔/日线积累
                    from datetime import datetime as _dt
                    from .services.trading.entry_timing import EntryTimingService
                    from .utils.market_helper import MarketTimeHelper
                    svc = EntryTimingService(container.db_manager)
                    while True:
                        try:
                            now = _dt.now()
                            hhmm = now.strftime("%H:%M")
                            if "09:25" <= hhmm <= "16:05" and MarketTimeHelper.is_trading_day('HK', now):
                                svc.record()
                        except Exception as e:
                            logging.debug(f"入场择时录制异常: {e}")
                        await asyncio.sleep(30)
                _track(_entry_timing_recorder(), name="entry_timing_recorder")
                logging.info("入场择时信号录制已注册（30s/轮，仅交易时段）")
            except Exception as e:
                logging.warning(f"入场择时录制启动失败: {e}")

            # 注入容器到 Ticker 推送处理器（使推送数据能驱动动量引擎）
            try:
                container.futu_client.set_container_for_push(container)
            except Exception as e:
                logging.warning(f"Ticker推送处理器容器注入失败: {e}")

            # 自动启动监控：每次后端启动后自动开启监控
            async def _auto_start_monitoring():
                """后台自动启动监控"""
                try:
                    # 等待行情推送启动完成（给 3 秒缓冲）
                    await asyncio.sleep(3)
                    print_status("【自动启动】正在启动监控...", "info")
                    await system_coordinator.start()
                    print_status("【自动启动】监控已启动", "ok")
                except Exception as e:
                    logging.error(f"自动启动监控失败: {e}", exc_info=True)
                    print_status(f"【自动启动】监控启动失败: {e}", "error")
            _track(_auto_start_monitoring(), name="auto_start_monitoring")

            # 发送企业微信启动通知
            if hasattr(container, 'wechat_alert_service') and container.wechat_alert_service:
                try:
                    await container.wechat_alert_service.alert_system_started()
                except Exception as e:
                    logging.warning(f"企业微信启动通知发送失败: {e}")
        else:
            logging.warning("系统数据初始化失败，跳过行情推送启动")
            print_status("【行情推送】跳过启动（初始化失败）", "warn")

        # P5-1: HTTP 就绪计时
        _startup_ms = (_time.monotonic() - _t_startup) * 1000
        print_status(f"HTTP API 就绪（阻塞启动耗时 {_startup_ms:.0f}ms）", "ok")
        logging.info(f"[P5-1] HTTP API 就绪: blocking_startup_ms={_startup_ms:.0f}")

        yield

    except Exception as e:
        logging.error(f"应用启动失败: {e}", exc_info=True)
        print_status(f"【系统】启动失败: {e}", "error")
        raise

    finally:
        # V2 使用独立 supervisor 持有真实长期任务句柄，先优雅排空并停止。
        if v2_runtime is not None:
            try:
                await v2_runtime.stop()
                logging.info("V2 影子内核已停止")
            except Exception as e:
                logging.warning(f"V2 影子内核停止异常（不影响关闭）: {e}")

        # 取消所有后台任务
        for t in background_tasks:
            if not t.done():
                t.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
            logging.info(f"已取消 {len(background_tasks)} 个后台任务")

        # 确保清理所有资源
        try:
            if quote_pusher_started and quote_pusher:
                await quote_pusher.stop()

            try:
                state = state_manager
                if state.is_running():
                    # 进程关闭时只清理内存状态，不持久化 is_running=false
                    # 这样重启后 was_running_before_shutdown() 仍返回 true，可以自动恢复
                    state._is_running = False
                    print_status("【系统协调器】进程关闭，保留持久化状态以便重启恢复", "info")
            except Exception as e:
                logging.warning(f"状态清理异常（不影响关闭）: {e}")

            try:
                # 关闭企业微信告警服务会话
                if hasattr(container, 'wechat_alert_service') and container.wechat_alert_service:
                    await container.wechat_alert_service.close()
                container.cleanup()
            except Exception as e:
                logging.warning(f"容器清理异常（不影响关闭）: {e}")

        except Exception as e:
            logging.error(f"资源清理失败: {e}", exc_info=True)


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""
    app = FastAPI(
        title="富途量化交易系统 API",
        description="简化版富途量化交易系统的 RESTful API",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json"
    )

    # 注册全局异常处理器
    register_exception_handlers(app)

    # 配置 CORS（从环境变量读取允许的来源，默认仅允许本地开发地址）
    cors_origins_str = os.environ.get('CORS_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000')
    cors_origins = [o.strip() for o in cors_origins_str.split(',') if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 健康检查端点
    @app.get("/health", tags=["系统"])
    async def health_check():
        """健康检查"""
        return {"status": "ok", "framework": "fastapi"}

    # 注册路由
    from .routers import register_routers
    register_routers(app)

    return app


# 创建应用实例
fastapi_app = create_app()
