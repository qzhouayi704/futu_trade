"""
数据加载器（协调器，支持API获取）

负责协调各个数据加载组件，提供统一的数据加载接口。
支持从API获取数据，用于数据获取工具。

注意：回测系统应使用 BacktestOnlyDataLoader，不使用此加载器。
"""

import pandas as pd
from typing import List, Dict, Optional, Any
from datetime import datetime
import logging

from simple_trade.database.core.db_manager import DatabaseManager
from .loaders.base_loader import BaseDataLoader
from .loaders.kline_loader import KlineDataLoader
from .loaders.cache_manager import CacheManager


class BacktestDataLoader:
    """回测数据加载器（协调器）"""

    def __init__(
        self,
        db_manager: DatabaseManager,
        market: str = 'HK',
        use_stock_pool_only: bool = True,
        enable_api_fetch: bool = True,
        max_api_requests: int = 100,
        only_stocks_with_kline: bool = True,
        min_kline_days: int = 20
    ):
        """
        初始化数据加载器

        Args:
            db_manager: 数据库管理器
            market: 市场代码（HK/US）
            use_stock_pool_only: 是否只加载股票池中的股票
            enable_api_fetch: 是否启用API获取数据（默认True）
            max_api_requests: 最大API请求次数限制（默认100）
            only_stocks_with_kline: 是否只加载有K线数据的股票（默认True）
            min_kline_days: 最少需要的K线天数（默认20）
        """
        self.db_manager = db_manager
        self.market = market
        self.use_stock_pool_only = use_stock_pool_only
        self.enable_api_fetch = enable_api_fetch
        self.max_api_requests = max_api_requests
        self.only_stocks_with_kline = only_stocks_with_kline
        self.min_kline_days = min_kline_days
        self.logger = logging.getLogger(__name__)

        # 初始化子组件
        self.base_loader = BaseDataLoader(
            db_manager=db_manager,
            market=market,
            use_stock_pool_only=use_stock_pool_only,
            only_stocks_with_kline=only_stocks_with_kline,
            min_kline_days=min_kline_days
        )

        self.kline_loader = KlineDataLoader(
            db_manager=db_manager,
            enable_api_fetch=enable_api_fetch,
            max_api_requests=max_api_requests
        )

        self.cache_manager = CacheManager()

    def load_stock_list(self) -> List[Dict[str, Any]]:
        """
        加载股票列表

        Returns:
            股票列表，每个元素包含 {code, name, id}
        """
        return self.base_loader.load_stock_list()

    def load_kline_data(
        self,
        stock_code: str,
        start_date: datetime,
        end_date: datetime,
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        加载K线数据

        Args:
            stock_code: 股票代码（如 HK.00100）
            start_date: 开始日期
            end_date: 结束日期
            use_cache: 是否使用缓存

        Returns:
            K线数据DataFrame，包含以下列：
            - time_key: 日期字符串
            - open_price, close_price, high_price, low_price: 价格
            - volume: 成交量
            - turnover: 成交额
            - turnover_rate: 换手率
        """
        cache_key = f"{stock_code}_{start_date.date()}_{end_date.date()}"

        # 检查缓存
        if use_cache:
            cached_df = self.cache_manager.get_kline_cache(cache_key)
            if cached_df is not None:
                return cached_df

        # 加载数据
        df = self.kline_loader.load_kline_data(stock_code, start_date, end_date)

        # 缓存
        if use_cache:
            self.cache_manager.set_kline_cache(cache_key, df)

        return df

    def get_kline_at_date(
        self,
        stock_code: str,
        date: datetime,
        lookback_days: int
    ) -> List[Dict[str, Any]]:
        """
        获取指定日期及之前N天的K线数据

        Args:
            stock_code: 股票代码
            date: 目标日期
            lookback_days: 回看天数

        Returns:
            K线数据列表（按时间倒序）
        """
        return self.kline_loader.get_kline_at_date(
            stock_code, date, lookback_days, self.cache_manager
        )

    def get_stock_name(self, stock_code: str) -> str:
        """
        获取股票名称

        Args:
            stock_code: 股票代码

        Returns:
            股票名称
        """
        return self.base_loader.get_stock_name(stock_code)

    def get_api_stats(self) -> Dict[str, Any]:
        """获取API使用统计"""
        return self.kline_loader.get_api_stats()

    def clear_cache(self):
        """清除所有缓存"""
        self.base_loader.clear_cache()
        self.cache_manager.clear_kline_cache()
        self.logger.info("已清除所有缓存")
