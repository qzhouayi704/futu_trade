#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测数据库初始化脚本

用于初始化回测所需的数据库表结构
"""

import os
import sys
import logging

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from simple_trade.database.core.db_manager import DatabaseManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def init_database():
    """初始化数据库"""
    try:
        # 数据库路径
        db_path = os.path.join(project_root, 'simple_trade', 'data', 'trade.db')

        logger.info(f"数据库路径: {db_path}")
        logger.info("开始初始化数据库...")

        # 创建数据库管理器
        db_manager = DatabaseManager(db_path)

        # 初始化数据库（创建表和索引）
        success = db_manager.init_database()

        if success:
            logger.info("✅ 数据库初始化成功！")
            logger.info("已创建以下表：")
            logger.info("  - stocks (股票表)")
            logger.info("  - plates (板块表)")
            logger.info("  - stock_plates (股票-板块关联表)")
            logger.info("  - kline_data (K线数据表)")
            logger.info("  - trade_signals (交易信号表)")
            logger.info("  - system_config (系统配置表)")
            logger.info("  - plate_match_log (板块匹配日志表)")
            logger.info("  - trading_records (交易记录表)")
            logger.info("  - daily_active_stocks (每日活跃股票表)")
            logger.info("  - news (新闻表)")
            logger.info("  - news_stocks (新闻-股票关联表)")
            logger.info("  - news_plates (新闻-板块关联表)")
            logger.info("")
            logger.info("现在可以运行回测了：")
            logger.info("  python scripts/run_low_turnover_backtest.py --start 2024-02-06 --end 2025-02-06")
            return True
        else:
            logger.error("❌ 数据库初始化失败")
            return False

    except Exception as e:
        logger.error(f"❌ 初始化过程出错: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = init_database()
    sys.exit(0 if success else 1)
