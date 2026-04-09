#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
激进策略测试脚本

测试激进策略的完整流程：
1. 板块强势度计算
2. 龙头股筛选
3. 信号生成
4. 风险检查
"""

import sys
import os
import asyncio
import logging

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.config.config import ConfigManager
from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.services import PlateManager
from simple_trade.services.trading.aggressive.aggressive_trade_service import AggressiveTradeService
from simple_trade.api.futu_client import FutuClient
from simple_trade.api.subscription_manager import SubscriptionManager
from simple_trade.api.quote_service import QuoteService
from simple_trade.services import KlineDataService
from simple_trade.services.subscription.subscription_helper import SubscriptionHelper

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_aggressive_strategy_initialization():
    """测试激进策略服务初始化"""
    logger.info("=" * 60)
    logger.info("测试1: 激进策略服务初始化")
    logger.info("=" * 60)

    try:
        # 初始化配置
        config = ConfigManager()

        # 初始化数据库
        db_manager = DatabaseManager(config.database_path)
        db_manager.init_database()

        # 初始化富途客户端
        futu_client = FutuClient(config.futu_host, config.futu_port)
        futu_client.connect()

        # 初始化订阅管理器和报价服务
        subscription_manager = SubscriptionManager(futu_client)
        quote_service = QuoteService(futu_client, subscription_manager)

        # 初始化实时服务
        realtime_service = SubscriptionHelper(
            db_manager,
            futu_client,
            subscription_manager,
            quote_service,
            config
        )

        # 初始化K线服务
        kline_service = KlineDataService(
            db_manager,
            futu_client,
            config
        )

        # 初始化板块管理器
        plate_manager = PlateManager(db_manager)

        # 初始化激进策略服务
        aggressive_service = AggressiveTradeService(
            db_manager=db_manager,
            config=config,
            realtime_service=realtime_service,
            plate_manager=plate_manager,
            kline_service=kline_service
        )

        logger.info("✓ 激进策略服务初始化成功")
        logger.info(f"  - 策略配置: {aggressive_service.strategy_config.get('name', '未知')}")
        logger.info(f"  - 板块强势度阈值: {aggressive_service.strategy_config.get('plate_filter', {}).get('min_strength_score', 70)}")
        logger.info(f"  - 最大日信号数: {aggressive_service.strategy_config.get('signal', {}).get('max_daily_signals', 2)}")

        # 清理
        futu_client.disconnect()

        return True

    except Exception as e:
        logger.error(f"✗ 激进策略服务初始化失败: {e}", exc_info=True)
        return False


async def test_plate_strength_calculation():
    """测试板块强势度计算"""
    logger.info("\n" + "=" * 60)
    logger.info("测试2: 板块强势度计算")
    logger.info("=" * 60)

    try:
        # 初始化配置
        config = ConfigManager()

        # 初始化数据库
        db_manager = DatabaseManager(config.database_path)

        # 初始化富途客户端
        futu_client = FutuClient(config.futu_host, config.futu_port)
        futu_client.connect()

        # 初始化订阅管理器和报价服务
        subscription_manager = SubscriptionManager(futu_client)
        quote_service = QuoteService(futu_client, subscription_manager)

        # 初始化实时服务
        realtime_service = SubscriptionHelper(
            db_manager,
            futu_client,
            subscription_manager,
            quote_service,
            config
        )

        # 初始化K线服务
        kline_service = KlineDataService(
            db_manager,
            futu_client,
            config
        )

        # 初始化板块管理器
        plate_manager = PlateManager(db_manager)

        # 初始化激进策略服务
        aggressive_service = AggressiveTradeService(
            db_manager=db_manager,
            config=config,
            realtime_service=realtime_service,
            plate_manager=plate_manager,
            kline_service=kline_service
        )

        # 获取强势板块
        strong_plates = await aggressive_service._get_strong_plates()

        if strong_plates:
            logger.info(f"✓ 找到 {len(strong_plates)} 个强势板块")
            for i, plate in enumerate(strong_plates, 1):
                logger.info(f"  {i}. {plate.plate_name} ({plate.plate_code})")
                logger.info(f"     - 强势度: {plate.strength_score:.1f}分")
                logger.info(f"     - 上涨占比: {plate.up_stock_ratio:.1%}")
                logger.info(f"     - 平均涨幅: {plate.avg_change_pct:.2f}%")
                logger.info(f"     - 龙头数量: {plate.leader_count}")
                logger.info(f"     - 总股票数: {plate.total_stocks}")
        else:
            logger.warning("✗ 未找到强势板块")

        # 清理
        futu_client.disconnect()

        return len(strong_plates) > 0

    except Exception as e:
        logger.error(f"✗ 板块强势度计算失败: {e}", exc_info=True)
        return False


async def test_signal_generation():
    """测试信号生成"""
    logger.info("\n" + "=" * 60)
    logger.info("测试3: 信号生成")
    logger.info("=" * 60)

    try:
        # 初始化配置
        config = ConfigManager()

        # 初始化数据库
        db_manager = DatabaseManager(config.database_path)

        # 初始化富途客户端
        futu_client = FutuClient(config.futu_host, config.futu_port)
        futu_client.connect()

        # 初始化订阅管理器和报价服务
        subscription_manager = SubscriptionManager(futu_client)
        quote_service = QuoteService(futu_client, subscription_manager)

        # 初始化实时服务
        realtime_service = SubscriptionHelper(
            db_manager,
            futu_client,
            subscription_manager,
            quote_service,
            config
        )

        # 初始化K线服务
        kline_service = KlineDataService(
            db_manager,
            futu_client,
            config
        )

        # 初始化板块管理器
        plate_manager = PlateManager(db_manager)

        # 初始化激进策略服务
        aggressive_service = AggressiveTradeService(
            db_manager=db_manager,
            config=config,
            realtime_service=realtime_service,
            plate_manager=plate_manager,
            kline_service=kline_service
        )

        # 生成信号
        signals = await aggressive_service.generate_signals()

        if signals:
            logger.info(f"✓ 成功生成 {len(signals)} 个交易信号")
            for i, signal in enumerate(signals, 1):
                logger.info(f"  {i}. {signal['stock_name']} ({signal['stock_code']})")
                logger.info(f"     - 信号类型: {signal['signal_type']}")
                logger.info(f"     - 当前价格: {signal['price']:.2f}")
                logger.info(f"     - 所属板块: {signal['plate_name']}")
                logger.info(f"     - 板块强势度: {signal['plate_strength']:.1f}分")
                logger.info(f"     - 信号评分: {signal['signal_score']:.1f}分")
                logger.info(f"     - 信号原因: {signal['reason']}")
        else:
            logger.warning("✗ 未生成交易信号（可能当前市场条件不满足）")

        # 清理
        futu_client.disconnect()

        return True

    except Exception as e:
        logger.error(f"✗ 信号生成失败: {e}", exc_info=True)
        return False


async def test_risk_check():
    """测试风险检查"""
    logger.info("\n" + "=" * 60)
    logger.info("测试4: 风险检查")
    logger.info("=" * 60)

    try:
        # 初始化配置
        config = ConfigManager()

        # 初始化数据库
        db_manager = DatabaseManager(config.database_path)

        # 初始化富途客户端
        futu_client = FutuClient(config.futu_host, config.futu_port)
        futu_client.connect()

        # 初始化订阅管理器和报价服务
        subscription_manager = SubscriptionManager(futu_client)
        quote_service = QuoteService(futu_client, subscription_manager)

        # 初始化实时服务
        realtime_service = SubscriptionHelper(
            db_manager,
            futu_client,
            subscription_manager,
            quote_service,
            config
        )

        # 初始化K线服务
        kline_service = KlineDataService(
            db_manager,
            futu_client,
            config
        )

        # 初始化板块管理器
        plate_manager = PlateManager(db_manager)

        # 初始化激进策略服务
        aggressive_service = AggressiveTradeService(
            db_manager=db_manager,
            config=config,
            realtime_service=realtime_service,
            plate_manager=plate_manager,
            kline_service=kline_service
        )

        # 检查持仓风险
        risk_results = await aggressive_service.check_positions_risk()

        if risk_results:
            logger.info(f"✓ 发现 {len(risk_results)} 个风险提示")
            for i, result in enumerate(risk_results, 1):
                logger.info(f"  {i}. {result['stock_name']} ({result['stock_code']})")
                logger.info(f"     - 操作建议: {result['action']}")
                logger.info(f"     - 原因: {result['reason']}")
                logger.info(f"     - 买入价: {result['entry_price']:.2f}")
                logger.info(f"     - 当前价: {result['current_price']:.2f}")
                logger.info(f"     - 盈亏: {result['profit_pct']:.2f}%")
        else:
            logger.info("✓ 无持仓或无风险提示")

        # 清理
        futu_client.disconnect()

        return True

    except Exception as e:
        logger.error(f"✗ 风险检查失败: {e}", exc_info=True)
        return False


def main():
    """主测试函数"""
    logger.info("\n" + "=" * 60)
    logger.info("激进策略完整流程测试")
    logger.info("=" * 60)

    results = []

    # 测试1: 初始化
    results.append(("初始化", test_aggressive_strategy_initialization()))

    # 测试2: 板块强势度计算
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    results.append(("板块强势度", loop.run_until_complete(test_plate_strength_calculation())))
    loop.close()

    # 测试3: 信号生成
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    results.append(("信号生成", loop.run_until_complete(test_signal_generation())))
    loop.close()

    # 测试4: 风险检查
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    results.append(("风险检查", loop.run_until_complete(test_risk_check())))
    loop.close()

    # 输出测试结果
    logger.info("\n" + "=" * 60)
    logger.info("测试结果汇总")
    logger.info("=" * 60)

    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        logger.info(f"{name}: {status}")

    # 统计
    passed = sum(1 for _, result in results if result)
    total = len(results)
    logger.info(f"\n总计: {passed}/{total} 通过")

    return passed == total


if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        logger.error(f"测试执行失败: {e}", exc_info=True)
        sys.exit(1)
