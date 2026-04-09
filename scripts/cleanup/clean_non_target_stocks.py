#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理非目标板块股票脚本

功能：删除不属于任何目标板块的美股
"""

import sys
import os
import logging
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from simple_trade.database.core.db_manager import DatabaseManager


def setup_logging():
    """配置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def query_non_target_stocks(db: DatabaseManager, market: str = 'US'):
    """查询不属于目标板块的股票

    Args:
        db: 数据库管理器
        market: 市场代码（US/HK）

    Returns:
        list: 股票列表 [(id, code, name), ...]
    """
    sql = '''
        SELECT s.id, s.code, s.name
        FROM stocks s
        WHERE s.market = ?
          AND s.id NOT IN (
            SELECT DISTINCT sp.stock_id
            FROM stock_plates sp
            JOIN plates p ON sp.plate_id = p.id
            WHERE p.is_target = 1
          )
        ORDER BY s.code
    '''

    try:
        rows = db.execute_query(sql, (market,))
        return rows if rows else []
    except Exception as e:
        logging.error(f"查询非目标板块股票失败: {e}")
        return []


def delete_stocks(db: DatabaseManager, stock_ids: list):
    """删除股票及其关联数据

    Args:
        db: 数据库管理器
        stock_ids: 股票ID列表

    Returns:
        dict: 删除结果统计
    """
    result = {
        'stocks_deleted': 0,
        'klines_deleted': 0,
        'signals_deleted': 0,
        'stock_plates_deleted': 0
    }

    if not stock_ids:
        return result

    try:
        placeholders = ','.join(['?' for _ in stock_ids])

        # 1. 删除关联的K线数据
        kline_sql = f'''
            DELETE FROM kline_data
            WHERE stock_code IN (
                SELECT code FROM stocks WHERE id IN ({placeholders})
            )
        '''
        result['klines_deleted'] = db.execute_update(kline_sql, stock_ids)
        logging.info(f"删除K线数据: {result['klines_deleted']}条")

        # 2. 删除关联的交易信号
        signal_sql = f'DELETE FROM trade_signals WHERE stock_id IN ({placeholders})'
        result['signals_deleted'] = db.execute_update(signal_sql, stock_ids)
        logging.info(f"删除交易信号: {result['signals_deleted']}条")

        # 3. 删除股票-板块关联
        stock_plate_sql = f'DELETE FROM stock_plates WHERE stock_id IN ({placeholders})'
        result['stock_plates_deleted'] = db.execute_update(stock_plate_sql, stock_ids)
        logging.info(f"删除股票-板块关联: {result['stock_plates_deleted']}条")

        # 4. 删除股票记录
        stock_sql = f'DELETE FROM stocks WHERE id IN ({placeholders})'
        result['stocks_deleted'] = db.execute_update(stock_sql, stock_ids)
        logging.info(f"删除股票记录: {result['stocks_deleted']}只")

        return result

    except Exception as e:
        logging.error(f"删除股票失败: {e}")
        raise


def main(dry_run: bool = False, auto_confirm: bool = False, market: str = 'US'):
    """主函数

    Args:
        dry_run: 是否为预览模式（不实际删除）
        auto_confirm: 是否自动确认（不询问用户）
        market: 市场代码（US/HK）
    """
    setup_logging()

    print("=" * 70)
    print("清理非目标板块股票")
    print("=" * 70)
    print(f"市场: {market}")
    print(f"模式: {'预览模式' if dry_run else '执行模式'}")
    print()

    # 初始化数据库
    db_path = 'simple_trade/data/trade.db'
    db = DatabaseManager(db_path)

    # 查询非目标板块股票
    logging.info(f"正在查询不属于目标板块的{market}股票...")
    non_target_stocks = query_non_target_stocks(db, market)

    if not non_target_stocks:
        print(f"\n✓ 没有找到需要清理的{market}股票")
        return

    # 显示待删除股票列表
    print(f"\n找到 {len(non_target_stocks)} 只不属于目标板块的{market}股票:")
    print("-" * 70)
    print(f"{'ID':<10} {'代码':<15} {'名称'}")
    print("-" * 70)

    for stock_id, code, name in non_target_stocks:
        print(f"{stock_id:<10} {code:<15} {name}")

    print("-" * 70)

    # 预览模式直接返回
    if dry_run:
        print(f"\n[预览模式] 将删除 {len(non_target_stocks)} 只股票")
        print("使用 --execute 参数执行实际删除")
        return

    # 确认删除
    if not auto_confirm:
        print()
        confirm = input(f"确认删除这 {len(non_target_stocks)} 只股票吗？(yes/no): ")
        if confirm.lower() not in ['yes', 'y']:
            print("已取消删除操作")
            return

    # 执行删除
    print(f"\n开始删除 {len(non_target_stocks)} 只股票...")
    stock_ids = [row[0] for row in non_target_stocks]

    try:
        result = delete_stocks(db, stock_ids)

        print("\n" + "=" * 70)
        print("删除完成")
        print("=" * 70)
        print(f"删除股票: {result['stocks_deleted']} 只")
        print(f"删除K线数据: {result['klines_deleted']} 条")
        print(f"删除交易信号: {result['signals_deleted']} 条")
        print(f"删除股票-板块关联: {result['stock_plates_deleted']} 条")

        # 显示清理后的统计信息
        print("\n" + "=" * 70)
        print("清理后统计")
        print("=" * 70)

        us_count = db.execute_query("SELECT COUNT(*) FROM stocks WHERE market='US'")[0][0]
        hk_count = db.execute_query("SELECT COUNT(*) FROM stocks WHERE market='HK'")[0][0]
        total_count = db.execute_query("SELECT COUNT(*) FROM stocks")[0][0]

        print(f"美股: {us_count} 只")
        print(f"港股: {hk_count} 只")
        print(f"总计: {total_count} 只")
        print("\n✓ 清理完成！")

    except Exception as e:
        print(f"\n✗ 删除失败: {e}")
        logging.error(f"删除操作失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='清理不属于目标板块的股票')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不实际删除')
    parser.add_argument('--execute', action='store_true', help='执行删除（与--dry-run互斥）')
    parser.add_argument('--auto-confirm', action='store_true', help='自动确认，不询问用户')
    parser.add_argument('--market', default='US', choices=['US', 'HK'], help='市场代码（默认US）')

    args = parser.parse_args()

    # 默认为预览模式，除非明确指定 --execute
    dry_run = not args.execute

    main(
        dry_run=dry_run,
        auto_confirm=args.auto_confirm,
        market=args.market
    )
