"""
数据库查询基类
提供统一的CRUD操作，避免在多个查询类中重复实现
"""
from typing import List, Tuple, Optional
from simple_trade.database.core.connection_manager import ConnectionManager
import logging


class BaseQueries:
    """数据库查询基类，提供统一的CRUD操作"""

    def __init__(self, conn_manager: ConnectionManager):
        self.conn_manager = conn_manager

    def execute_query(self, query: str, params: tuple = None) -> list:
        """
        执行查询操作

        Args:
            query: SQL查询语句
            params: 查询参数

        Returns:
            查询结果列表
        """
        try:
            with self.conn_manager.get_connection() as conn:
                cursor = conn.cursor()
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                return cursor.fetchall()
        except Exception as e:
            logging.error(f"查询执行失败: {e}, SQL: {query[:100]}...")
            return []

    def execute_update(self, query: str, params: tuple = None) -> int:
        """
        执行更新操作

        Args:
            query: SQL更新语句
            params: 更新参数

        Returns:
            影响的行数，失败返回-1
        """
        try:
            with self.conn_manager.lock:  # 写操作加锁
                with self.conn_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    if params:
                        cursor.execute(query, params)
                    else:
                        cursor.execute(query)
                    conn.commit()
                    return cursor.rowcount
        except Exception as e:
            logging.error(f"更新执行失败: {e}, SQL: {query[:100]}...")
            return -1

    def execute_insert(self, query: str, params: tuple = None) -> int:
        """
        执行插入操作

        Args:
            query: SQL插入语句
            params: 插入参数

        Returns:
            新插入记录的ID (lastrowid)

        Raises:
            Exception: 插入失败时抛出异常
        """
        try:
            with self.conn_manager.lock:  # 写操作加锁
                with self.conn_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    if params:
                        cursor.execute(query, params)
                    else:
                        cursor.execute(query)
                    lastrowid = cursor.lastrowid
                    conn.commit()
                    return lastrowid
        except Exception as e:
            logging.error(f"插入执行失败: {e}, SQL: {query[:100]}...")
            raise

    def execute_batch(self, query: str, params_list: List[Tuple]) -> int:
        """
        执行批量操作

        Args:
            query: SQL语句
            params_list: 参数列表

        Returns:
            影响的行数
        """
        try:
            with self.conn_manager.lock:  # 写操作加锁
                with self.conn_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.executemany(query, params_list)
                    conn.commit()
                    return cursor.rowcount if cursor.rowcount >= 0 else 0
        except Exception as e:
            logging.error(f"批量操作失败: {e}, SQL: {query[:100]}...")
            return 0
