#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统数据初始化模块

负责应用启动时的系统数据初始化，包括：
1. 数据库索引优化
2. 股票池初始化
3. 缓存预热
4. K线数据清理

拆分自 app.py
"""

import asyncio
import logging

from ..core.container.service_container import ServiceContainer
from ..utils.logger import print_status, get_flow_logger


async def _sync_positions_on_startup(container: ServiceContainer):
    """启动时同步持仓股票到股票池

    此函数会尝试连接交易API并同步持仓股票到"持仓监控"板块。
    失败时不会影响系统启动，仅记录警告日志。
    """
    try:
        trade_service = container.futu_trade_service
        if not trade_service:
            logging.info("【持仓同步】交易服务未初始化，跳过持仓同步")
            return

        # 尝试连接交易API
        if not trade_service.is_trade_ready():
            logging.info("【持仓同步】尝试连接交易API...")
            connect_result = await asyncio.to_thread(trade_service.connect_trade_api)
            if not connect_result['success']:
                logging.warning(f"【持仓同步】交易API连接失败: {connect_result['message']}")
                return

        # 获取持仓（内部会自动调用 sync_positions_to_stock_pool）
        result = await asyncio.to_thread(trade_service.get_positions)
        if result['success']:
            positions = result['positions']
            position_count = len(positions)
            logging.info(f"【持仓同步】成功同步 {position_count} 只持仓股票")
            print_status(f"持仓同步: {position_count} 只股票", "ok")

            # 设置持仓股票为优先订阅（确保后续订阅时始终包含持仓股票）
            if positions and container.subscription_helper:
                position_codes = [
                    p['stock_code'] for p in positions if p.get('qty', 0) > 0
                ]
                if position_codes:
                    container.subscription_helper.set_priority_stocks(position_codes)
                    logging.info(f"【持仓同步】已设置 {len(position_codes)} 只持仓股票为优先订阅")
        else:
            logging.warning(f"【持仓同步】获取持仓失败: {result['message']}")
    except Exception as e:
        logging.error(f"【持仓同步】异常: {e}", exc_info=True)


async def initialize_system_data(container: ServiceContainer, state_manager) -> bool:
    """系统数据初始化 - 与 Flask 模式保持一致

    Returns:
        bool: 初始化是否成功（关键组件初始化成功返回 True）
    """
    success = True
    flow = get_flow_logger("系统初始化")

    # 1. 优化数据库索引（非关键）
    try:
        await asyncio.to_thread(container.db_manager.create_indexes)
        await asyncio.to_thread(container.db_manager.system_queries.analyze_tables)
        flow.step("数据库索引优化")
    except Exception as e:
        flow.warn("数据库索引优化失败", error=str(e))

    # 2. 初始化股票池数据（关键）- 使用异步线程
    try:
        pool_result = await asyncio.to_thread(
            container.stock_pool_service.init_stock_pool,
            force_refresh=False
        )
        if pool_result['success']:
            flow.step("股票池初始化",
                      plates=pool_result['plates_count'],
                      stocks=pool_result['stocks_count'])

            # 3. 预热缓存
            stock_pool_data = state_manager.get_stock_pool()
            if not stock_pool_data['initialized']:
                flow.warn("缓存预热失败")
        else:
            flow.error("股票池初始化失败", reason=pool_result['message'])
            success = False
    except Exception as e:
        flow.error("股票池初始化异常", err=e)
        success = False

    # 4. 清理当天不完整K线数据（非关键）- 使用异步线程
    if container.futu_client.is_available():
        try:
            await asyncio.to_thread(
                container.kline_service.clean_today_incomplete_kline
            )
            flow.step("K线数据清理")
        except Exception as e:
            flow.warn("K线数据清理异常", error=str(e))

    # 5. 同步持仓股票到股票池（非关键）
    await _sync_positions_on_startup(container)
    flow.step("持仓同步")

    # 6. 如果系统未运行，清空所有订阅（关键）
    if not state_manager.is_running():
        if container.subscription_helper:
            try:
                container.subscription_helper.unsubscribe_all()
                flow.step("清空订阅")
            except Exception as e:
                # 快速重启时富途 API 可能拒绝（1分钟最短订阅限制），不影响后续订阅
                logging.debug(f"清空旧订阅跳过（可能快速重启）: {e}")

    flow.end(success=success)
    return success
