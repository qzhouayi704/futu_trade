#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心服务初始化器 - 负责数据库、富途客户端等核心组件的初始化
"""

import asyncio
import time
import logging
from typing import Optional

from ...config.config import ConfigManager
from ...database.core.db_manager import DatabaseManager
from ...api.futu_client import FutuClient
from ...api.subscription_manager import SubscriptionManager
from ...api.quote_service import QuoteService
from ...api.stock_data import StockDataService
from ...services.market_data.quote_cache import QuoteCache
from ...utils.logger import print_status
from ..subscription.subscription_recovery_helper import SubscriptionRecoveryHelper
from ..connection.global_connection_manager import GlobalConnectionManager
from ..cache.unified_data_cache import UnifiedDataCache
from ..monitoring.global_monitoring_dashboard import GlobalMonitoringDashboard

# 富途连接重试配置
FUTU_RETRY_INTERVAL = 10  # 每次重试间隔（秒）
FUTU_MAX_RETRIES = 30     # 最大重试次数（共等待约5分钟）


class CoreServices:
    """核心服务容器 - 管理数据库、API客户端等基础组件"""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.db_manager: Optional[DatabaseManager] = None
        self.futu_client: Optional[FutuClient] = None
        self.subscription_manager: Optional[SubscriptionManager] = None
        self.quote_service: Optional[QuoteService] = None
        self.stock_data_service: Optional[StockDataService] = None
        self.quote_cache: QuoteCache = QuoteCache()

        # 全局服务
        self.global_subscription_coordinator: Optional[SubscriptionRecoveryHelper] = None
        self.global_connection_manager: Optional[GlobalConnectionManager] = None

        # 缓存
        self.unified_cache: Optional[UnifiedDataCache] = None
        # P5-2: 懒加载，访问 /api/monitoring/global 时才创建
        self._global_monitoring_dashboard: Optional[GlobalMonitoringDashboard] = None

    def initialize(self):
        """初始化核心服务"""
        logging.info("开始初始化核心服务...")

        # 1. 数据库管理器（含建表和自动迁移）
        self.db_manager = DatabaseManager(self.config.database_path)
        self.db_manager.init_database()
        logging.info("数据库管理器初始化完成")

        # 2. 富途客户端（含连接重试）
        self.futu_client = FutuClient(
            host=self.config.futu_host,
            port=self.config.futu_port
        )
        self._connect_futu_with_retry()

        # 2b. 交易日历：显式注入富途客户端并预热（节假日闸依赖）
        self._init_trading_calendar()

        # 3. 订阅管理器
        self.subscription_manager = SubscriptionManager(
            self.futu_client,
            db_manager=self.db_manager,
            config=self.config
        )
        logging.info("订阅管理器初始化完成")

        # 注册重连回调：重连后清除所有内存订阅状态
        def _on_futu_reconnect():
            logging.warning("OpenD重连成功，清除所有内存订阅状态以触发重新订阅")
            all_stocks = list(self.subscription_manager.subscribed_stocks)
            if all_stocks:
                self.subscription_manager.force_clear_subscriptions(all_stocks)

        self.futu_client.register_reconnect_callback(_on_futu_reconnect)
        logging.info("重连回调已注册")

        # P5-2: 简化为 SubscriptionRecoveryHelper
        self.global_subscription_coordinator = SubscriptionRecoveryHelper(
            self.futu_client,
            self.subscription_manager
        )
        logging.info("订阅恢复助手初始化完成")

        # 全局连接管理器
        self.global_connection_manager = GlobalConnectionManager(
            self.futu_client,
            self.global_subscription_coordinator
        )
        logging.info("全局连接管理器初始化完成")

        # 统一缓存层
        self.unified_cache = UnifiedDataCache(self.db_manager)
        logging.info("统一缓存层初始化完成")

        # P5-2: GlobalMonitoringDashboard 改为懒加载，跳过初始化
        logging.info("全局监控面板将在首次访问时初始化（懒加载）")

        # 4. 行情服务
        self.quote_service = QuoteService(self.futu_client, self.subscription_manager)
        logging.info("行情服务初始化完成")

        # 5. 股票数据服务
        self.stock_data_service = StockDataService(
            futu_client=self.futu_client,
            db_manager=self.db_manager,
            quote_service=self.quote_service
        )
        logging.info("股票数据服务初始化完成")

        logging.info("核心服务初始化完成")

    def _connect_futu_with_retry(self):
        """连接富途API，失败时提示用户并等待重试（同步版本）

        Raises:
            RuntimeError: 超过最大重试次数仍无法连接
        """
        for attempt in range(1, FUTU_MAX_RETRIES + 1):
            if self.futu_client.connect():
                print_status("富途API连接成功", "ok")
                return

            remaining = FUTU_MAX_RETRIES - attempt
            print_status(
                f"富途API连接失败，请确保 OpenD 已启动并登录。"
                f"{FUTU_RETRY_INTERVAL}秒后重试... "
                f"(第{attempt}次，剩余{remaining}次)",
                "warn"
            )
            time.sleep(FUTU_RETRY_INTERVAL)

        raise RuntimeError(
            f"富途API连接失败：已重试{FUTU_MAX_RETRIES}次（共等待"
            f"{FUTU_MAX_RETRIES * FUTU_RETRY_INTERVAL}秒）。"
            f"请启动 OpenD 后重新运行程序。"
        )

    def _init_trading_calendar(self):
        """向交易日历显式注入富途客户端并预热当天交易日缓存。

        历史问题：交易日历此前只靠懒解析 get_container().futu_client，节假日闸
        首次调用时可能拿不到可用客户端而静默 fail-open，导致港股节假日（如端午）
        仍被当作交易日、整条行情管道照常产信号。这里在客户端连接成功后主动注入，
        并触发一次刷新做预热，刷新结果（成功/失败）均落日志，杜绝静默失败。
        """
        try:
            from ...utils.trading_calendar import get_trading_calendar
            cal = get_trading_calendar()
            cal.set_futu_client(self.futu_client)
            # 预热：触发一次刷新（成功会打印「[交易日历] HK 已刷新…」）
            hk_trading = cal.is_trading_day('HK')
            cal.is_trading_day('US')
            logging.info(
                "交易日历已注入富途客户端并预热（今日 HK 交易日=%s）", hk_trading
            )
        except Exception as e:
            # fail-open 兜底：日历问题绝不阻断启动
            logging.warning("交易日历初始化失败（fail-open 兜底）: %s", e)

    async def async_initialize(self):
        """异步初始化核心服务（不阻塞事件循环）"""
        logging.info("开始异步初始化核心服务...")

        # 1. 数据库管理器（CPU 密集型，放到线程池）
        loop = asyncio.get_running_loop()
        self.db_manager = await loop.run_in_executor(
            None, lambda: DatabaseManager(self.config.database_path)
        )
        await loop.run_in_executor(None, self.db_manager.init_database)
        logging.info("数据库管理器初始化完成")

        # 2. 富途客户端（含异步连接重试）
        self.futu_client = FutuClient(
            host=self.config.futu_host,
            port=self.config.futu_port
        )
        await self._connect_futu_with_retry_async()

        # 2b. 交易日历：显式注入富途客户端并预热（节假日闸依赖）
        self._init_trading_calendar()

        # 3-5. 其余服务初始化（轻量级，直接同步）
        self.subscription_manager = SubscriptionManager(
            self.futu_client, db_manager=self.db_manager, config=self.config
        )

        # 注册重连回调：重连后清除所有内存订阅状态
        def _on_futu_reconnect():
            logging.warning("OpenD重连成功，清除所有内存订阅状态以触发重新订阅")
            all_stocks = list(self.subscription_manager.subscribed_stocks)
            if all_stocks:
                self.subscription_manager.force_clear_subscriptions(all_stocks)

        self.futu_client.register_reconnect_callback(_on_futu_reconnect)
        logging.info("重连回调已注册")

        # P5-2: 简化为 SubscriptionRecoveryHelper
        self.global_subscription_coordinator = SubscriptionRecoveryHelper(
            self.futu_client,
            self.subscription_manager
        )
        logging.info("订阅恢复助手初始化完成")

        self.global_connection_manager = GlobalConnectionManager(
            self.futu_client,
            self.global_subscription_coordinator
        )
        logging.info("全局连接管理器初始化完成")

        # 统一缓存层
        self.unified_cache = UnifiedDataCache(self.db_manager)
        logging.info("统一缓存层初始化完成")

        # P5-2: GlobalMonitoringDashboard 改为懒加载，跳过初始化
        logging.info("全局监控面板将在首次访问时初始化（懒加载）")

        self.quote_service = QuoteService(self.futu_client, self.subscription_manager)
        self.stock_data_service = StockDataService(
            futu_client=self.futu_client,
            db_manager=self.db_manager,
            quote_service=self.quote_service
        )
        logging.info("核心服务异步初始化完成")

    async def _connect_futu_with_retry_async(self):
        """异步连接富途API，使用 asyncio.sleep 不阻塞事件循环

        Raises:
            RuntimeError: 超过最大重试次数仍无法连接
        """
        loop = asyncio.get_running_loop()
        for attempt in range(1, FUTU_MAX_RETRIES + 1):
            # futu_client.connect() 是同步方法，放到线程池
            connected = await loop.run_in_executor(None, self.futu_client.connect)
            if connected:
                print_status("富途API连接成功", "ok")
                return

            remaining = FUTU_MAX_RETRIES - attempt
            print_status(
                f"富途API连接失败，请确保 OpenD 已启动并登录。"
                f"{FUTU_RETRY_INTERVAL}秒后重试... "
                f"(第{attempt}次，剩余{remaining}次)",
                "warn"
            )
            await asyncio.sleep(FUTU_RETRY_INTERVAL)

        raise RuntimeError(
            f"富途API连接失败：已重试{FUTU_MAX_RETRIES}次（共等待"
            f"{FUTU_MAX_RETRIES * FUTU_RETRY_INTERVAL}秒）。"
            f"请启动 OpenD 后重新运行程序。"
        )

    def cleanup(self):
        """清理核心服务资源"""
        try:
            if self.subscription_manager:
                try:
                    self.subscription_manager.unsubscribe_all()
                except Exception as e:
                    logging.debug(f"取消订阅失败（快速重启时可忽略）: {e}")

            if self.futu_client:
                self.futu_client.disconnect()

            logging.info("核心服务资源已清理")

        except Exception as e:
            logging.error(f"核心服务清理失败: {e}")

    @property
    def global_monitoring_dashboard(self):
        """P5-2: 懒加载全局监控面板"""
        if self._global_monitoring_dashboard is None:
            self._global_monitoring_dashboard = GlobalMonitoringDashboard(
                global_coordinator=self.global_subscription_coordinator,
                global_connection_manager=self.global_connection_manager,
                unified_cache=self.unified_cache,
            )
            logging.info("全局监控面板已懒加载初始化")
        return self._global_monitoring_dashboard

