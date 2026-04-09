"""
基础数据加载器

负责加载股票列表、股票名称查询等基础功能
"""

from typing import List, Dict, Any, Optional
import logging

from simple_trade.database.core.db_manager import DatabaseManager


class BaseDataLoader:
    """基础数据加载器"""

    def __init__(
        self,
        db_manager: DatabaseManager,
        market: str = 'HK',
        use_stock_pool_only: bool = True,
        only_stocks_with_kline: bool = True,
        min_kline_days: int = 20
    ):
        """
        初始化基础数据加载器

        Args:
            db_manager: 数据库管理器
            market: 市场代码（HK/US）
            use_stock_pool_only: 是否只加载股票池中的股票
            only_stocks_with_kline: 是否只加载有K线数据的股票
            min_kline_days: 最少需要的K线天数
        """
        self.db_manager = db_manager
        self.market = market
        self.use_stock_pool_only = use_stock_pool_only
        self.only_stocks_with_kline = only_stocks_with_kline
        self.min_kline_days = min_kline_days
        self.logger = logging.getLogger(__name__)

        # 缓存
        self._stock_list_cache: Optional[List[Dict[str, Any]]] = None
        self._stock_name_cache: Dict[str, str] = {}

    def load_stock_list(self) -> List[Dict[str, Any]]:
        """
        加载股票列表

        Returns:
            股票列表，每个元素包含 {code, name, id, market, plate_name}
        """
        if self._stock_list_cache is not None:
            return self._stock_list_cache

        self.logger.info(
            f"加载股票列表 (market={self.market}, "
            f"use_pool={self.use_stock_pool_only})"
        )

        # 从数据库加载股票
        stock_tuples = self.db_manager.stock_queries.get_stocks()

        if not stock_tuples:
            self.logger.warning("股票列表为空")
            self._stock_list_cache = []
            return []

        # 将元组转换为字典
        stocks = self._convert_stock_tuples(stock_tuples)

        # 过滤市场
        if self.market:
            stocks = self._filter_by_market(stocks)

        # 过滤：只保留有K线数据的股票
        if self.only_stocks_with_kline:
            stocks = self._filter_stocks_with_kline(stocks)

        self.logger.info(f"最终加载了 {len(stocks)} 只股票")
        self._stock_list_cache = stocks
        return stocks

    def _convert_stock_tuples(
        self,
        stock_tuples: List[tuple]
    ) -> List[Dict[str, Any]]:
        """将股票元组转换为字典"""
        stocks = []
        for row in stock_tuples:
            stock = {
                'id': row[0],
                'code': row[1],
                'name': row[2],
                'market': row[3],
                'plate_name': row[4] if len(row) > 4 else None
            }
            stocks.append(stock)
        return stocks

    def _filter_by_market(
        self,
        stocks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """按市场过滤股票"""
        return [
            s for s in stocks
            if s.get('code', '').startswith(self.market + '.')
        ]

    def _filter_stocks_with_kline(
        self,
        stocks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """过滤出有足够K线数据的股票"""
        import sqlite3

        try:
            # 直接查询数据库
            conn = sqlite3.connect(self.db_manager.database_path)
            cursor = conn.cursor()

            # 查询每只股票的K线数量
            cursor.execute('''
                SELECT stock_code, COUNT(*) as cnt
                FROM kline_data
                GROUP BY stock_code
                HAVING cnt >= ?
            ''', (self.min_kline_days,))

            # 构建有K线数据的股票代码集合
            stocks_with_kline_set = {row[0] for row in cursor.fetchall()}
            conn.close()

            # 过滤股票列表
            filtered_stocks = [
                s for s in stocks
                if s.get('code') in stocks_with_kline_set
            ]

            self.logger.info(
                f"过滤后有K线数据的股票: "
                f"{len(filtered_stocks)}/{len(stocks)}"
            )

            return filtered_stocks

        except Exception as e:
            self.logger.error(f"过滤有K线数据的股票失败: {e}")
            return stocks  # 失败时返回原列表

    def get_stock_name(self, stock_code: str) -> str:
        """
        获取股票名称

        Args:
            stock_code: 股票代码

        Returns:
            股票名称
        """
        # 检查缓存
        if stock_code in self._stock_name_cache:
            return self._stock_name_cache[stock_code]

        # 从股票列表中查找
        stocks = self.load_stock_list()
        for stock in stocks:
            if stock.get('code') == stock_code:
                name = stock.get('name', stock_code)
                self._stock_name_cache[stock_code] = name
                return name

        # 如果找不到，返回股票代码
        return stock_code

    def clear_cache(self):
        """清除缓存"""
        self._stock_list_cache = None
        self._stock_name_cache.clear()
        self.logger.info("已清除股票列表缓存")
