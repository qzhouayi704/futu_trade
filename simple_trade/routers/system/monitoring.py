#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一监控路由 /api/monitoring/*

收口三处分散的监控前缀到一个规范命名空间：
- 控制：start / stop / control / health      （原 /api/monitor/*，monitor.py）
- 全局指标：global/health, global/metrics, subscription/stats,
            cache/stats, queue/stats, connection/status
                                              （原 /api/global-monitoring/*，global_monitoring.py）
- 统计：stocks/monitor-stats, link-health     （原散落，monitoring_routes.py）

本路由复用三个旧路由的处理函数（不复制业务逻辑）。旧前缀仍由各自 router 注册、保持可用，
作为迁移窗口的向后兼容；待前端迁到 /api/monitoring/* 后再退役旧前缀。

迁移顺序（必须后端先行，避免前端对不上生产后端）：
1) 本次：后端新增 /api/monitoring/*，旧前缀 /api/monitor/*、/api/global-monitoring/*、
   /stocks/monitor-stats 全部保留可用；
2) 部署后端 → 前端 lib/api/system.ts、app/api/monitor 代理迁到 /api/monitoring/*；
3) 一个迁移周期后删除旧前缀路由（monitor.py / global_monitoring.py 旧装饰器、
   monitoring_routes.py 的 /stocks/monitor-stats）。
"""

import logging

from fastapi import APIRouter

from .monitor import (
    start_monitoring,
    stop_monitoring,
    health_check,
    control_system,
)
from .global_monitoring import (
    get_health_report,
    get_metrics,
    get_subscription_stats,
    get_cache_stats,
    get_queue_stats,
    get_connection_status,
)
from .monitoring_routes import get_monitor_stats, get_link_health

router = APIRouter(prefix="/api/monitoring", tags=["监控(统一)"])

# ---- 控制（原 /api/monitor/*）----
router.add_api_route("/start", start_monitoring, methods=["POST"])
router.add_api_route("/stop", stop_monitoring, methods=["POST"])
router.add_api_route("/control", control_system, methods=["POST"])
router.add_api_route("/health", health_check, methods=["GET"])

# ---- 全局指标（原 /api/global-monitoring/*）----
router.add_api_route("/global/health", get_health_report, methods=["GET"])
router.add_api_route("/global/metrics", get_metrics, methods=["GET"])
router.add_api_route("/subscription/stats", get_subscription_stats, methods=["GET"])
router.add_api_route("/cache/stats", get_cache_stats, methods=["GET"])
router.add_api_route("/queue/stats", get_queue_stats, methods=["GET"])
router.add_api_route("/connection/status", get_connection_status, methods=["GET"])

# ---- 统计（原 monitoring_routes.py）----
router.add_api_route("/stocks/monitor-stats", get_monitor_stats, methods=["GET"])
router.add_api_route("/link-health", get_link_health, methods=["GET"])

logging.info("统一监控路由 /api/monitoring/* 已注册（旧前缀保留转发）")
