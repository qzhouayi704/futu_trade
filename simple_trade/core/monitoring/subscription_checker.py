#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订阅一致性巡检器（P1-2）

职责：
1. 每 5 分钟从 OpenD 拉取实际订阅列表
2. 与 SubscriptionManager 内存状态对比
3. 不一致即日志 + 告警
"""

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class SubscriptionChecker:
    """订阅一致性巡检器"""

    def __init__(self, futu_client, subscription_manager):
        self._futu_client = futu_client
        self._subscription_manager = subscription_manager
        self._check_task: Optional[asyncio.Task] = None
        self._check_interval = 300  # 5 分钟
        self._drift_count = 0

    async def start(self):
        """启动巡检"""
        if self._check_task is None or self._check_task.done():
            self._check_task = asyncio.create_task(self._check_loop())
            logger.info("订阅一致性巡检已启动（间隔5分钟）")

    async def stop(self):
        """停止巡检"""
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass

    async def _check_loop(self):
        """巡检循环"""
        while True:
            try:
                await asyncio.sleep(self._check_interval)
                await self._check_consistency()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"订阅巡检异常: {e}")
                await asyncio.sleep(60)

    async def _check_consistency(self):
        """执行一致性检查"""
        if not self._futu_client.is_available():
            logger.debug("富途API不可用，跳过订阅巡检")
            return

        try:
            loop = asyncio.get_running_loop()
            # query_subscription 是同步方法
            ret, data = await loop.run_in_executor(
                None,
                lambda: self._futu_client.client.query_subscription()
            )

            from futu import RET_OK
            if ret != RET_OK:
                logger.warning(f"查询订阅列表失败: {data}")
                return

            # data 是 DataFrame，提取实际订阅的股票代码
            if data is not None and hasattr(data, 'to_dict'):
                # 从 query_subscription 结果中提取代码列表
                actual_codes = set()
                if 'code' in data.columns:
                    actual_codes = set(data['code'].tolist())
                elif len(data.columns) > 0:
                    # 尝试其他列名
                    actual_codes = set()

                memory_codes = self._subscription_manager.subscribed_stocks

                # 比较
                only_in_memory = memory_codes - actual_codes
                only_in_opend = actual_codes - memory_codes

                if only_in_memory or only_in_opend:
                    self._drift_count += 1
                    logger.warning(
                        f"[订阅漂移#{self._drift_count}] "
                        f"内存多 {len(only_in_memory)} 只: {list(only_in_memory)[:5]}..., "
                        f"OpenD多 {len(only_in_opend)} 只: {list(only_in_opend)[:5]}..."
                    )
                else:
                    logger.debug(
                        f"订阅一致性检查通过: {len(memory_codes)} 只股票"
                    )
            else:
                logger.debug("query_subscription 返回空数据")

        except Exception as e:
            logger.error(f"订阅一致性检查异常: {e}")

    @property
    def drift_count(self) -> int:
        """累计漂移次数"""
        return self._drift_count
