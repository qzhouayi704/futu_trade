#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票池查询服务
负责股票池的查询操作，包括板块查询、股票查询、目标股票获取等
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from ...database.core.db_manager import DatabaseManager
from ...core.state import get_state_manager


class StockPoolQueryService:
    """股票池查询服务"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.state_manager = get_state_manager()
        self.logger = logging.getLogger(__name__)

    def get_stock_pool(self) -> Dict[str, Any]:
        """获取全局股票池数据"""
        return self.state_manager.get_stock_pool()

    def get_active_stocks(self, limit: int = None) -> List[Tuple]:
        """从全局股票池获取活跃股票

        Returns:
            List[Tuple]: 股票数据列表，格式为 (id, code, name, market, plate_name)
        """
        return self.state_manager.get_active_stocks(limit)

    def get_plates(self, is_target: bool = None, is_enabled: bool = None) -> List[Dict[str, Any]]:
        """查询板块列表

        Args:
            is_target: 是否为目标板块（None表示不过滤）
            is_enabled: 是否启用（None表示不过滤）

        Returns:
            List[Dict]: 板块列表
        """
        try:
            conditions = []
            params = []

            if is_target is not None:
                conditions.append('is_target = ?')
                params.append(1 if is_target else 0)

            if is_enabled is not None:
                conditions.append('COALESCE(is_enabled, 1) = ?')
                params.append(1 if is_enabled else 0)

            where_clause = f'WHERE {" AND ".join(conditions)}' if conditions else ''

            query = f'''
                SELECT id, plate_code, plate_name, market, category, stock_count,
                       is_target, COALESCE(is_enabled, 1) as is_enabled, priority
                FROM plates
                {where_clause}
                ORDER BY priority DESC, plate_name
            '''

            plates_result = self.db_manager.execute_query(query, tuple(params))

            plates = []
            for row in plates_result:
                plates.append({
                    'id': row[0],
                    'code': row[1],
                    'name': row[2],
                    'market': row[3],
                    'category': row[4] or '',
                    'stock_count': row[5] or 0,
                    'is_target': bool(row[6]),
                    'is_enabled': bool(row[7]),
                    'priority': row[8] if len(row) > 8 else 0
                })

            return plates

        except Exception as e:
            self.logger.error(f"查询板块列表失败: {e}")
            return []

    def get_stocks_by_plate(self, plate_id: int) -> List[Dict[str, Any]]:
        """获取指定板块的股票"""
        try:
            stocks_result = self.db_manager.execute_query('''
                SELECT s.id, s.code, s.name, s.market
                FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                WHERE sp.plate_id = ?
                ORDER BY s.code
            ''', (plate_id,))

            stocks = []
            for row in stocks_result:
                stocks.append({
                    'id': row[0],
                    'code': row[1],
                    'name': row[2] or '',
                    'market': row[3] or ''
                })

            return stocks

        except Exception as e:
            self.logger.error(f"获取板块股票失败: {e}")
            return []

    def get_all_stocks(self) -> List[Dict[str, Any]]:
        """获取所有启用的目标板块的股票"""
        try:
            stocks_result = self.db_manager.execute_query('''
                SELECT s.id, s.code, s.name, s.market,
                       GROUP_CONCAT(DISTINCT p.plate_name) as plate_names
                FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.is_target = 1 AND COALESCE(p.is_enabled, 1) = 1
                GROUP BY s.id, s.code, s.name, s.market
                ORDER BY s.code
            ''')

            stocks = []
            for row in stocks_result:
                plate_names_str = row[4] if len(row) > 4 and row[4] else ''
                plate_names = [name.strip() for name in plate_names_str.split(',') if name.strip()] if plate_names_str else []

                stocks.append({
                    'id': row[0],
                    'code': row[1],
                    'name': row[2] or '',
                    'market': row[3] or '',
                    'plate_names': plate_names,
                    'plate_name': plate_names[0] if plate_names else ''
                })

            return stocks

        except Exception as e:
            self.logger.error(f"获取所有股票失败: {e}")
            return []

    def get_stock_by_code(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """根据股票代码获取股票信息"""
        try:
            stock_result = self.db_manager.execute_query('''
                SELECT s.id, s.code, s.name, s.market,
                       GROUP_CONCAT(DISTINCT p.plate_name) as plate_names
                FROM stocks s
                LEFT JOIN stock_plates sp ON s.id = sp.stock_id
                LEFT JOIN plates p ON sp.plate_id = p.id
                WHERE s.code = ?
                GROUP BY s.id, s.code, s.name, s.market
            ''', (stock_code,))

            if not stock_result:
                return None

            row = stock_result[0]
            plate_names_str = row[4] if len(row) > 4 and row[4] else ''
            plate_names = [name.strip() for name in plate_names_str.split(',') if name.strip()] if plate_names_str else []

            return {
                'id': row[0],
                'code': row[1],
                'name': row[2] or '',
                'market': row[3] or '',
                'plate_names': plate_names,
                'plate_name': plate_names[0] if plate_names else ''
            }

        except Exception as e:
            self.logger.error(f"获取股票信息失败: {e}")
            return None

    def get_plate_by_code(self, plate_code: str) -> Optional[Dict[str, Any]]:
        """根据板块代码获取板块信息"""
        try:
            plate_result = self.db_manager.execute_query('''
                SELECT id, plate_code, plate_name, market, category, stock_count, is_target,
                       COALESCE(is_enabled, 1) as is_enabled, priority
                FROM plates
                WHERE plate_code = ?
            ''', (plate_code,))

            if not plate_result:
                return None

            row = plate_result[0]
            return {
                'id': row[0],
                'code': row[1],
                'name': row[2],
                'market': row[3],
                'category': row[4] or '',
                'stock_count': row[5] or 0,
                'is_target': bool(row[6]),
                'is_enabled': bool(row[7]),
                'priority': row[8] if len(row) > 8 else 0
            }

        except Exception as e:
            self.logger.error(f"获取板块信息失败: {e}")
            return None

    def get_plate_by_id(self, plate_id: int) -> Optional[Dict[str, Any]]:
        """根据板块ID获取板块信息"""
        try:
            plate_result = self.db_manager.execute_query('''
                SELECT id, plate_code, plate_name, market, category, stock_count, is_target,
                       COALESCE(is_enabled, 1) as is_enabled, priority
                FROM plates
                WHERE id = ?
            ''', (plate_id,))

            if not plate_result:
                return None

            row = plate_result[0]
            return {
                'id': row[0],
                'code': row[1],
                'name': row[2],
                'market': row[3],
                'category': row[4] or '',
                'stock_count': row[5] or 0,
                'is_target': bool(row[6]),
                'is_enabled': bool(row[7]),
                'priority': row[8] if len(row) > 8 else 0
            }

        except Exception as e:
            self.logger.error(f"获取板块信息失败: {e}")
            return None

    def get_stock_by_id(self, stock_id: int) -> Optional[Dict[str, Any]]:
        """根据股票ID获取股票信息"""
        try:
            stock_result = self.db_manager.execute_query('''
                SELECT s.id, s.code, s.name, s.market,
                       GROUP_CONCAT(DISTINCT p.plate_name) as plate_names
                FROM stocks s
                LEFT JOIN stock_plates sp ON s.id = sp.stock_id
                LEFT JOIN plates p ON sp.plate_id = p.id
                WHERE s.id = ?
                GROUP BY s.id, s.code, s.name, s.market
            ''', (stock_id,))

            if not stock_result:
                return None

            row = stock_result[0]
            plate_names_str = row[4] if len(row) > 4 and row[4] else ''
            plate_names = [name.strip() for name in plate_names_str.split(',') if name.strip()] if plate_names_str else []

            return {
                'id': row[0],
                'code': row[1],
                'name': row[2] or '',
                'market': row[3] or '',
                'plate_names': plate_names,
                'plate_name': plate_names[0] if plate_names else ''
            }

        except Exception as e:
            self.logger.error(f"获取股票信息失败: {e}")
            return None

    def refresh_from_database(self):
        """从数据库刷新全局股票池数据

        性能优化：使用单次联合查询代替N+1查询模式

        字段说明：
        - is_target: 是否为目标板块（用户选择关注的板块）
        - is_enabled: 是否启用（控制板块是否参与实时监控）
        """
        try:
            # 只获取目标板块
            plates = self.get_plates(is_target=True)
            stocks = self.get_all_stocks()

            # 更新全局数据
            self.state_manager.set_stock_pool(plates, stocks)
            self.logger.info(f"刷新全局股票池数据: {len(plates)}个目标板块, {len(stocks)}只股票")

        except Exception as e:
            self.logger.error(f"从数据库刷新全局股票池失败: {e}")
