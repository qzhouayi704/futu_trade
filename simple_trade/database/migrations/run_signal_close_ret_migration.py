#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移脚本 - 为 signal_performance 添加 day{1,3,5}_close_ret 列（诚实记分牌）。

每条 ALTER 独立执行并对 "duplicate column name" 容错，可安全重复运行。
用法: python run_signal_close_ret_migration.py [db_path]
"""

import sqlite3
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)

ALTERS = [
    "ALTER TABLE signal_performance ADD COLUMN day1_close_ret REAL",
    "ALTER TABLE signal_performance ADD COLUMN day3_close_ret REAL",
    "ALTER TABLE signal_performance ADD COLUMN day5_close_ret REAL",
]


def run_migration(db_path: str) -> bool:
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        for stmt in ALTERS:
            try:
                cursor.execute(stmt)
                logging.info(f"已执行: {stmt}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    logging.info(f"列已存在, 跳过: {stmt}")
                else:
                    raise
        conn.commit()

        cursor.execute("PRAGMA table_info(signal_performance)")
        cols = [r[1] for r in cursor.fetchall()]
        missing = [c for c in ("day1_close_ret", "day3_close_ret", "day5_close_ret") if c not in cols]
        conn.close()
        if missing:
            logging.error(f"迁移后仍缺列: {missing}")
            return False
        logging.info("signal_performance close_ret 列迁移成功完成")
        return True
    except Exception as e:
        logging.error(f"数据库迁移失败: {e}")
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = Path(__file__).parent.parent.parent / "data" / "trade.db"

    logging.info(f"数据库路径: {db_path}")
    success = run_migration(str(db_path))
    sys.exit(0 if success else 1)
