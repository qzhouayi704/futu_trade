#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据服务初始化器 - 负责数据初始化、实时服务、K线服务等
"""

import logging
from typing import Optional

from ...services import (
    DataInitializer,
    KlineDataService,
    StockPoolService,
    PlateManager,
)
from ...services.subscription.subscription_helper import SubscriptionHelper
from ...services.realtime.realtime_query import RealtimeQuery
from .core_services import CoreServices


class DataServices:
    """数据服务容器 - 管理数据初始化和查询服务"""

    def __init__(self, core: CoreServices, container=None):
        self.core = core
        self.container = container
        self.data_initializer: Optional[DataInitializer] = None
        self.subscription_helper: Optional[SubscriptionHelper] = None
        self.realtime_query: Optional[RealtimeQuery] = None
        self.realtime_service = None  # realtime_query 的别名，保持兼容
        self.kline_service: Optional[KlineDataService] = None
        self.stock_pool_service: Optional[StockPoolService] = None
        self.plate_manager: Optional[PlateManager] = None

    def initialize(self):
        """初始化数据服务"""
        logging.info("开始初始化数据服务...")

        # 1. 板块管理器
        self.plate_manager = PlateManager(
            db_manager=self.core.db_manager,
            futu_client=self.core.futu_client
        )
        logging.info("板块管理器初始化完成")

        # 2. 数据初始化服务
        self.data_initializer = DataInitializer(
            db_manager=self.core.db_manager,
            futu_client=self.core.futu_client,
            config=self.core.config
        )
        logging.info("数据初始化服务初始化完成")

        # 3. 订阅管理服务
        self.subscription_helper = SubscriptionHelper(
            db_manager=self.core.db_manager,
            futu_client=self.core.futu_client,
            subscription_manager=self.core.subscription_manager,
            quote_service=self.core.quote_service,
            config=self.core.config,
            container=self.container
        )

        # 4. 实时数据查询服务
        self.realtime_query = RealtimeQuery(
            db_manager=self.core.db_manager,
            futu_client=self.core.futu_client,
            subscription_manager=self.core.subscription_manager,
            quote_service=self.core.quote_service,
            config=self.core.config
        )

        # 已弃用：realtime_service 别名保留仅为向后兼容
        # 新代码请使用 subscription_helper（订阅管理）或 realtime_query（数据查询）
        self.realtime_service = self.subscription_helper
        logging.info("订阅管理 + 实时查询服务初始化完成")

        # 5. K线数据服务
        self.kline_service = KlineDataService(
            db_manager=self.core.db_manager,
            futu_client=self.core.futu_client,
            config=self.core.config
        )
        logging.info("K线数据服务初始化完成")

        # 6. 股票池服务
        self.stock_pool_service = StockPoolService(
            db_manager=self.core.db_manager,
            futu_client=self.core.futu_client,
            config=self.core.config
        )
        logging.info("股票池服务初始化完成")

        logging.info("数据服务初始化完成")
