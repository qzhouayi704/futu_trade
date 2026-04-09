#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步数据库连接管理器
负责异步连接管理、上下文管理器和连接池
"""

import aiosqlite
import asyncio
import logging
from contextvars import ContextVar
from contextlib import asynccontextmanager
from typing import Optional


class AsyncConnectionManager:
    """异步数据库连接管理器 - 使用 contextvars 管理异步上下文"""

    def __init__(self, database_path: str):
        """初始化异步连接管理器

        Args:
            database_path: 数据库文件路径
        """
        self.database_path = database_path
        self._local: ContextVar[Optional[aiosqlite.Connection]] = ContextVar('connection', default=None)
        self._lock = asyncio.Lock()  # 异步锁

    @asynccontextmanager
    async def get_connection(self):
        """获取数据库连接（异步上下文管理器）

        使用 contextvars 管理异步上下文，确保每个异步任务使用独立连接

        Usage:
            async with conn_manager.get_connection() as conn:
                cursor = await conn.execute(...)

        Yields:
            异步数据库连接对象
        """
        try:
            # 检查当前上下文是否已有连接
            conn = self._local.get()
            if conn is None:
                conn = await aiosqlite.connect(
                    self.database_path,
                    timeout=30.0  # 30秒超时
                )
                # 启用外键约束
                await conn.execute("PRAGMA foreign_keys = ON")
                # 设置WAL模式提高并发性能
                await conn.execute("PRAGMA journal_mode = WAL")
                self._local.set(conn)
                logging.debug(f"为异步上下文创建新数据库连接")

            yield conn

        except aiosqlite.Error as e:
            logging.error(f"异步数据库连接错误: {e}")
            # 连接出错时重置连接
            await self._close_context_connection()
            raise

    async def _close_context_connection(self):
        """关闭当前上下文的数据库连接"""
        conn = self._local.get()
        if conn is not None:
            try:
                await conn.close()
            except Exception as e:
                logging.warning(f"关闭异步连接时出错: {e}")
            finally:
                self._local.set(None)

    async def close_all_connections(self):
        """关闭所有连接（应用关闭时调用）"""
        await self._close_context_connection()
        logging.info("异步数据库连接已关闭")

    async def commit(self):
        """提交当前上下文的事务"""
        conn = self._local.get()
        if conn is not None:
            await conn.commit()

    @property
    def lock(self) -> asyncio.Lock:
        """获取异步写操作锁

        Returns:
            异步锁对象
        """
        return self._lock

    def get_connection_info(self) -> dict:
        """获取连接状态信息（用于调试）

        Returns:
            连接信息字典
        """
        conn = self._local.get()
        return {
            'database_path': self.database_path,
            'has_connection': conn is not None
        }
