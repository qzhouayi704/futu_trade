#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库管理器 - 协调器
负责初始化数据库、管理迁移，并协调各查询服务
"""

import os
import sqlite3
import logging
from typing import Dict, Any, List, Generator
from contextlib import contextmanager

from ..models import DatabaseSchema
from .connection_manager import ConnectionManager
from .async_connection_manager import AsyncConnectionManager
from .async_base_queries import AsyncBaseQueries
from .write_queue import DatabaseWriteQueue
from ..queries.stock_queries import StockQueries
from ..queries.stock_activity_queries import StockActivityQueries
from ..queries.plate_queries import PlateQueries
from ..queries.trade_queries import TradeQueries
from ..queries.trade_history_queries import TradeHistoryQueries
from ..queries.kline_queries import KlineQueries
from ..queries.system_queries import SystemQueries
from ..queries.advisor_queries import AdvisorQueries
from ..queries.ticker_queries import TickerQueries


class DatabaseManager:
    """数据库管理器 - 协调各查询服务"""

    def __init__(self, database_path: str):
        """初始化数据库管理器

        Args:
            database_path: 数据库文件路径
        """
        self.database_path = database_path

        # 创建同步连接管理器（保留向后兼容）
        self.conn_manager = ConnectionManager(database_path)

        # 创建异步连接管理器（新增）
        self.async_conn_manager = AsyncConnectionManager(database_path)
        self.async_queries = AsyncBaseQueries(self.async_conn_manager)

        # 创建各查询服务实例
        self.stock_queries = StockQueries(self.conn_manager)
        self.stock_activity_queries = StockActivityQueries(self.conn_manager)
        self.plate_queries = PlateQueries(self.conn_manager)
        self.trade_queries = TradeQueries(self.conn_manager)
        self.trade_history_queries = TradeHistoryQueries(self.conn_manager)
        self.kline_queries = KlineQueries(self.conn_manager)
        self.system_queries = SystemQueries(self.conn_manager)
        self.advisor_queries = AdvisorQueries(self.conn_manager)
        self.ticker_queries = TickerQueries(self.conn_manager)

        # 写入队列（序列化所有写操作，消除 "database is locked"）
        self.write_queue = DatabaseWriteQueue()
        self.write_queue.start()

        # 保留向后兼容的属性
        self._local = self.conn_manager._local
        self._lock = self.conn_manager._lock

    def init_database(self) -> bool:
        """初始化数据库（创建表和索引）

        执行顺序：
        1. 创建表（使用最新的表定义）
        2. 执行自动迁移（为旧数据库添加缺失的列）
        3. 创建索引（此时所有列都已存在）

        Returns:
            是否初始化成功
        """
        try:
            # 确保数据目录存在
            db_dir = os.path.dirname(self.database_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

            with self.get_connection() as conn:
                cursor = conn.cursor()
                # 1. 创建所有表
                for table_sql in DatabaseSchema.get_all_tables():
                    cursor.execute(table_sql)
                conn.commit()

            # 2. 执行自动迁移（添加缺失的列）- 必须在创建索引之前
            self._run_auto_migrations()

            # 3. 创建索引（此时所有需要的列已存在）
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for index_sql in DatabaseSchema.get_all_indexes():
                    try:
                        cursor.execute(index_sql)
                    except Exception as idx_err:
                        # 索引创建失败不应阻止整个初始化
                        logging.warning(f"索引创建失败（可能已存在）: {idx_err}")
                conn.commit()

            logging.info("数据库初始化完成（含表、迁移和索引）")
            return True

        except Exception as e:
            logging.error(f"数据库初始化失败: {e}")
            return False

    def _run_auto_migrations(self):
        """自动运行数据库迁移（添加缺失的列）"""
        try:
            migrations = [
                # (表名, 列名, 列定义)
                ('plates', 'is_enabled', 'BOOLEAN DEFAULT 1'),
                ('plates', 'priority', 'INTEGER DEFAULT 0'),
                ('plates', 'match_score', 'INTEGER DEFAULT 0'),
                ('stocks', 'is_manual', 'BOOLEAN DEFAULT 0'),
                ('stocks', 'stock_priority', 'INTEGER DEFAULT 0'),
                ('stocks', 'heat_score', 'REAL DEFAULT 0'),
                ('stocks', 'avg_turnover_rate', 'REAL DEFAULT 0'),
                ('stocks', 'avg_volume', 'REAL DEFAULT 0'),
                ('stocks', 'active_days', 'INTEGER DEFAULT 0'),
                ('stocks', 'heat_update_time', 'TIMESTAMP'),
                # 低活跃度标记字段
                ('stocks', 'is_low_activity', 'INTEGER DEFAULT 0'),
                ('stocks', 'low_activity_checked_at', 'TEXT'),
                # OTC股票标记字段
                ('stocks', 'is_otc', 'INTEGER DEFAULT 0'),
                # 交易信号策略关联字段
                ('trade_signals', 'strategy_id', 'VARCHAR(50)'),
                ('trade_signals', 'strategy_name', 'VARCHAR(100)'),
                # 止盈执行记录：deal_id 和 order_id
                ('take_profit_executions', 'deal_id', 'TEXT'),
                ('take_profit_executions', 'order_id', 'TEXT'),
            ]

            for table_name, column_name, column_def in migrations:
                if not self._column_exists(table_name, column_name):
                    self._add_column(table_name, column_name, column_def)
                    logging.info(f"迁移完成: 为表 {table_name} 添加列 {column_name}")

        except Exception as e:
            logging.error(f"自动迁移失败: {e}")

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        """检查表中是否存在指定列

        Args:
            table_name: 表名
            column_name: 列名

        Returns:
            是否存在
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = [row[1] for row in cursor.fetchall()]
                return column_name in columns
        except Exception as e:
            logging.error(f"检查列 {column_name} 是否存在失败: {e}")
            return True  # 出错时假设存在，避免重复添加

    def _add_column(self, table_name: str, column_name: str, column_def: str):
        """为表添加新列

        Args:
            table_name: 表名
            column_name: 列名
            column_def: 列定义
        """
        try:
            with self._lock:
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
                    conn.commit()
        except Exception as e:
            logging.warning(f"添加列 {table_name}.{column_name} 失败: {e}")

    def create_indexes(self) -> Dict[str, bool]:
        """创建所有索引

        Returns:
            索引名称 -> 创建成功/失败 的字典
        """
        results = {}
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for index_sql in DatabaseSchema.get_all_indexes():
                    # 从SQL中提取索引名称
                    index_name = index_sql.split('idx_')[1].split(' ')[0] if 'idx_' in index_sql else 'unknown'
                    index_name = f"idx_{index_name}"
                    try:
                        cursor.execute(index_sql)
                        results[index_name] = True
                    except Exception as e:
                        logging.warning(f"创建索引 {index_name} 失败: {e}")
                        results[index_name] = False
                conn.commit()
            logging.info(f"索引创建完成: {sum(results.values())}/{len(results)} 成功")
        except Exception as e:
            logging.error(f"创建索引失败: {e}")
        return results

    # ==================== 连接管理方法（委托给 ConnectionManager） ====================

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """获取数据库连接（上下文管理器）"""
        with self.conn_manager.get_connection() as conn:
            yield conn

    def close_all_connections(self):
        """关闭所有连接"""
        # 先关闭写入队列（flush 剩余任务）
        if hasattr(self, 'write_queue') and self.write_queue.is_running:
            self.write_queue.shutdown(timeout=10.0)
        self.conn_manager.close_all_connections()

    def get_cursor(self) -> sqlite3.Cursor:
        """获取数据库游标"""
        return self.conn_manager.get_cursor()

    def commit(self):
        """提交当前线程的事务"""
        self.conn_manager.commit()

    def get_connection_info(self) -> Dict[str, Any]:
        """获取连接状态信息（用于调试）"""
        return self.conn_manager.get_connection_info()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """事务上下文管理器，自动提交或回滚"""
        with self._lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    yield cursor
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    logging.error(f"事务执行失败，已回滚: {e}")
                    raise

    def execute_query(self, query: str, params: tuple = None) -> list:
        """执行查询语句，返回结果列表"""
        return self.system_queries.execute_query(query, params)

    def execute_update(self, query: str, params: tuple = None) -> int:
        """执行更新语句，返回影响行数（失败返回-1）"""
        return self.system_queries.execute_update(query, params)

    def execute_insert(self, query: str, params: tuple = None) -> int:
        """执行插入语句，返回新记录ID"""
        return self.trade_queries.execute_insert(query, params)

    def execute_many(self, query: str, params_list: List[tuple]) -> int:
        """批量执行语句，返回成功记录数（失败返回-1）"""
        return self.system_queries.execute_many(query, params_list)

    # ==================== 异步查询方法 ====================

    async def async_execute_query(self, query: str, params: tuple = None) -> list:
        """执行异步查询操作"""
        return await self.async_queries.execute_query(query, params)

    async def async_execute_update(self, query: str, params: tuple = None) -> int:
        """执行异步更新操作"""
        return await self.async_queries.execute_update(query, params)

    async def async_execute_insert(self, query: str, params: tuple = None) -> int:
        """执行异步插入操作"""
        return await self.async_queries.execute_insert(query, params)

    async def async_execute_delete(self, query: str, params: tuple = None) -> int:
        """执行异步删除操作"""
        return await self.async_queries.execute_delete(query, params)

    async def async_close_all_connections(self):
        """关闭所有异步连接"""
        await self.async_conn_manager.close_all_connections()
