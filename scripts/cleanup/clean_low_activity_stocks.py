"""清理低活跃股票脚本

删除已标记为低活跃的股票及其关联数据
"""
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from simple_trade.database.core.db_manager import DatabaseManager


def clean_low_activity_stocks(db_path: str, market: str = 'US', dry_run: bool = False, auto_confirm: bool = False):
    """清理低活跃股票

    Args:
        db_path: 数据库路径
        market: 市场代码（US/HK）
        dry_run: 是否只查看不执行
        auto_confirm: 是否自动确认删除
    """
    db = DatabaseManager(db_path)

    print(f"\n{'='*70}")
    print(f"清理{market}市场低活跃股票")
    print(f"{'='*70}\n")

    # 1. 查询低活跃股票
    query = """
        SELECT id, code, name, is_low_activity, low_activity_count
        FROM stocks
        WHERE market = ? AND is_low_activity = 1
    """
    low_activity_stocks = db.execute_query(query, (market,))

    if not low_activity_stocks:
        print("没有找到低活跃股票")
        return

    print(f"找到 {len(low_activity_stocks)} 只低活跃股票：")
    for stock_id, code, name, is_low, count in low_activity_stocks:
        print(f"  - {code} {name} (低活跃次数: {count})")

    if dry_run:
        print("\n[预览模式] 不会执行删除操作")
        return

    # 确认删除
    if not auto_confirm:
        print(f"\n警告：即将删除 {len(low_activity_stocks)} 只股票及其关联数据")
        confirm = input("确认删除？(yes/no): ")
        if confirm.lower() not in ['yes', 'y']:
            print("已取消操作")
            return

    # 2. 删除关联数据
    stock_ids = [str(stock[0]) for stock in low_activity_stocks]
    stock_ids_str = ','.join(stock_ids)

    # 删除K线数据
    kline_query = f"DELETE FROM klines WHERE stock_id IN ({stock_ids_str})"
    kline_deleted = db.execute_update(kline_query)
    print(f"\n删除K线数据: {kline_deleted} 条")

    # 删除交易信号
    signal_query = f"DELETE FROM trade_signals WHERE stock_id IN ({stock_ids_str})"
    signal_deleted = db.execute_update(signal_query)
    print(f"删除交易信号: {signal_deleted} 条")

    # 删除股票-板块关系
    relation_query = f"DELETE FROM stock_plates WHERE stock_id IN ({stock_ids_str})"
    relation_deleted = db.execute_update(relation_query)
    print(f"删除股票-板块关系: {relation_deleted} 条")

    # 3. 删除股票
    stock_query = f"DELETE FROM stocks WHERE id IN ({stock_ids_str})"
    stock_deleted = db.execute_update(stock_query)
    print(f"删除股票: {stock_deleted} 只")

    # 4. 验证结果
    remaining_count_query = "SELECT COUNT(*) FROM stocks WHERE market = ?"
    remaining_count = db.execute_query(remaining_count_query, (market,))[0][0]

    print(f"\n{'='*70}")
    print(f"清理完成")
    print(f"{'='*70}")
    print(f"剩余{market}股票: {remaining_count} 只")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='清理低活跃股票')
    parser.add_argument('--market', default='US', choices=['US', 'HK'], help='市场代码（默认US）')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不执行删除')
    parser.add_argument('--auto-confirm', action='store_true', help='自动确认删除')

    args = parser.parse_args()

    db_path = 'simple_trade/data/trade.db'
    clean_low_activity_stocks(db_path, args.market, args.dry_run, args.auto_confirm)
