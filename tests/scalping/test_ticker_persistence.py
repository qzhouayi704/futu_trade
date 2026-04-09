#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试逐笔数据持久化功能
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from simple_trade.database.core.db_manager import DatabaseManager


def test_ticker_persistence():
    """测试逐笔数据持久化功能"""

    print("=== 测试逐笔数据持久化功能 ===\n")

    # 1. 初始化数据库
    print("步骤1：初始化数据库管理器")
    db = DatabaseManager("simple_trade/data/trade.db")
    print("[OK] 数据库管理器已初始化\n")

    # 2. 检查表是否存在
    print("步骤2：检查 ticker_data 表")
    with db.conn_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ticker_data'"
        )
        if cursor.fetchone():
            print("[OK] ticker_data 表已存在\n")
        else:
            print("[ERROR] ticker_data 表不存在\n")
            return

    # 3. 测试查询接口
    print("步骤3：测试查询接口")

    # 获取 HK.02706 的数据统计
    stats = db.ticker_queries.get_ticker_statistics("HK.02706")
    if stats:
        print(f"[OK] HK.02706 统计信息:")
        print(f"  - 总记录数: {stats.get('total_count', 0)}")
        print(f"  - 总成交量: {stats.get('total_volume', 0)}")
        print(f"  - 总成交额: {stats.get('total_turnover', 0):.2f}")
        print(f"  - 买入笔数: {stats.get('buy_count', 0)}")
        print(f"  - 卖出笔数: {stats.get('sell_count', 0)}")
        print(f"  - 中性笔数: {stats.get('neutral_count', 0)}")

        if stats.get('first_time'):
            from datetime import datetime
            first_time = datetime.fromtimestamp(stats['first_time'] / 1000)
            last_time = datetime.fromtimestamp(stats['last_time'] / 1000)
            print(f"  - 时间范围: {first_time} ~ {last_time}")
    else:
        print("[INFO] HK.02706 暂无逐笔数据")

    print("\n步骤4：获取最近 10 笔数据")
    recent_data = db.ticker_queries.get_ticker_data("HK.02706", limit=10)
    if recent_data:
        print(f"[OK] 获取到 {len(recent_data)} 笔数据:")
        for i, tick in enumerate(recent_data[:5], 1):
            from datetime import datetime
            tick_time = datetime.fromtimestamp(tick['timestamp'] / 1000)
            print(f"  {i}. {tick_time} | 价格: {tick['price']} | 量: {tick['volume']} | 方向: {tick['direction']}")
    else:
        print("[INFO] 暂无数据")

    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    test_ticker_persistence()
