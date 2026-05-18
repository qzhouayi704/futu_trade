#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移脚本：移除 is_hot 字段

功能：
1. 备份当前数据库
2. 移除 stocks 表的 is_hot 字段
3. 移除相关索引
"""

import sqlite3
import shutil
import os
import sys
from datetime import datetime

# 设置输出编码为 UTF-8
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def backup_database(db_path: str) -> str:
    """备份数据库"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = f"{db_path}.backup_{timestamp}"

    print(f"正在备份数据库...")
    print(f"源文件: {db_path}")
    print(f"备份文件: {backup_path}")

    shutil.copy2(db_path, backup_path)
    print(f"✓ 数据库备份完成")

    return backup_path


def migrate_remove_is_hot(db_path: str):
    """移除 is_hot 字段"""

    print("\n" + "=" * 60)
    print("数据库迁移：移除 is_hot 字段")
    print("=" * 60)

    # 1. 备份数据库
    backup_path = backup_database(db_path)

    # 2. 连接数据库
    print("\n正在连接数据库...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 3. 检查 is_hot 字段是否存在
        print("\n检查 is_hot 字段...")
        cursor.execute("PRAGMA table_info(stocks)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]

        if 'is_hot' not in column_names:
            print("✓ is_hot 字段不存在，无需迁移")
            conn.close()
            return

        print(f"✓ 找到 is_hot 字段")

        # 4. 统计 is_hot=1 的股票数量
        cursor.execute("SELECT COUNT(*) FROM stocks WHERE is_hot = 1")
        hot_count = cursor.fetchone()[0]
        print(f"  当前标记为热门的股票数量: {hot_count}")

        # 5. 创建新表（不包含 is_hot 字段）
        print("\n创建新表结构...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stocks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code VARCHAR(20) UNIQUE NOT NULL,
                name VARCHAR(100),
                market VARCHAR(10) NOT NULL,
                is_manual BOOLEAN DEFAULT FALSE,
                stock_priority INTEGER DEFAULT 0,
                heat_score REAL DEFAULT 0,
                avg_turnover_rate REAL DEFAULT 0,
                avg_volume REAL DEFAULT 0,
                active_days INTEGER DEFAULT 0,
                heat_update_time TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_low_activity INTEGER DEFAULT 0,
                low_activity_checked_at TEXT,
                is_otc INTEGER DEFAULT 0,
                activity_score REAL DEFAULT 0,
                last_activity_check TIMESTAMP,
                low_activity_count INTEGER DEFAULT 0
            )
        ''')
        print("✓ 新表创建完成")

        # 6. 复制数据（排除 is_hot 字段）
        print("\n复制数据到新表...")
        cursor.execute('''
            INSERT INTO stocks_new (
                id, code, name, market, is_manual, stock_priority,
                heat_score, avg_turnover_rate, avg_volume, active_days,
                heat_update_time, created_at, updated_at,
                is_low_activity, low_activity_checked_at, is_otc,
                activity_score, last_activity_check, low_activity_count
            )
            SELECT
                id, code, name, market, is_manual, stock_priority,
                heat_score, avg_turnover_rate, avg_volume, active_days,
                heat_update_time, created_at, updated_at,
                is_low_activity, low_activity_checked_at, is_otc,
                activity_score, last_activity_check, low_activity_count
            FROM stocks
        ''')

        copied_count = cursor.rowcount
        print(f"✓ 已复制 {copied_count} 条记录")

        # 7. 删除旧表
        print("\n删除旧表...")
        cursor.execute("DROP TABLE stocks")
        print("✓ 旧表已删除")

        # 8. 重命名新表
        print("\n重命名新表...")
        cursor.execute("ALTER TABLE stocks_new RENAME TO stocks")
        print("✓ 新表已重命名为 stocks")

        # 9. 重建索引（排除 is_hot 索引）
        print("\n重建索引...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_code ON stocks(code)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_market ON stocks(market)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_manual ON stocks(is_manual)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_low_activity ON stocks(is_low_activity)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_otc ON stocks(is_otc)")
        print("✓ 索引重建完成")

        # 10. 提交事务
        conn.commit()
        print("\n✓ 迁移完成！")

        # 11. 验证
        print("\n验证迁移结果...")
        cursor.execute("PRAGMA table_info(stocks)")
        new_columns = cursor.fetchall()
        new_column_names = [col[1] for col in new_columns]

        if 'is_hot' in new_column_names:
            print("✗ 错误：is_hot 字段仍然存在")
        else:
            print("✓ is_hot 字段已成功移除")

        cursor.execute("SELECT COUNT(*) FROM stocks")
        final_count = cursor.fetchone()[0]
        print(f"✓ 最终股票数量: {final_count}")

        print("\n" + "=" * 60)
        print("迁移总结")
        print("=" * 60)
        print(f"备份文件: {backup_path}")
        print(f"移除字段: is_hot")
        print(f"原热门股数量: {hot_count}")
        print(f"迁移记录数: {copied_count}")
        print(f"最终记录数: {final_count}")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ 迁移失败: {e}")
        conn.rollback()
        print(f"\n可以从备份恢复: {backup_path}")
        raise

    finally:
        conn.close()


if __name__ == '__main__':
    # 数据库路径
    db_path = 'simple_trade/data/trade.db'

    if not os.path.exists(db_path):
        print(f"错误：数据库文件不存在: {db_path}")
        exit(1)

    # 执行迁移
    migrate_remove_is_hot(db_path)

    print("\n迁移脚本执行完成！")
