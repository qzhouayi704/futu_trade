#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步数据库查询基类
提供统一的异步CRUD操作，避免在多个查询类中重复实现
"""
from typing import List, Tuple, Optional
from simple_trade.database.core.async_connection_manager import AsyncConnectionManager
import logging


class AsyncBaseQueries:
    """异步数据库查询基类，提供统一的异步CRUD操作"""

    def __init__(self, conn_manager: AsyncConnectionManager):
        self.conn_manager = conn_manager

    async def execute_query(self, query: str, params: tuple = None) -> list:
        """
        执行异步查询操作

        Args:
            query: SQL查询语句
            params: 查询参数

        Returns:
            查询结果列表
        """
        try:
            async with self.conn_manager.get_connection() as conn:
                cursor = await conn.execute(query, params or ())
                return await cursor.fetchall()
        except Exception as e:
            logging.error(f"异步查询执行失败: {e}, SQL: {query[:100]}...")
            return []

    async def execute_update(self, query: str, params: tuple = None) -> int:
        """
        执行异步更新操作

        Args:
            query: SQL更新语句
            params: 更新参数

        Returns:
            影响的行数，失败返回-1
        """
        try:
            async with self.conn_manager.lock:
                async with self.conn_manager.get_connection() as conn:
                    cursor = await conn.execute(query, params or ())
                    await conn.commit()
                    return cursor.rowcount
        except Exception as e:
            logging.error(f"异步更新执行失败: {e}, SQL: {query[:100]}...")
            return -1

    async def execute_insert(self, query: str, params: tuple = None) -> int:
        """
        执行异步插入操作

        Args:
            query: SQL插入语句
            params: 插入参数

        Returns:
            新插入记录的ID，失败返回-1
        """
        try:
            async with self.conn_manager.lock:
                async with self.conn_manager.get_connection() as conn:
                    cursor = await conn.execute(query, params or ())
                    await conn.commit()
                    return cursor.lastrowid
        except Exception as e:
            logging.error(f"异步插入执行失败: {e}, SQL: {query[:100]}...")
            return -1

    async def execute_delete(self, query: str, params: tuple = None) -> int:
        """
        执行异步删除操作

        Args:
            query: SQL删除语句
            params: 删除参数

        Returns:
            删除的行数，失败返回-1
        """
        try:
            async with self.conn_manager.lock:
                async with self.conn_manager.get_connection() as conn:
                    cursor = await conn.execute(query, params or ())
                    await conn.commit()
                    return cursor.rowcount
        except Exception as e:
            logging.error(f"异步删除执行失败: {e}, SQL: {query[:100]}...")
            return -1

    async def execute_many(self, query: str, params_list: List[tuple]) -> int:
        """
        执行异步批量操作

        Args:
            query: SQL语句
            params_list: 参数列表

        Returns:
            影响的总行数，失败返回-1
        """
        try:
            async with self.conn_manager.lock:
                async with self.conn_manager.get_connection() as conn:
                    await conn.executemany(query, params_list)
                    await conn.commit()
                    return len(params_list)
        except Exception as e:
            logging.error(f"异步批量操作执行失败: {e}, SQL: {query[:100]}...")
            return -1

    async def execute_script(self, script: str) -> bool:
        """
        执行异步SQL脚本

        Args:
            script: SQL脚本

        Returns:
            是否执行成功
        """
        try:
            async with self.conn_manager.lock:
                async with self.conn_manager.get_connection() as conn:
                    await conn.executescript(script)
                    await conn.commit()
                    return True
        except Exception as e:
            logging.error(f"异步脚本执行失败: {e}")
            return False
