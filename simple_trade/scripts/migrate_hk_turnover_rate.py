#!/usr/bin/env python3
"""
一次性迁移脚本：将港股K线数据中的 turnover_rate 从小数比例转为百分比形式

背景：
- 富途API港股K线返回的 turnover_rate 是小数比例 (0.01732 = 1.732%)
- 实时报价API返回的是百分比形式 (1.732 = 1.732%)
- 需要统一为百分比形式

迁移规则：
- 仅处理港股 (stock_code LIKE 'HK.%')
- 仅处理 turnover_rate < 1.0 的记录（避免已转换或异常高换手率的数据被二次转换）
- 将 turnover_rate 乘以 100

运行方式：
    python migrate_hk_turnover_rate.py
"""

import sqlite3
import os
import sys
import shutil
from datetime import datetime


DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'data', 'trade.db'
)


def main():
    if not os.path.exists(DB_PATH):
        print(f"数据库不存在: {DB_PATH}")
        sys.exit(1)

    # 备份数据库
    backup_path = DB_PATH + f'.bak_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    print(f"备份数据库 → {backup_path}")
    shutil.copy2(DB_PATH, backup_path)

    conn = sqlite3.connect(DB_PATH)

    # 统计待迁移数据
    count_before = conn.execute(
        "SELECT COUNT(*) FROM kline_data "
        "WHERE stock_code LIKE 'HK.%' AND turnover_rate > 0 AND turnover_rate < 1.0"
    ).fetchone()[0]

    total_hk = conn.execute(
        "SELECT COUNT(*) FROM kline_data WHERE stock_code LIKE 'HK.%' AND turnover_rate > 0"
    ).fetchone()[0]

    print(f"港股K线记录总数(有换手率): {total_hk}")
    print(f"待迁移记录数(turnover_rate < 1.0): {count_before}")

    if count_before == 0:
        print("无需迁移，已退出")
        conn.close()
        return

    # 迁移前样本
    print("\n--- 迁移前样本 ---")
    samples = conn.execute(
        "SELECT stock_code, time_key, turnover_rate FROM kline_data "
        "WHERE stock_code LIKE 'HK.%' AND turnover_rate > 0 AND turnover_rate < 1.0 "
        "ORDER BY time_key DESC LIMIT 5"
    ).fetchall()
    for s in samples:
        print(f"  {s[0]} | {s[1]} | {s[2]} → {round(s[2] * 100, 5)}")

    # 执行迁移
    conn.execute(
        "UPDATE kline_data SET turnover_rate = ROUND(turnover_rate * 100, 5) "
        "WHERE stock_code LIKE 'HK.%' AND turnover_rate > 0 AND turnover_rate < 1.0"
    )
    conn.commit()

    # 迁移后验证
    count_after = conn.execute(
        "SELECT COUNT(*) FROM kline_data "
        "WHERE stock_code LIKE 'HK.%' AND turnover_rate > 0 AND turnover_rate < 1.0"
    ).fetchone()[0]

    print(f"\n--- 迁移完成 ---")
    print(f"已转换: {count_before} 条记录")
    print(f"剩余未转换: {count_after} 条")

    # 迁移后样本
    print("\n--- 迁移后样本 ---")
    for s in samples:
        row = conn.execute(
            "SELECT turnover_rate FROM kline_data "
            "WHERE stock_code = ? AND time_key = ?",
            (s[0], s[1])
        ).fetchone()
        if row:
            print(f"  {s[0]} | {s[1]} | {row[0]}%")

    conn.close()
    print(f"\n备份文件: {backup_path}")
    print("如需回滚: 用备份文件替换 trade.db")


if __name__ == '__main__':
    main()
