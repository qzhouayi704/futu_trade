#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统协调器 - 监控状态管理

职责：
1. 启动/停止监控（通过 StateManager 设置状态标志）
2. 初始化订阅（委托给 SubscriptionManager）
3. 同步持仓股票

注意：报价获取和监控周期由 AsyncQuotePusher 统一驱动，
本协调器仅通过 state_manager.set_running() 控制监控开关。
"""

import logging
import asyncio

from ..state.state_manager import StateManager
from ...utils.logger import print_status


class SystemCoordinator:
    """系统协调器 - 仅管理监控状态，不驱动 Pipeline"""

    def __init__(self, container, state_manager: StateManager):
        """初始化系统协调器

        Args:
            container: 服务容器
            state_manager: 状态管理器
        """
        self.container = container
        self.state_manager = state_manager

    async def start(self):
        """启动监控 - 设置状态标志 + 初始化订阅 + 同步持仓"""
        print_status("【系统协调器】启动系统", "info")

        if self.state_manager.is_running():
            logging.warning("系统已在运行中")
            print_status("【系统协调器】系统已在运行中，跳过启动", "warn")
            return

        # 1. 检查富途API状态
        futu_available = await asyncio.get_event_loop().run_in_executor(
            None, self.container.futu_client.is_available
        )
        print_status(f"【系统协调器】富途API状态: {'可用' if futu_available else '不可用'}", "info")

        # 2. 同步持仓股票
        print_status("【系统协调器】同步持仓股票...", "info")
        await self._sync_positions()

        # 3. 初始化订阅
        await self._initialize_subscription(futu_available)

        # 4. 设置运行状态（AsyncQuotePusher 会检测此标志来执行监控周期）
        self.state_manager.set_running(True)

        print_status("【系统协调器】系统启动完成", "ok")

    async def stop(self):
        """停止监控 - 仅清除状态标志"""
        print_status("【系统协调器】停止系统", "info")
        self.state_manager.set_running(False)
        print_status("【系统协调器】系统已停止", "ok")

    async def _initialize_subscription(self, futu_available: bool):
        """初始化订阅 - 委托给 subscription_helper"""
        subscribed_count = self.container.subscription_manager.subscribed_count

        if subscribed_count == 0 and futu_available:
            print_status("【系统协调器】初始化订阅...", "info")

            from ...utils.market_helper import MarketTimeHelper
            current_markets = MarketTimeHelper.get_current_active_markets()
            if not current_markets:
                current_markets = [MarketTimeHelper.get_primary_market()]

            subscription_result = await asyncio.get_event_loop().run_in_executor(
                None, self.container.subscription_helper.subscribe_target_stocks, current_markets
            )

            if subscription_result['success']:
                print_status(
                    f"【系统协调器】订阅完成: {subscription_result.get('subscribed_count', 0)} 只股票",
                    "ok"
                )
            else:
                print_status(
                    f"【系统协调器】订阅失败: {subscription_result.get('message', '')}",
                    "warn"
                )
        else:
            print_status(
                f"【系统协调器】已有 {subscribed_count} 只股票订阅",
                "info"
            )

    async def _sync_positions(self):
        """同步持仓股票 - 委托给服务层"""
        try:
            positions_result = await asyncio.get_event_loop().run_in_executor(
                None, self.container.futu_trade_service.get_positions
            )

            if positions_result['success']:
                positions = positions_result['positions']
                if positions:
                    position_codes = [p['stock_code'] for p in positions if p.get('qty', 0) > 0]
                    if position_codes:
                        logging.info(f"持仓优先订阅: {len(position_codes)} 只股票")
                        self.container.subscription_helper.set_priority_stocks(position_codes)
        except Exception as e:
            logging.error(f"同步持仓异常: {e}")
