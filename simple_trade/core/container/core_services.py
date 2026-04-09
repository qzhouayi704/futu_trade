#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心服务初始化器 - 负责数据库、富途客户端等核心组件的初始化
"""

import time
import logging
from typing import Optional

from ...config.config import ConfigManager
from ...database.core.db_manager import DatabaseManager
from ...api.futu_client import FutuClient
from ...api.subscription_manager import SubscriptionManager
from ...api.quote_service import QuoteService
from ...api.stock_data import StockDataService
from ...utils.logger import print_status

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

        # 3. 订阅管理器
        self.subscription_manager = SubscriptionManager(
            self.futu_client,
            db_manager=self.db_manager,
            config=self.config
        )
        logging.info("订阅管理器初始化完成")

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
        """连接富途API，失败时提示用户并等待重试

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

    def cleanup(self):
        """清理核心服务资源"""
        try:
            if self.subscription_manager:
                self.subscription_manager.unsubscribe_all()

            if self.futu_client:
                self.futu_client.disconnect()

            logging.info("核心服务资源已清理")

        except Exception as e:
            logging.error(f"核心服务清理失败: {e}")
