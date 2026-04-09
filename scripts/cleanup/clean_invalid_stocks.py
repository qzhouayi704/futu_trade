#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理无效股票脚本

清理数据库中无法订阅的股票，包括：
1. 已退市的股票
2. 富途API无法识别的股票
3. 无权限订阅的股票
4. ADR股票（美国存托凭证）
"""

import sqlite3
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 已知无效的股票代码列表
INVALID_STOCKS = [
    'US.LBPS',   # 未知股票 - 4D pharma
    'US.AVAI',   # AVANT TECHNOLOGIES INC - 订阅失败
    'US.VSSYW',  # VERSUS SYSTEMS INC 权证 - 已到期
]

# 已知的ADR股票和无法订阅的股票
ADR_AND_PROBLEM_STOCKS = [
    'US.SIEGY',  # 西门子(ADR)
    'US.LKNCY',  # 瑞幸咖啡
    'US.DIDIY',  # DiDi Global Inc
    'US.HTHIY',  # 本田(ADR)
    'US.SSNLF',  # 三星电子
    'US.VWSYF',  # VESTAS WIND SYSTEMS
    'US.ABLZF',  # ABB LTD
    'US.CVKD',   # Cadrenal Therapeutics
    'US.MDGL',   # Madrigal Pharmaceuticals
    'US.BR',     # Broadridge金融解决方案
    'US.NVDS',   # 1.5倍做空NVDA ETF-Tradr
    'US.SARK',   # Tradr 1X Short Innovation Daily ETF
    'US.TARK',   # Tradr 2X Long Innovation ETF
    'US.TSLL',   # 2倍做多TSLA ETF-Direxion
]


def clean_invalid_stocks(db_path: str, clean_adr: bool = True, auto_confirm: bool = False):
    """清理无效股票

    Args:
        db_path: 数据库路径
        clean_adr: 是否清理ADR股票
        auto_confirm: 是否自动确认（不询问用户）
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. 查询并删除明确无效的股票
        print("=" * 70)
        print("第一步：清理明确无效的股票")
        print("=" * 70)

        if INVALID_STOCKS:
            placeholders = ','.join(['?' for _ in INVALID_STOCKS])
            query = f"SELECT code, name FROM stocks WHERE code IN ({placeholders})"
            cursor.execute(query, INVALID_STOCKS)
            found_invalid = cursor.fetchall()

            if found_invalid:
                print(f"\n找到 {len(found_invalid)} 只无效股票:")
                for code, name in found_invalid:
                    print(f"  - {code:15} | {name}")

                if not auto_confirm:
                    confirm = input("\n确认删除这些无效股票吗？(y/n): ")
                    if confirm.lower() != 'y':
                        print("跳过删除无效股票")
                    else:
                        delete_query = f"DELETE FROM stocks WHERE code IN ({placeholders})"
                        cursor.execute(delete_query, INVALID_STOCKS)
                        conn.commit()
                        print(f"[OK] 成功删除 {cursor.rowcount} 只无效股票")
                else:
                    delete_query = f"DELETE FROM stocks WHERE code IN ({placeholders})"
                    cursor.execute(delete_query, INVALID_STOCKS)
                    conn.commit()
                    print(f"[OK] 成功删除 {cursor.rowcount} 只无效股票")
            else:
                print("没有找到需要清理的无效股票")

        # 2. 查询并删除ADR股票和问题股票
        if clean_adr and ADR_AND_PROBLEM_STOCKS:
            print("\n" + "=" * 70)
            print("第二步：清理ADR股票和无法订阅的股票")
            print("=" * 70)

            placeholders = ','.join(['?' for _ in ADR_AND_PROBLEM_STOCKS])
            query = f"SELECT code, name FROM stocks WHERE code IN ({placeholders})"
            cursor.execute(query, ADR_AND_PROBLEM_STOCKS)
            found_adr = cursor.fetchall()

            if found_adr:
                print(f"\n找到 {len(found_adr)} 只ADR/问题股票:")
                for code, name in found_adr:
                    print(f"  - {code:15} | {name}")

                if not auto_confirm:
                    confirm = input("\n确认删除这些ADR/问题股票吗？(y/n): ")
                    if confirm.lower() != 'y':
                        print("跳过删除ADR/问题股票")
                    else:
                        delete_query = f"DELETE FROM stocks WHERE code IN ({placeholders})"
                        cursor.execute(delete_query, ADR_AND_PROBLEM_STOCKS)
                        conn.commit()
                        print(f"[OK] 成功删除 {cursor.rowcount} 只ADR/问题股票")
                else:
                    delete_query = f"DELETE FROM stocks WHERE code IN ({placeholders})"
                    cursor.execute(delete_query, ADR_AND_PROBLEM_STOCKS)
                    conn.commit()
                    print(f"[OK] 成功删除 {cursor.rowcount} 只ADR/问题股票")
            else:
                print("没有找到需要清理的ADR/问题股票")

        # 3. 清理相关的K线数据
        print("\n" + "=" * 70)
        print("第三步：清理相关的K线数据")
        print("=" * 70)

        all_deleted_codes = INVALID_STOCKS + (ADR_AND_PROBLEM_STOCKS if clean_adr else [])
        if all_deleted_codes:
            placeholders = ','.join(['?' for _ in all_deleted_codes])

            # 查询有多少K线数据需要删除
            cursor.execute(
                f"SELECT COUNT(*) FROM kline_data WHERE stock_code IN ({placeholders})",
                all_deleted_codes
            )
            kline_count = cursor.fetchone()[0]

            if kline_count > 0:
                print(f"\n找到 {kline_count} 条相关K线数据")
                cursor.execute(
                    f"DELETE FROM kline_data WHERE stock_code IN ({placeholders})",
                    all_deleted_codes
                )
                conn.commit()
                print(f"[OK] 成功删除 {cursor.rowcount} 条K线数据")
            else:
                print("没有找到需要清理的K线数据")

        # 4. 显示清理后的统计信息
        print("\n" + "=" * 70)
        print("清理完成 - 统计信息")
        print("=" * 70)

        cursor.execute("SELECT COUNT(*) FROM stocks WHERE market='US'")
        us_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM stocks WHERE market='HK'")
        hk_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM stocks")
        total_count = cursor.fetchone()[0]

        print(f"\n当前股票池:")
        print(f"  - 美股: {us_count} 只")
        print(f"  - 港股: {hk_count} 只")
        print(f"  - 总计: {total_count} 只")
        print("\n[OK] 清理完成！")

    except Exception as e:
        print(f"\n[ERROR] 清理失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='清理无效股票和ADR股票')
    parser.add_argument('--no-adr', action='store_true', help='不清理ADR股票')
    parser.add_argument('--auto-confirm', action='store_true', help='自动确认，不询问用户')
    parser.add_argument('--db', default='simple_trade/data/trade.db', help='数据库路径')

    args = parser.parse_args()

    clean_invalid_stocks(
        db_path=args.db,
        clean_adr=not args.no_adr,
        auto_confirm=args.auto_confirm
    )
