#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
链路健康监控器（P1-2）

职责：
1. 每 10s 计算 P50/P95/P99 延迟、成功率、重连频率
2. 暴露 HTTP 端点 /api/monitoring/link-health
"""

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class LinkHealthMonitor:
    """链路健康监控器

    从 futu_api.log 和 quote_cycle.log 采集指标，
    计算 P50/P95/P99 延迟和成功率。
    """

    def __init__(self):
        # 滑动窗口（最近 300 条，约 10 分钟 @5s 间隔）
        self._api_latencies: deque = deque(maxlen=300)
        self._quote_latencies: deque = deque(maxlen=300)
        self._api_successes: deque = deque(maxlen=300)
        self._reconnect_count = 0
        self._last_reconnect_time: Optional[float] = None

        self._monitor_task: Optional[asyncio.Task] = None
        self._log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            'logs'
        )

    async def start_monitoring(self):
        """启动监控"""
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("链路健康监控已启动")

    async def stop_monitoring(self):
        """停止监控"""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self):
        """每 10s 采集一次指标"""
        while True:
            try:
                await self._collect_metrics()
                await asyncio.sleep(10.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"链路健康采集异常: {e}")
                await asyncio.sleep(10.0)

    async def _collect_metrics(self):
        """从日志文件尾部采集最新指标"""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._read_recent_logs)

    def _read_recent_logs(self):
        """同步读取日志文件尾部"""
        # 读取 futu_api.log 最后 50 行
        api_log = os.path.join(self._log_dir, 'futu_api.log')
        if os.path.exists(api_log):
            try:
                lines = self._tail(api_log, 50)
                for line in lines:
                    try:
                        # 格式: timestamp - json
                        json_part = line.split(' - ', 1)[-1].strip()
                        data = json.loads(json_part)
                        if data.get('flow') == 'futu_api':
                            self._api_latencies.append(data.get('duration_ms', 0))
                            self._api_successes.append(1 if data.get('success') else 0)
                    except (json.JSONDecodeError, IndexError):
                        pass
            except Exception:
                pass

        # 读取 quote_cycle.log 最后 20 行
        cycle_log = os.path.join(self._log_dir, 'quote_cycle.log')
        if os.path.exists(cycle_log):
            try:
                lines = self._tail(cycle_log, 20)
                for line in lines:
                    try:
                        json_part = line.split(' - ', 1)[-1].strip()
                        data = json.loads(json_part)
                        if data.get('flow') == 'quote_cycle':
                            self._quote_latencies.append(data.get('fetch_ms', 0))
                    except (json.JSONDecodeError, IndexError):
                        pass
            except Exception:
                pass

        # 读取 reconnect.log 计数
        reconnect_log = os.path.join(self._log_dir, 'reconnect.log')
        if os.path.exists(reconnect_log):
            try:
                lines = self._tail(reconnect_log, 10)
                count = sum(1 for l in lines if '"reconnect"' in l)
                self._reconnect_count = count
            except Exception:
                pass

    @staticmethod
    def _tail(filepath: str, n: int) -> list:
        """读取文件最后 n 行"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.readlines()[-n:]
        except Exception:
            return []

    @staticmethod
    def _percentile(data, pct: float) -> float:
        """计算百分位数"""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        idx = int(len(sorted_data) * pct / 100.0)
        idx = min(idx, len(sorted_data) - 1)
        return sorted_data[idx]

    def get_health(self) -> Dict[str, Any]:
        """获取当前健康指标"""
        api_lats = list(self._api_latencies)
        quote_lats = list(self._quote_latencies)
        api_succs = list(self._api_successes)

        success_rate = (sum(api_succs) / len(api_succs) * 100) if api_succs else 100.0

        return {
            "api_latency": {
                "p50_ms": round(self._percentile(api_lats, 50), 1),
                "p95_ms": round(self._percentile(api_lats, 95), 1),
                "p99_ms": round(self._percentile(api_lats, 99), 1),
                "sample_count": len(api_lats),
            },
            "quote_cycle_latency": {
                "p50_ms": round(self._percentile(quote_lats, 50), 1),
                "p95_ms": round(self._percentile(quote_lats, 95), 1),
                "p99_ms": round(self._percentile(quote_lats, 99), 1),
                "sample_count": len(quote_lats),
            },
            "success_rate_pct": round(success_rate, 2),
            "reconnect_count_recent": self._reconnect_count,
            "timestamp": time.time(),
        }
