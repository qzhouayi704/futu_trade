#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线数据管理服务（兼容层）
保持原有 KlineDataService 接口不变，内部委托给 KlineDataFetcher 和 KlineProgressManager。
所有外部调用方无需修改导入路径。
"""

import logging
from typing import Dict, Any, List, Optional, Callable

from ....database.core.db_manager import DatabaseManager
from ....config.config import Config
from ....api.futu_client import FutuClient
from .kline_data_fetcher import KlineDataFetcher
from .kline_progress import KlineProgressManager


class KlineDataService:
    """K线数据管理服务（兼容层）"""

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient, config: Config):
        # 创建实际的服务实例
        self._data_fetcher = KlineDataFetcher(db_manager, futu_client, config)
        self._progress_manager = KlineProgressManager(
            self._data_fetcher, db_manager, futu_client, config
        )

        # 暴露子服务引用（供 activity_filter 等直接访问）
        self.fetcher = self._data_fetcher.fetcher
        self.parser = self._data_fetcher.parser
        self.storage = self._data_fetcher.storage
        self.rate_limiter = self._data_fetcher.rate_limiter
        self.config = config
        self.futu_client = futu_client  # 暴露 futu_client 供 background_kline_task 使用

    # ==================== 额度管理（委托给 data_fetcher） ====================

    def get_quota_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        """获取K线额度信息（带缓存）"""
        return self._data_fetcher.get_quota_info(force_refresh)

    def get_cached_quota_info(self) -> Optional[Dict[str, Any]]:
        """获取缓存的额度信息"""
        return self._data_fetcher.get_cached_quota_info()

    def clear_quota_cache(self):
        """清除额度缓存"""
        self._data_fetcher.clear_quota_cache()

    # ==================== 初始化（委托给对应模块） ====================

    def initialize_kline_data(self, force_refresh: bool = False) -> Dict[str, Any]:
        """初始化K线数据（快速模式，30天）"""
        return self._data_fetcher.initialize_kline_data(force_refresh)

    def initialize_kline_for_all_stocks(self,
                                        days: int = None,
                                        max_stocks: int = None,
                                        progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """为所有目标股票初始化K线数据（默认半年）"""
        return self._progress_manager.initialize_kline_for_all_stocks(
            days, max_stocks, progress_callback
        )

    def get_init_progress(self) -> Dict[str, Any]:
        """获取初始化进度"""
        return self._progress_manager.get_init_progress()

    # ==================== 数据清理（委托给 data_fetcher） ====================

    def clean_today_incomplete_kline(self) -> Dict[str, Any]:
        """清理今天的不完整K线数据（考虑时差）"""
        return self._data_fetcher.clean_today_incomplete_kline()

    def clean_incomplete_kline_by_date(self, date_str: str) -> Dict[str, Any]:
        """清理指定日期的K线数据"""
        return self._data_fetcher.clean_incomplete_kline_by_date(date_str)

    # ==================== 内部方法（委托给 data_fetcher） ====================

    def _has_enough_kline_data(self, stock_code: str, required_days: int) -> bool:
        """检查是否有足够的K线数据"""
        return self._data_fetcher._has_enough_kline_data(stock_code, required_days)

    def _fetch_kline_data(self, stock_code: str, days: int) -> List[Dict]:
        """获取K线数据"""
        return self._data_fetcher._fetch_kline_data(stock_code, days)

    def _save_kline_data(self, stock_code: str, kline_data: List[Dict]) -> int:
        """保存K线数据"""
        return self._data_fetcher._save_kline_data(stock_code, kline_data)
