#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移脚本 - 添加资金流向和大单追踪表
"""

import sqlite3
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)


def run_migration(db_path: str):
    """执行数据库迁移"""
    migration_file = Path(__file__).parent / "add_capital_flow_tables.sql"

    if not migration_file.exists():
        logging.error(f"迁移文件不存在: {migration_file}")
        return False

    try:
        # 读取SQL脚本
        with open(migration_file, 'r', encoding='utf-8') as f:
            sql_script = f.read()

        # 连接数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 执行SQL脚本
        cursor.executescript(sql_script)
        conn.commit()

        logging.info("数据库迁移成功完成")
        logging.info("已创建表: capital_flow_cache, big_order_tracking")

        # 验证表是否创建成功
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('capital_flow_cache', 'big_order_tracking')
        """)
        tables = cursor.fetchall()
        logging.info(f"验证表: {[t[0] for t in tables]}")

        conn.close()
        return True

    except Exception as e:
        logging.error(f"数据库迁移失败: {e}")
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        # 默认数据库路径
        db_path = Path(__file__).parent.parent.parent / "data" / "trading.db"

    logging.info(f"数据库路径: {db_path}")
    success = run_migration(str(db_path))
    sys.exit(0 if success else 1)
