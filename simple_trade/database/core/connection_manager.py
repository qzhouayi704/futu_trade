#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库连接管理器
负责线程本地连接管理、上下文管理器和连接池
"""

import sqlite3
import logging
import threading
from typing import Generator
from contextlib import contextmanager


class ConnectionManager:
    """数据库连接管理器 - 使用线程本地存储复用连接"""

    def __init__(self, database_path: str):
        """初始化连接管理器

        Args:
            database_path: 数据库文件路径
        """
        self.database_path = database_path
        self._local = threading.local()  # 线程本地存储
        self._lock = threading.Lock()  # 写操作锁

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """获取数据库连接（上下文管理器）

        使用线程本地存储复用连接，确保每个线程使用独立连接

        Usage:
            with conn_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(...)

        Yields:
            数据库连接对象
        """
        try:
            # 检查当前线程是否已有连接
            if not hasattr(self._local, 'connection') or self._local.connection is None:
                self._local.connection = sqlite3.connect(
                    self.database_path,
                    check_same_thread=False,
                    timeout=30.0  # 30秒超时
                )
                # 启用外键约束
                self._local.connection.execute("PRAGMA foreign_keys = ON")
                # 设置WAL模式提高并发性能
                self._local.connection.execute("PRAGMA journal_mode = WAL")
                logging.debug(f"为线程 {threading.current_thread().name} 创建新数据库连接")

            yield self._local.connection

        except sqlite3.Error as e:
            logging.error(f"数据库连接错误: {e}")
            # 连接出错时重置连接
            self._close_thread_connection()
            raise

    def _close_thread_connection(self):
        """关闭当前线程的数据库连接"""
        if hasattr(self._local, 'connection') and self._local.connection is not None:
            try:
                self._local.connection.close()
            except Exception as e:
                logging.warning(f"关闭连接时出错: {e}")
            finally:
                self._local.connection = None

    def close_all_connections(self):
        """关闭所有连接（应用关闭时调用）"""
        self._close_thread_connection()
        logging.info("数据库连接已关闭")

    def get_cursor(self) -> sqlite3.Cursor:
        """获取数据库游标（用于数据库升级等操作）

        注意：调用方需要自行管理连接的提交和关闭

        Returns:
            数据库游标对象
        """
        with self.get_connection() as conn:
            return conn.cursor()

    def commit(self):
        """提交当前线程的事务"""
        if hasattr(self._local, 'connection') and self._local.connection is not None:
            self._local.connection.commit()

    @property
    def lock(self) -> threading.Lock:
        """获取写操作锁

        Returns:
            线程锁对象
        """
        return self._lock

    def get_connection_info(self) -> dict:
        """获取连接状态信息（用于调试）

        Returns:
            连接信息字典
        """
        return {
            'database_path': self.database_path,
            'thread_name': threading.current_thread().name,
            'has_connection': hasattr(self._local, 'connection') and self._local.connection is not None
        }
