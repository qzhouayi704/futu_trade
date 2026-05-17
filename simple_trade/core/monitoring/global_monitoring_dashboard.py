#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局监控面板（Phase 6）

职责：
1. 聚合所有全局服务的运行指标
2. 提供统一的监控 API 端点
3. 触发企业微信告警
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MetricSnapshot:
    """指标快照"""
    timestamp: float = field(default_factory=time.time)
    subscription_metrics: Dict[str, Any] = field(default_factory=dict)
    api_metrics: Dict[str, Any] = field(default_factory=dict)
    connection_metrics: Dict[str, Any] = field(default_factory=dict)
    cache_metrics: Dict[str, Any] = field(default_factory=dict)
    queue_metrics: Dict[str, Any] = field(default_factory=dict)


class GlobalMonitoringDashboard:
    """全局监控面板

    聚合所有全局服务的运行指标，提供统一的监控视图。
    """

    def __init__(
        self,
        global_coordinator=None,
        global_connection_manager=None,
        unified_cache=None,
    ):
        self._coordinator = global_coordinator
        self._connection_manager = global_connection_manager
        self._cache = unified_cache

        # 告警阈值
        self._alert_thresholds = {
            'subscription_failure_rate': 0.05,   # 5%
            'api_error_rate': 0.10,              # 10%
            'memory_percent': 85.0,              # 85%
            'queue_overflow_count': 3,           # 3次
        }

        # 告警回调
        self._alert_callbacks: List = []

        # 监控任务
        self._monitor_task: Optional[asyncio.Task] = None

    def register_alert_callback(self, callback):
        """注册告警回调"""
        self._alert_callbacks.append(callback)

    async def start_monitoring(self, interval: float = 30.0):
        """启动监控"""
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(
                self._monitor_loop(interval)
            )
            logger.info("全局监控面板已启动")

    async def stop_monitoring(self):
        """停止监控"""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            logger.info("全局监控面板已停止")

    def get_snapshot(self) -> MetricSnapshot:
        """获取当前指标快照"""
        snapshot = MetricSnapshot()

        # 订阅指标
        if self._coordinator:
            try:
                sub_count = self._coordinator._get_subscription_count
                snapshot.subscription_metrics = {
                    'quote_count': sub_count('QUOTE') if callable(sub_count) else 0,
                    'ticker_count': sub_count('TICKER') if callable(sub_count) else 0,
                    'orderbook_count': sub_count('ORDER_BOOK') if callable(sub_count) else 0,
                }
            except Exception:
                pass

        return snapshot

    def get_health_report(self) -> Dict[str, Any]:
        """获取健康报告"""
        snapshot = self.get_snapshot()
        issues = []

        # 检查连接状态
        conn = snapshot.connection_metrics
        if conn and not conn.get('is_connected', True):
            issues.append(f"富途连接断开: {conn.get('state')}")

        # 检查熔断器
        api = snapshot.api_metrics
        if api and api.get('circuit_open'):
            for api_name in api['circuit_open']:
                issues.append(f"API熔断中: {api_name}")

        # 检查缓存降级
        cache = snapshot.cache_metrics
        if cache and cache.get('l1_enabled') is False:
            issues.append(f"缓存已降级，内存使用: {cache.get('memory_percent', 0):.1f}%")

        # 检查队列溢出
        queues = snapshot.queue_metrics
        if queues:
            ticker_q = queues.get('ticker_queue', {})
            if ticker_q.get('overflow_count', 0) > self._alert_thresholds['queue_overflow_count']:
                issues.append(f"Ticker队列溢出: {ticker_q['overflow_count']}次")

        return {
            'healthy': len(issues) == 0,
            'issues': issues,
            'snapshot': {
                'timestamp': snapshot.timestamp,
                'subscription': snapshot.subscription_metrics,
                'connection': snapshot.connection_metrics,
                'cache': snapshot.cache_metrics,
                'queues': snapshot.queue_metrics,
            }
        }

    async def _monitor_loop(self, interval: float):
        """监控循环"""
        while True:
            try:
                report = self.get_health_report()
                if not report['healthy']:
                    for issue in report['issues']:
                        logger.warning(f"[监控告警] {issue}")
                    await self._send_alerts(report['issues'])

                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"监控循环异常: {e}")
                await asyncio.sleep(interval)

    async def _send_alerts(self, issues: List[str]):
        """发送告警"""
        for callback in self._alert_callbacks:
            try:
                msg = "【系统告警】\n" + "\n".join(f"• {i}" for i in issues)
                if asyncio.iscoroutinefunction(callback):
                    await callback(msg)
                else:
                    callback(msg)
            except Exception as e:
                logger.error(f"发送告警失败: {e}")
