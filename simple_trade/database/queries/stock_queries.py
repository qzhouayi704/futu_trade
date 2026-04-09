#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票相关查询服务
负责股票数据的查询和更新操作
"""

import logging
from typing import List, Dict, Any, Optional
from ..core.connection_manager import ConnectionManager
from ..core.base_queries import BaseQueries
from ...core.models import StockInfo


class StockQueries(BaseQueries):
    """股票查询服务"""

    def __init__(self, conn_manager: ConnectionManager):
        """初始化股票查询服务

        Args:
            conn_manager: 连接管理器实例
        """
        super().__init__(conn_manager)

    def get_stocks(self, limit: int = None) -> list:
        """获取目标板块的股票列表（使用stock_plates多对多关联，只返回目标板块且已启用的板块的股票）

        Args:
            limit: 限制返回数量，None表示不限制

        Returns:
            股票列表
        """
        if limit is None:
            query = '''
                SELECT DISTINCT s.id, s.code, s.name, s.market, p.plate_name
                FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.is_target = 1 AND COALESCE(p.is_enabled, 1) = 1
                ORDER BY s.code
            '''
            return self.execute_query(query)
        else:
            query = '''
                SELECT DISTINCT s.id, s.code, s.name, s.market, p.plate_name
                FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.is_target = 1 AND COALESCE(p.is_enabled, 1) = 1
                ORDER BY s.code
                LIMIT ?
            '''
            return self.execute_query(query, (limit,))

    def get_stocks_with_plate_info(self) -> list:
        """获取股票列表（包含板块信息，使用stock_plates多对多关联）

        只返回目标板块且已启用的板块的股票

        Returns:
            股票列表（含板块信息）
        """
        query = '''
            SELECT DISTINCT s.id, s.code, s.name, s.market, sp.plate_id, p.plate_name
            FROM stocks s
            INNER JOIN stock_plates sp ON s.id = sp.stock_id
            INNER JOIN plates p ON sp.plate_id = p.id
            WHERE p.is_target = 1 AND COALESCE(p.is_enabled, 1) = 1
            ORDER BY s.code
        '''
        return self.execute_query(query)

    def get_stocks_by_plate(self, plate_code: str) -> List[Dict[str, Any]]:
        """获取指定板块的所有股票

        Args:
            plate_code: 板块代码

        Returns:
            股票列表，格式: [{'id': 1, 'code': 'HK.00700', 'name': '腾讯控股', 'market': 'HK'}, ...]
        """
        try:
            query = '''
                SELECT DISTINCT s.id, s.code, s.name, s.market
                FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.plate_code = ?
                ORDER BY s.code
            '''
            rows = self.execute_query(query, (plate_code,))
            return [{'id': r[0], 'code': r[1], 'name': r[2], 'market': r[3]} for r in rows]
        except Exception as e:
            logging.error(f"获取板块股票失败 {plate_code}: {e}")
            return []

    def get_plates_by_stock(self, stock_code: str) -> List[Dict[str, Any]]:
        """获取指定股票所属的所有板块

        Args:
            stock_code: 股票代码

        Returns:
            板块列表，格式: [{'code': 'BK001', 'name': '科技板块', ...}, ...]
        """
        try:
            query = '''
                SELECT DISTINCT p.plate_code, p.plate_name, p.market, p.is_target, p.priority
                FROM plates p
                INNER JOIN stock_plates sp ON p.id = sp.plate_id
                INNER JOIN stocks s ON sp.stock_id = s.id
                WHERE s.code = ?
                ORDER BY p.priority DESC, p.plate_code
            '''
            rows = self.execute_query(query, (stock_code,))
            return [
                {
                    'code': r[0],
                    'name': r[1],
                    'market': r[2],
                    'is_target': r[3],
                    'priority': r[4]
                }
                for r in rows
            ]
        except Exception as e:
            logging.error(f"获取股票板块失败 {stock_code}: {e}")
            return []

    def get_active_positions(self) -> List[Dict[str, Any]]:
        """获取当前持仓的股票列表

        注意: 该方法假设持仓信息已通过 sync_positions_to_stock_pool() 同步到数据库

        Returns:
            持仓股票列表，格式: [{'stock_code': 'HK.00700', 'stock_name': '腾讯控股',
                                'entry_price': 350.0, 'entry_date': '2026-01-20'}, ...]
        """
        try:
            # 从"持仓监控"板块获取股票信息
            query = '''
                SELECT DISTINCT s.code, s.name
                FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.plate_code = 'POSITION_MONITOR'
                ORDER BY s.code
            '''
            rows = self.execute_query(query)
            return [{'stock_code': r[0], 'stock_name': r[1], 'entry_price': 0, 'entry_date': ''} for r in rows]
        except Exception as e:
            logging.error(f"获取持仓股票失败: {e}")
            return []

    def get_stock_name(self, stock_code: str) -> str:
        """获取股票名称

        Args:
            stock_code: 股票代码

        Returns:
            股票名称，查询失败时返回 stock_code 本身
        """
        try:
            result = self.execute_query(
                'SELECT name FROM stocks WHERE code = ?', (stock_code,)
            )
            return result[0][0] if result else stock_code
        except Exception:
            return stock_code

    def get_stock_info(self, stock_code: str) -> Optional[StockInfo]:
        """获取股票信息（返回 StockInfo 对象）

        Args:
            stock_code: 股票代码

        Returns:
            StockInfo 对象，查询失败时返回 None
        """
        try:
            result = self.execute_query(
                'SELECT id, code, name FROM stocks WHERE code = ?', (stock_code,)
            )
            if result:
                row = result[0]
                return StockInfo(id=row[0], code=row[1], name=row[2])
            return None
        except Exception as e:
            logging.error(f"获取股票信息失败 {stock_code}: {e}")
            return None
