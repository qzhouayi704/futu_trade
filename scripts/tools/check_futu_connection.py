#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
富途API连接检查脚本

用法：
python scripts/check_futu_connection.py
"""

import os
import sys
import logging

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from simple_trade.config.config import Config
from simple_trade.api.futu_client import FutuClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_connection():
    """检查富途API连接"""
    logger.info("=" * 60)
    logger.info("富途API连接检查")
    logger.info("=" * 60)

    try:
        # 加载配置
        config = Config()
        logger.info(f"配置信息：")
        logger.info(f"  - Host: {config.futu_host}")
        logger.info(f"  - Port: {config.futu_port}")

        # 创建客户端
        logger.info("\n正在连接富途OpenD...")
        futu_client = FutuClient(host=config.futu_host, port=config.futu_port)

        # 连接到富途API
        if not futu_client.connect():
            logger.error("❌ 富途API连接失败！")
            logger.error("\n请检查：")
            logger.error("  1. 富途OpenD是否已启动")
            logger.error("  2. 富途客户端是否已登录")
            logger.error("  3. 配置文件中的host和port是否正确")
            logger.error("  4. 网络连接是否正常")
            logger.error("  5. 防火墙是否阻止了连接")
            return

        # 检查连接状态
        if futu_client.is_available():
            logger.info("✅ 富途API连接成功！")

            # 测试获取K线额度
            logger.info("\n正在检查K线额度...")
            from simple_trade.services.analysis.kline.kline_fetcher import KlineFetcher
            kline_fetcher = KlineFetcher(futu_client, config)
            quota_info = kline_fetcher.get_quota_info()

            if quota_info:
                logger.info("✅ K线额度信息：")
                logger.info(f"  - 剩余额度：{quota_info.get('remaining', 'N/A')}")
                logger.info(f"  - 已使用：{quota_info.get('used', 'N/A')}")
                logger.info(f"  - 总额度：{quota_info.get('total', 'N/A')}")
                logger.info(f"  - 状态：{quota_info.get('status', 'N/A')}")

                if quota_info.get('remaining', 0) > 0:
                    logger.info("\n✅ 可以开始下载K线数据")
                else:
                    logger.warning("\n⚠️ K线额度不足，无法下载数据")
            else:
                logger.error("❌ 无法获取K线额度信息")

            # 测试下载一只股票的K线数据
            logger.info("\n正在测试下载K线数据（HK.00700 腾讯控股）...")
            test_data = kline_fetcher.fetch_kline_data('HK.00700', 30)
            if test_data:
                logger.info(f"✅ 测试成功！获取了 {len(test_data)} 条K线数据")
                logger.info(f"  - 最早日期：{test_data[0]['time_key']}")
                logger.info(f"  - 最新日期：{test_data[-1]['time_key']}")
            else:
                logger.error("❌ 测试失败！无法获取K线数据")

        else:
            logger.error("❌ 富途API连接失败！")
            logger.error("\n请检查：")
            logger.error("  1. 富途OpenD是否已启动")
            logger.error("  2. 配置文件中的host和port是否正确")
            logger.error("  3. 网络连接是否正常")
            logger.error("  4. 防火墙是否阻止了连接")

    except Exception as e:
        logger.error(f"❌ 检查过程中出错: {e}")
        import traceback
        traceback.print_exc()

    logger.info("\n" + "=" * 60)


if __name__ == '__main__':
    check_connection()
