#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多层降级策略管理器（P3-3）

职责：
1. 统一管理系统多维度降级：内存、连接、API 频率
2. 提供降级状态查询 API
3. 自动恢复检测

降级等级：
- NORMAL: 所有功能正常
- WARNING: 非关键功能降频
- DEGRADED: 关闭次要推送，降低轮询频率
- CRITICAL: 仅保留核心报价和交易功能

职责边界（收尾-5）：
- DegradationManager: 全局降级等级决策（功能开关、推送频率调整）
- UnifiedDataCache: 缓存清理策略（内存压力响应、L1/L2 淘汰）

协作方式：
- DegradationManager 不直接操作缓存
- UnifiedDataCache 不决定全局降级等级
- 两者通过配置和事件解耦
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class DegradationLevel(Enum):
    NORMAL = 0
    WARNING = 1
    DEGRADED = 2
    CRITICAL = 3


class DegradationManager:
    """多层降级策略管理器"""

    def __init__(self, config=None):
        self._level = DegradationLevel.NORMAL
        self._reasons: list = []
        self._last_check = 0.0
        self._check_interval = 30.0  # 30 秒检查一次

        # 配置阈值
        self._memory_thresholds = {
            DegradationLevel.WARNING: 0.70,
            DegradationLevel.DEGRADED: 0.85,
            DegradationLevel.CRITICAL: 0.95,
        }
        self._api_fail_thresholds = {
            DegradationLevel.WARNING: 5,    # 连续失败 5 次
            DegradationLevel.DEGRADED: 15,  # 连续失败 15 次
            DegradationLevel.CRITICAL: 30,  # 连续失败 30 次
        }

        # 外部指标输入
        self._api_consecutive_failures = 0
        self._is_connected = True

        self._monitor_task: Optional[asyncio.Task] = None

    @property
    def level(self) -> DegradationLevel:
        return self._level

    @property
    def is_degraded(self) -> bool:
        return self._level.value >= DegradationLevel.DEGRADED.value

    def get_push_interval(self, base_interval: int = 5) -> int:
        """根据降级等级返回推送间隔"""
        multipliers = {
            DegradationLevel.NORMAL: 1,
            DegradationLevel.WARNING: 1,
            DegradationLevel.DEGRADED: 3,   # 15s
            DegradationLevel.CRITICAL: 6,   # 30s
        }
        return base_interval * multipliers.get(self._level, 1)

    def should_skip_feature(self, feature: str) -> bool:
        """判断某功能是否应该跳过

        Args:
            feature: 功能名称 ('strategy_detection', 'kline_update',
                      'plate_heat', 'signal_tracking', 'broadcast_conditions')
        """
        # CRITICAL: 只保留核心报价
        if self._level == DegradationLevel.CRITICAL:
            return feature not in ('quote_fetch', 'price_monitor')

        # DEGRADED: 关闭次要推送
        if self._level == DegradationLevel.DEGRADED:
            return feature in ('plate_heat', 'signal_tracking', 'broadcast_conditions')

        return False

    def report_api_failure(self):
        """报告 API 调用失败"""
        self._api_consecutive_failures += 1

    def report_api_success(self):
        """报告 API 调用成功"""
        self._api_consecutive_failures = 0

    def report_connection_state(self, connected: bool):
        """报告连接状态"""
        self._is_connected = connected

    async def start_monitoring(self):
        """启动降级监控"""
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("降级策略管理器已启动")

    async def stop_monitoring(self):
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self):
        while True:
            try:
                self._evaluate()
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"降级监控异常: {e}")
                await asyncio.sleep(self._check_interval)

    def _evaluate(self):
        """评估当前降级等级"""
        import psutil
        new_level = DegradationLevel.NORMAL
        reasons = []

        # 1. 内存维度
        mem_pct = psutil.virtual_memory().percent / 100.0
        for level, threshold in sorted(
            self._memory_thresholds.items(), key=lambda x: x[0].value, reverse=True
        ):
            if mem_pct >= threshold:
                if level.value > new_level.value:
                    new_level = level
                reasons.append(f"内存{mem_pct*100:.0f}%")
                break

        # 2. 连接维度
        if not self._is_connected:
            if DegradationLevel.DEGRADED.value > new_level.value:
                new_level = DegradationLevel.DEGRADED
            reasons.append("连接断开")

        # 3. API 失败维度
        for level, threshold in sorted(
            self._api_fail_thresholds.items(), key=lambda x: x[0].value, reverse=True
        ):
            if self._api_consecutive_failures >= threshold:
                if level.value > new_level.value:
                    new_level = level
                reasons.append(f"API连续失败{self._api_consecutive_failures}次")
                break

        # 状态变化通知
        if new_level != self._level:
            old = self._level
            self._level = new_level
            self._reasons = reasons
            if new_level.value > old.value:
                logger.warning(f"系统降级: {old.name} → {new_level.name} | {', '.join(reasons)}")
            else:
                logger.info(f"系统恢复: {old.name} → {new_level.name}")

    def get_status(self) -> Dict[str, Any]:
        """获取降级状态"""
        return {
            'level': self._level.name,
            'level_value': self._level.value,
            'is_degraded': self.is_degraded,
            'reasons': self._reasons,
            'api_consecutive_failures': self._api_consecutive_failures,
            'is_connected': self._is_connected,
            'push_interval': self.get_push_interval(),
            'timestamp': time.time(),
        }
