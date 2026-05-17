#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局连接管理器

职责：
1. 监听富途连接状态
2. 连接断开时触发全局重连流程
3. 重连成功后自动恢复所有订阅
4. 通知所有依赖服务
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Callable, List

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """连接状态"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


class GlobalConnectionManager:
    """全局连接管理器

    统一管理富途连接状态，自动重连和恢复订阅。
    """

    def __init__(self, futu_client, global_coordinator):
        self._futu_client = futu_client
        self._global_coordinator = global_coordinator

        self._connection_state = ConnectionState.DISCONNECTED
        self._reconnect_callbacks: List[Callable] = []
        self._reconnect_lock = asyncio.Lock()
        self._reconnect_cooldown = 10.0  # 10秒冷却
        self._last_reconnect_time = 0.0

        self._monitor_task: asyncio.Task = None

    async def start_monitoring(self):
        """启动连接监控"""
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._connection_monitor_loop())
            logger.info("连接监控已启动")

    async def stop_monitoring(self):
        """停止连接监控"""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            logger.info("连接监控已停止")

    async def _connection_monitor_loop(self):
        """后台任务：监控连接状态"""
        while True:
            try:
                if not self._futu_client.is_connected:
                    if self._connection_state != ConnectionState.DISCONNECTED:
                        logger.warning("检测到富途连接断开")
                        self._connection_state = ConnectionState.DISCONNECTED
                        await self._handle_disconnection()
                else:
                    if self._connection_state == ConnectionState.DISCONNECTED:
                        self._connection_state = ConnectionState.CONNECTED
                        logger.info("富途连接已恢复")

                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"连接监控异常: {e}")
                await asyncio.sleep(5.0)

    async def _handle_disconnection(self):
        """处理连接断开"""
        async with self._reconnect_lock:
            now = time.monotonic()
            if now - self._last_reconnect_time < self._reconnect_cooldown:
                logger.debug("重连冷却中，跳过")
                return

            self._last_reconnect_time = now
            self._connection_state = ConnectionState.RECONNECTING

            # P1-1: 重连埋点
            import json, os
            from ...utils.logger import create_dedicated_logger
            if not hasattr(self, '_reconnect_logger'):
                log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'logs')
                self._reconnect_logger = create_dedicated_logger(
                    'reconnect_trace', os.path.join(log_dir, 'reconnect.log')
                )

            t_start = time.monotonic()

            # 1. 清除所有订阅状态
            logger.info("清除所有订阅状态...")
            await self._global_coordinator.force_clear_all()

            # 2. 重连富途API
            logger.info("尝试重连富途API...")
            t_reconnect = time.monotonic()
            success = await self._reconnect_futu()
            reconnect_ms = (time.monotonic() - t_reconnect) * 1000

            if not success:
                logger.error("重连失败")
                self._connection_state = ConnectionState.DISCONNECTED
                self._reconnect_logger.info(json.dumps({
                    "flow": "reconnect", "success": False,
                    "reconnect_ms": round(reconnect_ms, 1),
                }, ensure_ascii=False))
                return

            # 3. 恢复所有订阅
            logger.info("恢复所有订阅...")
            t_restore = time.monotonic()
            await self._global_coordinator.restore_all_subscriptions()
            restore_ms = (time.monotonic() - t_restore) * 1000

            # 4. 通知所有服务
            logger.info("通知所有服务重连成功...")
            for callback in self._reconnect_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback()
                    else:
                        callback()
                except Exception as e:
                    logger.error(f"重连回调执行异常: {e}")

            self._connection_state = ConnectionState.CONNECTED
            total_ms = (time.monotonic() - t_start) * 1000
            logger.info("重连流程完成")

            # P1-1: 记录完整重连链路
            self._reconnect_logger.info(json.dumps({
                "flow": "reconnect", "success": True,
                "reconnect_ms": round(reconnect_ms, 1),
                "restore_ms": round(restore_ms, 1),
                "total_ms": round(total_ms, 1),
            }, ensure_ascii=False))

    async def _reconnect_futu(self) -> bool:
        """重连富途API（指数退避：2s → 4s → 8s → 上限 60s）"""
        loop = asyncio.get_running_loop()
        max_attempts = 10
        base_delay = 2.0
        max_delay = 60.0

        for attempt in range(1, max_attempts + 1):
            try:
                success = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self._futu_client._reconnect_opend
                    ),
                    timeout=30.0
                )
                if success:
                    logger.info(f"重连成功（第{attempt}次尝试）")
                    return True
            except asyncio.TimeoutError:
                logger.warning(f"重连超时（第{attempt}次，30s）")
            except Exception as e:
                logger.error(f"重连异常（第{attempt}次）: {e}")

            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            logger.info(f"等待 {delay:.0f}s 后重试重连...")
            await asyncio.sleep(delay)

        logger.error(f"重连失败：已尝试 {max_attempts} 次")
        return False

    def register_reconnect_callback(self, callback: Callable):
        """注册重连回调"""
        self._reconnect_callbacks.append(callback)
        logger.debug(f"已注册重连回调: {callback.__name__ if hasattr(callback, '__name__') else callback}")

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connection_state == ConnectionState.CONNECTED

    @property
    def state(self) -> ConnectionState:
        """当前连接状态"""
        return self._connection_state
