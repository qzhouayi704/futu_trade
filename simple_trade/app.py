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

    try:
        # 启动时初始化
        config = ConfigManager.load_config("simple_trade/config.json")
        state_manager = get_state_manager()
        state_manager.set_quotes_ttl(config.update_interval)

        # [测试模式] 强制设置为港股市场
        from .utils.market_helper import MarketTimeHelper
        MarketTimeHelper.set_force_market('HK')

        # 初始化服务容器（不传入 Flask app，因为是 FastAPI 模式）
        container = ServiceContainer(config, app=None)
        container.initialize_all()

        # 注入主事件循环到参数缓存管理器（使其能从工作线程安全提交协程）
        if hasattr(container, 'strategy_monitor_service') and container.strategy_monitor_service:
            container.strategy_monitor_service.params_cache_manager.set_event_loop(
                asyncio.get_running_loop()
            )

        # 获取 Socket 管理器（全局单例）
        from .websocket import get_socket_manager as _get_socket_manager
        socket_manager = _get_socket_manager()

        # 初始化统一行情处理管道（显式依赖注入）
        quote_pipeline = QuotePipeline(
            container=container,
            socket_manager=socket_manager,
            state_manager=state_manager,
            risk_coordinator=getattr(container, 'risk_coordinator', None),
            price_monitor=getattr(container, 'price_monitor_service', None),
            strategy_monitor=getattr(container, 'strategy_monitor_service', None),
        )

        # 初始化系统协调器（替代旧的 MonitorCoordinator 和 BroadcastCoordinator）
        system_coordinator = SystemCoordinator(
            container, state_manager
        )

        # 通过 dependencies 注册所有服务实例
        dependencies.set_container(container)
        dependencies.set_state_manager(state_manager)
        dependencies.set_system_coordinator(system_coordinator)
        dependencies.set_quote_pipeline(quote_pipeline)
        dependencies.set_socket_manager(socket_manager)

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
        dependencies.set_quote_pusher(quote_pusher)

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
            asyncio.create_task(_start_quote_pusher_background())
            # 启动 Scalping 引擎自动启动任务（传递 quote_pusher 参数）
            asyncio.create_task(auto_start_scalping(container, state_manager, quote_pusher))
            print_status("【行情推送】正在后台启动订阅（HTTP 服务已就绪）...", "info")
        else:
            logging.warning("系统数据初始化失败，跳过行情推送启动")
            print_status("【行情推送】跳过启动（初始化失败）", "warn")

        yield

    except Exception as e:
        logging.error(f"应用启动失败: {e}", exc_info=True)
        print_status(f"【系统】启动失败: {e}", "error")
        raise

    finally:
        # 确保清理所有资源
        try:
            if quote_pusher_started and quote_pusher:
                await quote_pusher.stop()

            # 停止 Scalping 引擎
            try:
                _container = dependencies.get_container()
                scalping_engine = _container.scalping_engine
                if scalping_engine is not None:
                    await scalping_engine.stop()
                    logging.info("ScalpingEngine 已停止")
            except Exception as e:
                logging.error(f"ScalpingEngine 停止失败: {e}", exc_info=True)

            try:
                coordinator = dependencies.get_system_coordinator()
                state = dependencies.get_state()
                if state.is_running():
                    await coordinator.stop()
            except Exception:
                pass

            try:
                container = dependencies.get_container()
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
