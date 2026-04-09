#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块管理服务 - 兼容层

保持原有 PlateManager 接口不变，内部委托给：
- PlateFetcher: 板块数据获取
- PlateStockManager: 板块股票管理

新代码应直接使用 PlateFetcher 或 PlateStockManager。
"""

import logging
from typing import Dict, Any, List

from ....database.core.db_manager import DatabaseManager
from ....api.futu_client import FutuClient
from .plate_fetcher import PlateFetcher
from .plate_stock_manager import PlateStockManager


class PlateManager:
    """
    板块管理服务 - 兼容层

    组合 PlateFetcher 和 PlateStockManager，
    保持原有接口供现有调用方使用。
    """

    # 保留原有常量，供外部可能的引用
    MAX_STOCKS_PER_PLATE = PlateStockManager.MAX_STOCKS_PER_PLATE
    API_REQUEST_DELAY = PlateFetcher.API_REQUEST_DELAY

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient = None):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.fetcher = PlateFetcher(db_manager, futu_client)
        self.stock_manager = PlateStockManager(db_manager, futu_client)
        self.plate_matcher = self.fetcher.plate_matcher
        self.logger = logging.getLogger(__name__)

    # ---- 委托给 PlateFetcher ----

    def get_target_plates(self, from_db: bool = True) -> Dict[str, Any]:
        return self.fetcher.get_target_plates(from_db)

    def refresh_plates(self, force_api: bool = False) -> Dict[str, Any]:
        return self.fetcher.refresh_plates(force_api)

    def get_plate_categories(self) -> List[str]:
        return self.fetcher.get_plate_categories()

    def get_plates_by_category(self, category: str) -> List[Dict[str, Any]]:
        return self.fetcher.get_plates_by_category(category)

    # ---- 委托给 PlateStockManager ----

    def get_plate_stocks(
        self, plate_code: str, max_stocks: int = None
    ) -> List[Dict[str, Any]]:
        return self.stock_manager.get_plate_stocks(plate_code, max_stocks)

    def get_all_target_stocks(self, distinct: bool = True) -> List[Dict[str, Any]]:
        return self.stock_manager.get_all_target_stocks(distinct)

    def get_stock_plates(self, stock_code: str) -> List[Dict[str, Any]]:
        return self.stock_manager.get_stock_plates(stock_code)
