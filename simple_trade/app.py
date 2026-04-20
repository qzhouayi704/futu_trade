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
- build_stock_list_for_scalping + _auto_start_scalping → services/scalping/auto_starter.py
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
from .services.scalping.auto_starter import auto_start_scalping
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
        # 版本标识 - 修改此值可确认代码是否正确加载
        BUILD_VERSION = "2026.04.14-v3"
        print_status(f"代码版本: {BUILD_VERSION}", "ok")
        logging.info(f"===== 系统启动 BUILD={BUILD_VERSION} =====")

        # 启动时初始化
        config = ConfigManager.load_config("simple_trade/config.json")
        state_manager = get_state_manager()
        state_manager.set_quotes_ttl(config.update_interval)

        # [测试模式] 强制设置为港股市场
        from .utils.market_helper import MarketTimeHelper
        MarketTimeHelper.set_force_market('HK')

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
            # 启动 Scalping 引擎自动启动任务（传递 quote_pusher + socket_manager）
            _track(auto_start_scalping(container, state_manager, quote_pusher, socket_manager), name="scalping_auto_start")
            print_status("【行情推送】正在后台启动订阅（HTTP 服务已就绪）...", "info")

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

            # 自动恢复监控：如果上次关闭前监控在运行，则自动重启
            if state_manager.was_running_before_shutdown():
                async def _auto_resume_monitoring():
                    """后台自动恢复监控"""
                    try:
                        # 等待行情推送启动完成（给 3 秒缓冲）
                        await asyncio.sleep(3)
                        print_status("【自动恢复】检测到上次监控未正常关闭，正在自动恢复...", "info")
                        await system_coordinator.start()
                        print_status("【自动恢复】监控已自动恢复", "ok")
                    except Exception as e:
                        logging.error(f"自动恢复监控失败: {e}", exc_info=True)
                        print_status(f"【自动恢复】监控恢复失败: {e}", "error")
                _track(_auto_resume_monitoring(), name="auto_resume_monitoring")

            # 发送企业微信启动通知
            if hasattr(container, 'wechat_alert_service') and container.wechat_alert_service:
                try:
                    await container.wechat_alert_service.alert_system_started()
                except Exception as e:
                    logging.warning(f"企业微信启动通知发送失败: {e}")
        else:
            logging.warning("系统数据初始化失败，跳过行情推送启动")
            print_status("【行情推送】跳过启动（初始化失败）", "warn")

        yield

    except Exception as e:
        logging.error(f"应用启动失败: {e}", exc_info=True)
        print_status(f"【系统】启动失败: {e}", "error")
        raise

    finally:
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

            # 停止 Scalping 引擎（含进程模式的子进程终止）
            try:
                scalping_engine = container.scalping_engine if container else None
                if scalping_engine is not None:
                    from .services.scalping.scalping_process_manager import ScalpingProcessManager
                    if isinstance(scalping_engine, ScalpingProcessManager):
                        await asyncio.wait_for(scalping_engine.shutdown(), timeout=5)
                        logging.info("Scalping 子进程已终止")
                    else:
                        await asyncio.wait_for(scalping_engine.stop(), timeout=5)
                        logging.info("ScalpingEngine 已停止")
            except asyncio.TimeoutError:
                logging.warning("Scalping 停止超时(5s)，强制继续")
            except Exception as e:
                logging.error(f"ScalpingEngine 停止失败: {e}", exc_info=True)

            try:
                state = state_manager
                if state.is_running():
                    # 进程关闭时只清理内存状态，不持久化 is_running=false
                    # 这样重启后 was_running_before_shutdown() 仍返回 true，可以自动恢复
                    state._is_running = False
                    print_status("【系统协调器】进程关闭，保留持久化状态以便重启恢复", "info")
            except Exception:
                pass

            try:
                pass  # container 已在局部作用域
                # 关闭企业微信告警服务会话
                if hasattr(container, 'wechat_alert_service') and container.wechat_alert_service:
                    await container.wechat_alert_service.close()
                container.cleanup()
            except Exception:
                pass

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

    # 配置 CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
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
