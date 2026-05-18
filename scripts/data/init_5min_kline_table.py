#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化5分钟K线数据表

使用方法:
    python scripts/init_5min_kline_table.py
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.database.models import DatabaseSchema
from simple_trade.config.config import Config


def main():
    print("=" * 60)
    print("初始化5分钟K线数据表")
    print("=" * 60)

    # 加载配置
    config = Config()
    print(f"\n数据库路径: {config.database_path}")

    # 连接数据库
    db_manager = DatabaseManager(config.database_path)

    # 创建5分钟K线表
    print("\n正在创建 kline_5min_data 表...")
    try:
        db_manager.execute_update(DatabaseSchema.KLINE_5MIN_DATA_TABLE)
        print("✓ 表创建成功")
    except Exception as e:
        print(f"✗ 表创建失败: {e}")
        return

    # 创建索引
    print("\n正在创建索引...")
    indexes = [
        'CREATE INDEX IF NOT EXISTS idx_kline_5min_code ON kline_5min_data(stock_code)',
        'CREATE INDEX IF NOT EXISTS idx_kline_5min_time ON kline_5min_data(time_key)',
        'CREATE INDEX IF NOT EXISTS idx_kline_5min_code_time ON kline_5min_data(stock_code, time_key DESC)'
    ]

    for idx_sql in indexes:
        try:
            db_manager.execute_update(idx_sql)
            print(f"✓ 索引创建成功")
        except Exception as e:
            print(f"✗ 索引创建失败: {e}")

    # 验证表是否存在
    print("\n验证表结构...")
    try:
        result = db_manager.execute_query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='kline_5min_data'"
        )
        if result:
            print("✓ kline_5min_data 表已存在")

            # 查看表结构
            schema = db_manager.execute_query("PRAGMA table_info(kline_5min_data)")
            print("\n表结构:")
            print("-" * 60)
            for col in schema:
                print(f"  {col[1]:20s} {col[2]:15s} {'NOT NULL' if col[3] else ''}")
            print("-" * 60)
        else:
            print("✗ 表不存在")
    except Exception as e:
        print(f"✗ 验证失败: {e}")

    print("\n" + "=" * 60)
    print("初始化完成！")
    print("=" * 60)
    print("\n现在可以运行回测脚本了:")
    print("  python scripts/run_intraday_backtest.py -i")


if __name__ == '__main__':
    main()
