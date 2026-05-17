#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘后基准更新任务

收盘后运行，遍历所有活跃股票，更新 market_baselines 表。
支持首次运行时回溯历史数据（60天），加速冷启动。

使用方式：
    python -m simple_trade.tasks.update_baselines
"""

import logging
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
project_root = str(Path(__file__).resolve().parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.services.baseline.baseline_updater import BaselineUpdater

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("baseline_task")


def get_active_stocks(db_manager) -> list:
    """获取需要更新基准的活跃股票列表"""
    # 优先从 daily_active_stocks 获取最近活跃的股票
    rows = db_manager.execute_query("""
        SELECT DISTINCT stock_code FROM daily_active_stocks
        WHERE is_active = 1
        ORDER BY check_date DESC
        LIMIT 200
    """)
    if rows:
        return [r[0] for r in rows]
    # 降级：从 kline_data 取有数据的股票
    rows = db_manager.execute_query("""
        SELECT DISTINCT stock_code FROM kline_data
        ORDER BY stock_code
    """)
    return [r[0] for r in rows] if rows else []


def main():
    logger.info("========== 开始盘后基准更新 ==========")

    db_path = str(Path(project_root) / "simple_trade" / "data" / "trade.db")
    db_manager = DatabaseManager(db_path)
    updater = BaselineUpdater(db_manager)

    stocks = get_active_stocks(db_manager)
    logger.info(f"待更新股票数: {len(stocks)}")

    success_count = 0
    for i, code in enumerate(stocks, 1):
        try:
            # 20日窗口
            n20 = updater.update_all_for_stock(code, window_days=20)
            # 60日窗口（冷启动加速）
            n60 = updater.update_all_for_stock(code, window_days=60)
            if n20 > 0 or n60 > 0:
                success_count += 1
            if i % 50 == 0:
                logger.info(f"进度: {i}/{len(stocks)}, 成功: {success_count}")
        except Exception as e:
            logger.warning(f"更新 {code} 失败: {e}")

    logger.info(f"========== 更新完成: {success_count}/{len(stocks)} 只股票 ==========")


if __name__ == "__main__":
    main()
