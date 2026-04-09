#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试异步数据库层功能
"""

import asyncio
import sys
import os
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 直接导入数据库模块，避免循环导入
from simple_trade.database.core.db_manager import DatabaseManager


async def test_async_database():
    """测试异步数据库操作"""
    print("=" * 60)
    print("测试异步数据库层")
    print("=" * 60)

    # 使用测试数据库
    db_path = "data/test_async.db"
    db_manager = DatabaseManager(db_path)

    try:
        # 测试1: 异步查询
        print("\n[测试1] 异步查询 - 获取所有股票")
        stocks = await db_manager.async_execute_query(
            "SELECT stock_code, stock_name FROM stocks LIMIT 5"
        )
        print(f"✓ 查询成功，返回 {len(stocks)} 条记录")
        for stock in stocks:
            print(f"  - {stock[0]}: {stock[1]}")

        # 测试2: 异步插入
        print("\n[测试2] 异步插入 - 插入测试股票")
        test_stock_code = "TEST.HK"
        test_stock_name = "异步测试股票"

        # 先删除可能存在的测试数据
        await db_manager.async_execute_delete(
            "DELETE FROM stocks WHERE stock_code = ?",
            (test_stock_code,)
        )

        # 插入新记录
        stock_id = await db_manager.async_execute_insert(
            "INSERT INTO stocks (stock_code, stock_name, market) VALUES (?, ?, ?)",
            (test_stock_code, test_stock_name, "HK")
        )
        print(f"✓ 插入成功，新记录ID: {stock_id}")

        # 测试3: 异步更新
        print("\n[测试3] 异步更新 - 更新测试股票")
        updated_name = "异步测试股票(已更新)"
        rows_affected = await db_manager.async_execute_update(
            "UPDATE stocks SET stock_name = ? WHERE stock_code = ?",
            (updated_name, test_stock_code)
        )
        print(f"✓ 更新成功，影响 {rows_affected} 行")

        # 验证更新
        result = await db_manager.async_execute_query(
            "SELECT stock_name FROM stocks WHERE stock_code = ?",
            (test_stock_code,)
        )
        if result:
            print(f"  验证: {result[0][0]}")

        # 测试4: 异步删除
        print("\n[测试4] 异步删除 - 删除测试股票")
        rows_deleted = await db_manager.async_execute_delete(
            "DELETE FROM stocks WHERE stock_code = ?",
            (test_stock_code,)
        )
        print(f"✓ 删除成功，删除 {rows_deleted} 行")

        # 测试5: 并发查询
        print("\n[测试5] 并发查询 - 测试异步性能")
        tasks = [
            db_manager.async_execute_query("SELECT COUNT(*) FROM stocks"),
            db_manager.async_execute_query("SELECT COUNT(*) FROM plates"),
            db_manager.async_execute_query("SELECT COUNT(*) FROM trade_signals"),
        ]
        results = await asyncio.gather(*tasks)
        print(f"✓ 并发查询成功")
        print(f"  - 股票数量: {results[0][0][0] if results[0] else 0}")
        print(f"  - 板块数量: {results[1][0][0] if results[1] else 0}")
        print(f"  - 信号数量: {results[2][0][0] if results[2] else 0}")

        print("\n" + "=" * 60)
        print("✓ 所有测试通过！异步数据库层工作正常")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # 清理
        await db_manager.async_close_all_connections()
        # 删除测试数据库
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"\n清理: 已删除测试数据库 {db_path}")

    return True


if __name__ == "__main__":
    success = asyncio.run(test_async_database())
    sys.exit(0 if success else 1)
