#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移脚本 - 为 take_profit_executions 表添加 deal_id 和 order_id 字段
"""

import sqlite3
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)


def column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    """检查表中是否已存在某列"""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def run_migration(db_path: str):
    """执行数据库迁移：为 take_profit_executions 添加 deal_id 和 order_id"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 检查表是否存在
        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='take_profit_executions'"
        )
        if not cursor.fetchone():
            logging.warning("表 take_profit_executions 不存在，跳过迁移")
            conn.close()
            return True

        added = []

        # 添加 deal_id 列
        if not column_exists(cursor, "take_profit_executions", "deal_id"):
            cursor.execute(
                "ALTER TABLE take_profit_executions ADD COLUMN deal_id TEXT"
            )
            added.append("deal_id")
            logging.info("已添加列: deal_id")
        else:
            logging.info("列 deal_id 已存在，跳过")

        # 添加 order_id 列
        if not column_exists(cursor, "take_profit_executions", "order_id"):
            cursor.execute(
                "ALTER TABLE take_profit_executions ADD COLUMN order_id TEXT"
            )
            added.append("order_id")
            logging.info("已添加列: order_id")
        else:
            logging.info("列 order_id 已存在，跳过")

        # 创建索引
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tp_exec_deal "
            "ON take_profit_executions(deal_id)"
        )
        logging.info("已创建索引: idx_tp_exec_deal")

        conn.commit()

        # 验证
        cursor.execute("PRAGMA table_info(take_profit_executions)")
        columns = [row[1] for row in cursor.fetchall()]
        logging.info(f"当前列: {columns}")

        conn.close()

        if added:
            logging.info(f"迁移成功完成，新增列: {added}")
        else:
            logging.info("所有列已存在，无需迁移")
        return True

    except Exception as e:
        logging.error(f"数据库迁移失败: {e}")
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = Path(__file__).parent.parent.parent / "data" / "trading.db"

    logging.info(f"数据库路径: {db_path}")
    success = run_migration(str(db_path))
    sys.exit(0 if success else 1)
