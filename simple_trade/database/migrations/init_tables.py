#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库表初始化模块

提供统一的数据库表初始化函数，避免在各个服务中重复创建表
"""

import logging
from typing import Optional

from ..database.core.db_manager import DatabaseManager
from ..database.models.schema import DatabaseSchema


logger = logging.getLogger(__name__)


def init_all_tables(db_manager: DatabaseManager, force: bool = False) -> bool:
    """
    初始化所有数据库表

    从 DatabaseSchema 读取表定义，统一创建所有表。
    应该在应用启动时调用一次，而不是在各个服务的 __init__ 中重复调用。

    Args:
        db_manager: 数据库管理器实例
        force: 是否强制重建表（默认 False，只创建不存在的表）

    Returns:
        是否成功初始化所有表

    Example:
        >>> from simple_trade.database.core.db_manager import DatabaseManager
        >>> from simple_trade.database.migrations.init_tables import init_all_tables
        >>>
        >>> db = DatabaseManager('trading.db')
        >>> init_all_tables(db)
    """
    try:
        logger.info("开始初始化数据库表...")

        # 获取所有表定义
        schema = DatabaseSchema()
        tables = schema.get_all_tables()

        success_count = 0
        failed_tables = []

        for table_name, table_sql in tables.items():
            try:
                if force:
                    # 强制重建：先删除再创建
                    logger.debug(f"强制重建表: {table_name}")
                    db_manager.execute_update(f"DROP TABLE IF EXISTS {table_name}")

                # 创建表（如果不存在）
                db_manager.execute_update(table_sql)
                success_count += 1
                logger.debug(f"表 {table_name} 初始化成功")

            except Exception as e:
                logger.error(f"表 {table_name} 初始化失败: {e}")
                failed_tables.append(table_name)

        # 输出总结
        total_tables = len(tables)
        if failed_tables:
            logger.warning(
                f"数据库表初始化完成: {success_count}/{total_tables} 成功，"
                f"失败的表: {', '.join(failed_tables)}"
            )
            return False
        else:
            logger.info(f"数据库表初始化完成: {success_count}/{total_tables} 全部成功")
            return True

    except Exception as e:
        logger.error(f"数据库表初始化失败: {e}", exc_info=True)
        return False


def init_specific_tables(
    db_manager: DatabaseManager,
    table_names: list[str],
    force: bool = False
) -> bool:
    """
    初始化指定的数据库表

    Args:
        db_manager: 数据库管理器实例
        table_names: 要初始化的表名列表
        force: 是否强制重建表（默认 False）

    Returns:
        是否成功初始化所有指定的表

    Example:
        >>> init_specific_tables(db, ['stocks', 'plates'])
    """
    try:
        logger.info(f"开始初始化指定的数据库表: {', '.join(table_names)}")

        schema = DatabaseSchema()
        all_tables = schema.get_all_tables()

        success_count = 0
        failed_tables = []

        for table_name in table_names:
            if table_name not in all_tables:
                logger.warning(f"表 {table_name} 不在 schema 定义中，跳过")
                continue

            try:
                table_sql = all_tables[table_name]

                if force:
                    logger.debug(f"强制重建表: {table_name}")
                    db_manager.execute_update(f"DROP TABLE IF EXISTS {table_name}")

                db_manager.execute_update(table_sql)
                success_count += 1
                logger.debug(f"表 {table_name} 初始化成功")

            except Exception as e:
                logger.error(f"表 {table_name} 初始化失败: {e}")
                failed_tables.append(table_name)

        # 输出总结
        if failed_tables:
            logger.warning(
                f"指定表初始化完成: {success_count}/{len(table_names)} 成功，"
                f"失败的表: {', '.join(failed_tables)}"
            )
            return False
        else:
            logger.info(f"指定表初始化完成: {success_count}/{len(table_names)} 全部成功")
            return True

    except Exception as e:
        logger.error(f"指定表初始化失败: {e}", exc_info=True)
        return False


def check_tables_exist(db_manager: DatabaseManager, table_names: Optional[list[str]] = None) -> dict[str, bool]:
    """
    检查表是否存在

    Args:
        db_manager: 数据库管理器实例
        table_names: 要检查的表名列表（None 表示检查所有表）

    Returns:
        字典，键为表名，值为是否存在

    Example:
        >>> status = check_tables_exist(db, ['stocks', 'plates'])
        >>> print(status)
        {'stocks': True, 'plates': False}
    """
    try:
        schema = DatabaseSchema()
        all_tables = schema.get_all_tables()

        if table_names is None:
            table_names = list(all_tables.keys())

        result = {}
        for table_name in table_names:
            try:
                # 尝试查询表，如果不存在会抛出异常
                db_manager.execute_query(f"SELECT 1 FROM {table_name} LIMIT 1")
                result[table_name] = True
            except Exception:
                result[table_name] = False

        return result

    except Exception as e:
        logger.error(f"检查表存在性失败: {e}", exc_info=True)
        return {}
