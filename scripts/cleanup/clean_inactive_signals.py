#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理不活跃股票的未执行交易信号

清理标准：
- 平均换手率 < 0.3% 或
- 平均成交量 < 500,000 股

这些股票不符合活跃度筛选标准，不应该被监控和产生信号
"""

import sqlite3
import sys
from datetime import datetime

# 设置输出编码为 UTF-8
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def clean_inactive_signals(db_path: str, min_turnover_rate: float = 0.3,
                           min_volume: int = 500000, dry_run: bool = False):
    """清理不活跃股票的未执行信号

    Args:
        db_path: 数据库路径
        min_turnover_rate: 最低换手率（%）
        min_volume: 最低成交量
        dry_run: 是否为试运行（不实际删除）
    """

    print("=" * 80)
    print("清理不活跃股票的未执行交易信号")
    print("=" * 80)
    print(f"数据库: {db_path}")
    print(f"筛选标准: 换手率 < {min_turnover_rate}% 且 成交量 < {min_volume:,}")
    print(f"模式: {'试运行（不删除）' if dry_run else '正式运行（将删除）'}")
    print("=" * 80)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. 查询不符合标准的股票及其信号（使用 AND 逻辑）
        print("\n正在查询不活跃股票...")
        cursor.execute('''
            SELECT s.id, s.code, s.name, s.avg_turnover_rate, s.avg_volume,
                   COUNT(ts.id) as signal_count
            FROM stocks s
            INNER JOIN trade_signals ts ON s.id = ts.stock_id
            WHERE ts.is_executed = 0
              AND s.avg_turnover_rate < ?
              AND s.avg_volume < ?
            GROUP BY s.id, s.code, s.name, s.avg_turnover_rate, s.avg_volume
            ORDER BY signal_count DESC
        ''', (min_turnover_rate, min_volume))

        stocks = cursor.fetchall()

        if not stocks:
            print("未找到不活跃股票的未执行信号")
            return

        print(f"\n找到 {len(stocks)} 只不活跃股票:")
        print(f"{'代码':<15} {'名称':<20} {'换手率%':<10} {'成交量':<12} {'信号数'}")
        print("-" * 80)

        total_signals = 0
        stock_ids = []

        for stock in stocks:
            stock_id, code, name, turnover, volume, signals = stock
            stock_ids.append(stock_id)
            total_signals += signals

            # 截断名称以适应显示
            display_name = name[:18] if len(name) > 18 else name
            print(f"{code:<15} {display_name:<20} {turnover:<10.4f} {volume:<12.0f} {signals}")

        print("-" * 80)
        print(f"总计: {len(stocks)} 只股票, {total_signals} 条未执行信号")

        if dry_run:
            print("\n[试运行模式] 不会删除任何数据")
            return

        # 2. 确认删除
        print(f"\n准备删除这 {total_signals} 条信号...")

        # 3. 删除信号
        placeholders = ','.join(['?' for _ in stock_ids])
        delete_query = f'''
            DELETE FROM trade_signals
            WHERE stock_id IN ({placeholders})
              AND is_executed = 0
        '''

        cursor.execute(delete_query, tuple(stock_ids))
        deleted_count = cursor.rowcount

        conn.commit()

        print(f"成功删除 {deleted_count} 条信号")

        # 4. 验证
        print("\n验证删除结果...")
        cursor.execute('''
            SELECT COUNT(*) FROM trade_signals ts
            INNER JOIN stocks s ON ts.stock_id = s.id
            WHERE ts.is_executed = 0
              AND s.avg_turnover_rate < ?
              AND s.avg_volume < ?
        ''', (min_turnover_rate, min_volume))

        remaining = cursor.fetchone()[0]

        if remaining == 0:
            print("验证通过: 所有不活跃股票的未执行信号已清理")
        else:
            print(f"警告: 仍有 {remaining} 条不活跃股票的未执行信号")

        print("\n" + "=" * 80)
        print("清理完成")
        print("=" * 80)

    except Exception as e:
        print(f"\n错误: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='清理不活跃股票的未执行交易信号')
    parser.add_argument('--db', default='simple_trade/data/trade.db',
                       help='数据库路径 (默认: simple_trade/data/trade.db)')
    parser.add_argument('--min-turnover', type=float, default=0.3,
                       help='最低换手率%% (默认: 0.3)')
    parser.add_argument('--min-volume', type=int, default=500000,
                       help='最低成交量 (默认: 500000)')
    parser.add_argument('--dry-run', action='store_true',
                       help='试运行模式，不实际删除')

    args = parser.parse_args()

    clean_inactive_signals(
        db_path=args.db,
        min_turnover_rate=args.min_turnover,
        min_volume=args.min_volume,
        dry_run=args.dry_run
    )
