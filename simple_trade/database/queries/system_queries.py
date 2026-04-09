#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统配置和统计查询服务
负责系统配置、数据库统计、索引管理等操作
"""

import logging
from typing import Dict, Any, Optional, List
from ..core.connection_manager import ConnectionManager
from ..core.base_queries import BaseQueries


class SystemQueries(BaseQueries):
    """系统查询服务"""

    def __init__(self, conn_manager: ConnectionManager):
        """初始化系统查询服务

        Args:
            conn_manager: 连接管理器实例
        """
        super().__init__(conn_manager)

    def execute_many(self, query: str, params_list: List[tuple]) -> int:
        """批量执行语句（使用基类的execute_batch方法）

        Args:
            query: SQL语句（使用?占位符）
            params_list: 参数元组列表

        Returns:
            执行成功的记录数，失败返回-1
        """
        return self.execute_batch(query, params_list)

    def get_system_config(self, key: str) -> Optional[str]:
        """获取系统配置

        Args:
            key: 配置键

        Returns:
            配置值，不存在返回None
        """
        try:
            result = self.execute_query(
                'SELECT value FROM system_config WHERE key = ?',
                (key,)
            )
            return result[0][0] if result else None
        except Exception as e:
            logging.error(f"获取系统配置失败: {e}")
            return None

    def set_system_config(self, key: str, value: str, description: str = "") -> bool:
        """设置系统配置

        Args:
            key: 配置键
            value: 配置值
            description: 配置描述

        Returns:
            是否设置成功
        """
        try:
            rows = self.execute_update('''
                INSERT OR REPLACE INTO system_config (key, value, description, updated_at)
                VALUES (?, ?, ?, datetime('now'))
            ''', (key, value, description))
            return rows >= 0
        except Exception as e:
            logging.error(f"设置系统配置失败: {e}")
            return False

    def get_database_stats(self) -> Dict[str, int]:
        """获取数据库统计信息

        Returns:
            各表记录数统计
        """
        stats = {}

        # 获取各表记录数
        for table in ['plates', 'stocks', 'trade_signals']:
            query = f'SELECT COUNT(*) FROM {table}'
            result = self.execute_query(query)
            stats[table] = result[0][0] if result else 0

        return stats

    def get_index_info(self) -> List[Dict[str, Any]]:
        """获取当前数据库的所有索引信息

        Returns:
            索引信息列表
        """
        try:
            from ...core.models import IndexInfo

            query = """
                SELECT name, tbl_name, sql
                FROM sqlite_master
                WHERE type = 'index' AND sql IS NOT NULL
                ORDER BY tbl_name, name
            """
            rows = self.execute_query(query)
            # 使用 IndexInfo 数据模型
            index_objects = [IndexInfo.from_db_row(row) for row in rows]
            return [index.to_dict() for index in index_objects]
        except Exception as e:
            logging.error(f"获取索引信息失败: {e}")
            return []

    def drop_index(self, index_name: str) -> bool:
        """删除指定索引

        Args:
            index_name: 索引名称

        Returns:
            是否删除成功
        """
        try:
            # 使用参数化方式不适用于DROP INDEX，需验证索引名
            if not index_name.startswith('idx_'):
                logging.warning(f"无效的索引名称: {index_name}")
                return False

            with self.conn_manager.lock:
                with self.conn_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(f"DROP INDEX IF EXISTS {index_name}")
                    conn.commit()
            logging.info(f"索引 {index_name} 已删除")
            return True
        except Exception as e:
            logging.error(f"删除索引 {index_name} 失败: {e}")
            return False

    def analyze_tables(self) -> bool:
        """分析表以优化查询计划

        运行ANALYZE命令更新SQLite的统计信息

        Returns:
            是否分析成功
        """
        try:
            with self.conn_manager.get_connection() as conn:
                conn.execute('ANALYZE')
            logging.info("数据库表分析完成")
            return True
        except Exception as e:
            logging.error(f"分析表失败: {e}")
            return False

    def vacuum_database(self) -> bool:
        """优化数据库

        Returns:
            是否优化成功
        """
        try:
            with self.conn_manager.get_connection() as conn:
                conn.execute('VACUUM')
            logging.info("数据库优化完成")
            return True
        except Exception as e:
            logging.error(f"数据库优化失败: {e}")
            return False

    def explain_query(self, query: str, params: tuple = None) -> List[str]:
        """解释查询执行计划（用于调试）

        Args:
            query: SQL查询语句
            params: 查询参数

        Returns:
            执行计划说明列表
        """
        try:
            explain_query = f"EXPLAIN QUERY PLAN {query}"
            with self.conn_manager.get_connection() as conn:
                cursor = conn.cursor()
                if params:
                    cursor.execute(explain_query, params)
                else:
                    cursor.execute(explain_query)
                return [str(row) for row in cursor.fetchall()]
        except Exception as e:
            logging.error(f"解释查询失败: {e}")
            return [f"Error: {e}"]
