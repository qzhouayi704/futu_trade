#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票初始化服务
负责股票数据的获取和保存
"""

import logging
from typing import Dict, Any, List, Set
from ...database.core.db_manager import DatabaseManager
from ...api.futu_client import FutuClient
from ...api.market_types import ReturnCode
from ...utils.field_mapper import FieldMapper
from ...utils.rate_limiter import wait_for_api, record_api_call


class StockInitializerService:
    """
    股票初始化服务

    职责：
    1. 获取板块下的股票列表
    2. 保存股票数据到数据库
    3. 维护股票-板块多对多关系
    4. 更新板块的股票数量统计
    """

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.logger = logging.getLogger(__name__)

    def get_plate_stocks(self, plate_code: str, market_code: str) -> List[Dict[str, Any]]:
        """
        获取板块下的股票

        Args:
            plate_code: 板块代码
            market_code: 市场代码

        Returns:
            List: 股票列表
        """
        stocks = []

        try:
            # 使用频率控制器
            wait_time = wait_for_api('get_plate_stock')
            if wait_time > 0:
                self.logger.debug(f"等待API可用: {wait_time:.1f}秒")

            ret, stock_data = self.futu_client.get_plate_stock(plate_code)
            record_api_call('get_plate_stock')

            if ReturnCode.is_ok(ret) and stock_data is not None and not stock_data.empty:
                for _, stock_row in stock_data.iterrows():
                    stock_info = FieldMapper.extract_stock_info(stock_row, market_code)
                    if stock_info:
                        stocks.append(stock_info)

        except Exception as e:
            self.logger.warning(f"获取板块 {plate_code} 股票失败: {e}")

        return stocks

    def save_stocks_with_relations(
        self,
        stocks: Dict[str, Dict[str, Any]],
        stock_plate_map: Dict[str, Set[int]]
    ):
        """
        保存股票和股票-板块关联关系

        Args:
            stocks: 股票信息字典 (code -> stock_info)
            stock_plate_map: 股票-板块关系 (code -> plate_ids)
        """
        try:
            for code, stock_info in stocks.items():
                # 插入或更新股票
                self.db_manager.execute_update('''
                    INSERT OR REPLACE INTO stocks (code, name, market)
                    VALUES (?, ?, ?)
                ''', (code, stock_info.get('name', ''), stock_info.get('market', '')))

                # 获取股票ID
                result = self.db_manager.execute_query(
                    'SELECT id FROM stocks WHERE code = ?', (code,)
                )
                if not result:
                    continue

                stock_id = result[0][0]

                # 保存股票-板块关联
                plate_ids = stock_plate_map.get(code, set())
                for plate_id in plate_ids:
                    try:
                        self.db_manager.execute_update('''
                            INSERT OR IGNORE INTO stock_plates (stock_id, plate_id)
                            VALUES (?, ?)
                        ''', (stock_id, plate_id))
                    except Exception as e:
                        self.logger.debug(f"关联已存在或插入失败: stock={code}, plate={plate_id}")

            # 更新每个板块的股票数量
            self.update_plate_stock_counts()

            self.logger.info(f"成功保存 {len(stocks)} 只股票及其板块关联")

        except Exception as e:
            self.logger.error(f"保存股票和关联失败: {e}")

    def update_plate_stock_counts(self):
        """更新每个板块的股票数量"""
        try:
            self.db_manager.execute_update('''
                UPDATE plates SET stock_count = (
                    SELECT COUNT(DISTINCT sp.stock_id)
                    FROM stock_plates sp
                    WHERE sp.plate_id = plates.id
                )
            ''')
        except Exception as e:
            self.logger.warning(f"更新板块股票数量失败: {e}")

    def get_target_stocks(self, distinct: bool = True) -> List[Dict[str, Any]]:
        """
        获取目标板块的股票列表

        Args:
            distinct: 是否去重（默认True）

        Returns:
            List: 股票列表
        """
        stocks = []

        try:
            if distinct:
                # 去重查询
                query = '''
                    SELECT DISTINCT s.id, s.code, s.name, s.market
                    FROM stocks s
                    INNER JOIN stock_plates sp ON s.id = sp.stock_id
                    INNER JOIN plates p ON sp.plate_id = p.id
                    WHERE p.is_target = 1
                    ORDER BY s.code
                '''
                results = self.db_manager.execute_query(query)

                for row in results:
                    stocks.append({
                        'id': row[0],
                        'code': row[1],
                        'name': row[2],
                        'market': row[3]
                    })
            else:
                # 不去重，包含板块信息
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
                    stocks.append({
                        'id': row[0],
                        'code': row[1],
                        'name': row[2],
                        'market': row[3],
                        'plate_name': row[4],
                        'category': row[5]
                    })

            self.logger.debug(f"获取目标股票: {len(stocks)} 只 (去重={distinct})")

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
                    'category': row[4]
                })

        except Exception as e:
            self.logger.error(f"获取股票 {stock_code} 的板块失败: {e}")

        return plates

    def fetch_stocks_for_plates(
        self,
        plates: List[Dict[str, Any]]
    ) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Set[int]], int]:
        """
        获取多个板块的所有股票

        Args:
            plates: 板块列表（需包含 id, code, name, market 字段）

        Returns:
            tuple: (股票字典, 股票-板块映射, 总股票数)
                - 股票字典: code -> stock_info
                - 股票-板块映射: code -> plate_ids
                - 总股票数: 包含重复的总数
        """
        all_stocks: Dict[str, Dict[str, Any]] = {}
        stock_plate_map: Dict[str, Set[int]] = {}
        total_count = 0

        for i, plate in enumerate(plates):
            plate_name = plate['name']
            plate_id = plate['id']

            self.logger.info(f"获取板块股票 ({i+1}/{len(plates)}): {plate_name}")

            stocks = self.get_plate_stocks(plate['code'], plate['market'])

            for stock in stocks:
                code = stock['code']

                # 保存股票信息（去重）
                if code not in all_stocks:
                    all_stocks[code] = stock
                    stock_plate_map[code] = set()

                # 记录股票-板块关系
                stock_plate_map[code].add(plate_id)

            total_count += len(stocks)
            self.logger.info(f"板块 {plate_name} 获取到 {len(stocks)} 只股票")

        return all_stocks, stock_plate_map, total_count
