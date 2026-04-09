#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将低活跃股票标记为永久排除

将所有 is_low_activity=1 的股票的 low_activity_count 设置为 3，
使其被永久排除，不再参与活跃度筛选。
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from simple_trade.database.core.db_manager import DatabaseManager


def mark_permanent_exclusion(db_path: str, market: str = 'US', dry_run: bool = False):
    """将低活跃股票标记为永久排除

    Args:
        db_path: 数据库路径
        market: 市场代码（US/HK）
        dry_run: 是否只查看不执行
    """
    db = DatabaseManager(db_path)

    print(f"\n{'='*70}")
    print(f"标记{market}市场低活跃股票为永久排除")
    print(f"{'='*70}\n")

    # 1. 查询当前低活跃股票
    query = """
        SELECT id, code, name, low_activity_count
        FROM stocks
        WHERE market = ? AND is_low_activity = 1
    """
    low_activity_stocks = db.execute_query(query, (market,))

    if not low_activity_stocks:
        print("没有找到低活跃股票")
        return

    print(f"找到 {len(low_activity_stocks)} 只低活跃股票：")

    # 统计不同 low_activity_count 的股票数量
    count_stats = {}
    for stock_id, code, name, count in low_activity_stocks:
        count = count if count is not None else 0
        if count not in count_stats:
            count_stats[count] = []
        count_stats[count].append((stock_id, code, name))

    print("\n按低活跃次数分组：")
    for count in sorted(count_stats.keys()):
        stocks = count_stats[count]
        print(f"  - 低活跃次数 {count}: {len(stocks)} 只")
        if count < 3:
            print(f"    （将被更新为 3，标记为永久排除）")

    if dry_run:
        print("\n[预览模式] 不会执行更新操作")
        return

    # 2. 更新所有低活跃股票为永久排除
    update_query = """
        UPDATE stocks
        SET low_activity_count = 3
        WHERE market = ? AND is_low_activity = 1 AND (low_activity_count IS NULL OR low_activity_count < 3)
    """

    updated_count = db.execute_update(update_query, (market,))

    print(f"\n{'='*70}")
    print(f"更新完成")
    print(f"{'='*70}")
    print(f"已将 {updated_count} 只股票标记为永久排除（low_activity_count = 3）")

    # 3. 验证结果
    verify_query = """
        SELECT COUNT(*)
        FROM stocks
        WHERE market = ? AND is_low_activity = 1 AND low_activity_count >= 3
    """
    permanent_count = db.execute_query(verify_query, (market,))[0][0]

    print(f"\n当前永久排除的{market}股票: {permanent_count} 只")
    print("\n✓ 标记完成！这些股票将被永久排除，不再参与活跃度筛选。")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='将低活跃股票标记为永久排除')
    parser.add_argument('--market', default='US', choices=['US', 'HK'], help='市场代码（默认US）')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不执行更新')

    args = parser.parse_args()

    db_path = 'simple_trade/data/trade.db'
    mark_permanent_exclusion(db_path, args.market, args.dry_run)
