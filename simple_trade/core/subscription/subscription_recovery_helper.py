#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订阅恢复助手（P5-2 重构自 GlobalSubscriptionCoordinator）

职责（精简后仅保留重连恢复相关功能）：
1. force_clear_all() — 重连时清除所有订阅状态
2. restore_all_subscriptions() — 重连后恢复订阅
3. get_subscription_count() — 监控端点查询当前订阅数
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SubscriptionRecoveryHelper:
    """订阅恢复助手

    从 GlobalSubscriptionCoordinator 精简而来，
    仅保留 GlobalConnectionManager 和监控端点所需的功能。
    """

    def __init__(self, futu_client, subscription_manager):
        self._futu_client = futu_client
        self._subscription_manager = subscription_manager
        self._lock = asyncio.Lock()

    async def force_clear_all(self):
        """强制清除所有订阅状态（重连后使用）

        直接委托给 SubscriptionManager。
        """
        async with self._lock:
            if hasattr(self._subscription_manager, 'force_clear_subscriptions'):
                self._subscription_manager.force_clear_subscriptions()
            else:
                # fallback: 手动清除内存状态
                self._subscription_manager._subscribed_stocks.clear()
                self._subscription_manager._quote_subscribed.clear()
                if hasattr(self._subscription_manager, '_ticker_subscribed'):
                    self._subscription_manager._ticker_subscribed.clear()
                if hasattr(self._subscription_manager, '_orderbook_subscribed'):
                    self._subscription_manager._orderbook_subscribed.clear()
            logger.info("已清除所有订阅状态")

    async def restore_all_subscriptions(self):
        """恢复所有订阅（重连后使用）

        优先使用 SubscriptionManager 的分级恢复方法。
        """
        async with self._lock:
            if hasattr(self._subscription_manager, 'restore_subscriptions_by_priority'):
                # P2-2: 使用分级恢复
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    self._subscription_manager.restore_subscriptions_by_priority
                )
                logger.info(
                    f"分级恢复完成: 成功{result.get('success', 0)}/"
                    f"总计{result.get('total', 0)}"
                )
            else:
                logger.warning("SubscriptionManager 无分级恢复方法，跳过恢复")

    def get_subscription_count(self) -> int:
        """获取当前订阅数量（供监控端点使用）"""
        return len(self._subscription_manager.subscribed_stocks)
