#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块股票管理模块

负责板块与股票关联的查询操作（从数据库或API获取板块下的股票）。
从 plate_manager.py 拆分而来。
"""

import logging
from typing import Dict, Any, List

from ....database.core.db_manager import DatabaseManager
from ....api.futu_client import FutuClient
from ....api.market_types import ReturnCode
from ....utils.field_mapper import FieldMapper
from ....utils.rate_limiter import wait_for_api
from ....core.models import Stock


class PlateStockManager:
    """
    板块股票管理器

    职责：
    1. 获取板块下的股票列表（DB优先，API兜底）
    2. 获取所有目标板块的股票汇总
    3. 查询股票所属的板块
    """

    MAX_STOCKS_PER_PLATE = 50

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.logger = logging.getLogger(__name__)

    def get_plate_stocks(
        self, plate_code: str, max_stocks: int = None
    ) -> List[Dict[str, Any]]:
        """
        获取板块下的股票

        Args:
            plate_code: 板块代码
            max_stocks: 最大股票数量

        Returns:
            List: 股票列表
        """
        try:
            # 优先从数据库获取
            db_stocks = self._get_plate_stocks_from_db(plate_code)
            if db_stocks:
                if max_stocks:
                    db_stocks = db_stocks[:max_stocks]
                return db_stocks

            # 从API获取
            return self._fetch_plate_stocks_from_api(plate_code, max_stocks)

        except Exception as e:
            self.logger.error(f"获取板块 {plate_code} 股票失败: {e}")
            return []

    def _fetch_plate_stocks_from_api(
        self, plate_code: str, max_stocks: int = None
    ) -> List[Dict[str, Any]]:
        """从富途API获取板块股票"""
        stocks = []

        if not self.futu_client.is_available():
            self.logger.warning("富途API不可用，无法获取板块股票")
            return stocks

        if max_stocks is None:
            max_stocks = self.MAX_STOCKS_PER_PLATE

        # 频率控制已由 futu_client.get_plate_stock() 统一处理
        ret, stock_data = self.futu_client.get_plate_stock(plate_code)

        if ReturnCode.is_ok(ret) and stock_data is not None and not stock_data.empty:
            for _, stock_row in stock_data.head(max_stocks).iterrows():
                stock_info = FieldMapper.extract_stock_info(stock_row)
                if stock_info:
                    stocks.append(stock_info)

        return stocks

    def _get_plate_stocks_from_db(self, plate_code: str) -> List[Dict[str, Any]]:
        """从数据库获取板块股票"""
        stocks = []

        try:
            query = '''
                SELECT DISTINCT s.id, s.code, s.name, s.market
                FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.plate_code = ?
                ORDER BY s.code
            '''
            results = self.db_manager.execute_query(query, (plate_code,))

            stock_objects = [Stock.from_db_row(row) for row in results]
            stocks = [stock.to_dict() for stock in stock_objects]

            if stocks:
                self.logger.debug(
                    f"从数据库获取板块 {plate_code} 的 {len(stocks)} 只股票"
                )

        except Exception as e:
            self.logger.error(f"从数据库获取板块股票失败: {e}")

        return stocks

    def get_all_target_stocks(self, distinct: bool = True) -> List[Dict[str, Any]]:
        """
        获取所有目标板块的股票

        Args:
            distinct: 是否去重

        Returns:
            List: 股票列表
        """
        stocks = []

        try:
            if distinct:
                query = '''
                    SELECT DISTINCT s.id, s.code, s.name, s.market
                    FROM stocks s
                    INNER JOIN stock_plates sp ON s.id = sp.stock_id
                    INNER JOIN plates p ON sp.plate_id = p.id
                    WHERE p.is_target = 1
                    ORDER BY s.code
                '''
            else:
                query = '''
                    SELECT s.id, s.code, s.name, s.market, p.plate_name, p.category
                    FROM stocks s
                    INNER JOIN stock_plates sp ON s.id = sp.stock_id
                    INNER JOIN plates p ON sp.plate_id = p.id
                    WHERE p.is_target = 1
                    ORDER BY s.code, p.plate_name
                '''

            results = self.db_manager.execute_query(query)

            for row in results:
                stock_obj = Stock.from_db_row(row)
                stock = stock_obj.to_dict()
                if not distinct and len(row) > 4:
                    stock['plate_name'] = row[4]
                    stock['category'] = row[5]
                stocks.append(stock)

            self.logger.info(f"获取目标股票: {len(stocks)} 只 (去重={distinct})")

        except Exception as e:
            self.logger.error(f"获取目标股票失败: {e}")

        return stocks

    def get_stock_plates(self, stock_code: str) -> List[Dict[str, Any]]:
        """
        获取股票所属的所有板块

        Args:
            stock_code: 股票代码

        Returns:
            List: 板块列表
        """
        plates = []

        try:
            query = '''
                SELECT p.id, p.plate_code, p.plate_name, p.market, p.category
                FROM plates p
                INNER JOIN stock_plates sp ON p.id = sp.plate_id
                INNER JOIN stocks s ON sp.stock_id = s.id
                WHERE s.code = ?
                ORDER BY p.priority DESC
            '''
            results = self.db_manager.execute_query(query, (stock_code,))

            for row in results:
                plates.append({
                    'id': row[0],
                    'plate_code': row[1],
                    'plate_name': row[2],
                    'market': row[3],
                    'category': row[4] or ''
                })

        except Exception as e:
            self.logger.error(f"获取股票 {stock_code} 的板块失败: {e}")

        return plates
