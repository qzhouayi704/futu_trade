#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局监控 API 端点

提供全局服务的运行指标和健康报告。
"""

from fastapi import APIRouter, Depends
from typing import Dict, Any

from ...dependencies import get_container

router = APIRouter(prefix="/api/global-monitoring", tags=["全局监控"])


@router.get("/health")
async def get_health_report(container=Depends(get_container)) -> Dict[str, Any]:
    """获取全局健康报告

    Returns:
        {
            "healthy": bool,
            "issues": List[str],
            "snapshot": {
                "timestamp": float,
                "subscription": {...},
                "connection": {...},
                "cache": {...},
                "queues": {...}
            }
        }
    """
    if not hasattr(container, 'global_monitoring_dashboard') or not container.global_monitoring_dashboard:
        return {
            "healthy": False,
            "issues": ["全局监控面板未初始化"],
            "snapshot": {}
        }

    return container.global_monitoring_dashboard.get_health_report()


@router.get("/metrics")
async def get_metrics(container=Depends(get_container)) -> Dict[str, Any]:
    """获取所有全局服务的指标快照

    Returns:
        {
            "timestamp": float,
            "subscription_metrics": {...},
            "api_metrics": {...},
            "connection_metrics": {...},
            "cache_metrics": {...},
            "queue_metrics": {...}
        }
    """
    if not hasattr(container, 'global_monitoring_dashboard') or not container.global_monitoring_dashboard:
        return {"error": "全局监控面板未初始化"}

    snapshot = container.global_monitoring_dashboard.get_snapshot()
    return {
        "timestamp": snapshot.timestamp,
        "subscription_metrics": snapshot.subscription_metrics,
        "api_metrics": snapshot.api_metrics,
        "connection_metrics": snapshot.connection_metrics,
        "cache_metrics": snapshot.cache_metrics,
        "queue_metrics": snapshot.queue_metrics,
    }


@router.get("/subscription/stats")
async def get_subscription_stats(container=Depends(get_container)) -> Dict[str, Any]:
    """获取订阅统计

    Returns:
        {
            "quote_count": int,
            "ticker_count": int,
            "orderbook_count": int
        }
    """
    if not hasattr(container, 'global_subscription_coordinator') or not container.global_subscription_coordinator:
        return {"error": "订阅恢复助手未初始化"}

    coordinator = container.global_subscription_coordinator
    sub_mgr = container.subscription_manager

    return {
        "quote_count": coordinator.get_subscription_count(),
        "ticker_count": len(getattr(sub_mgr, '_ticker_subscribed', set())),
        "orderbook_count": len(getattr(sub_mgr, '_orderbook_subscribed', set())),
    }


@router.get("/cache/stats")
async def get_cache_stats(container=Depends(get_container)) -> Dict[str, Any]:
    """获取缓存统计

    Returns:
        {
            "l1_hits": int,
            "l1_misses": int,
            "l1_size": int,
            "l1_enabled": bool,
            "memory_percent": float,
            "degraded_count": int,
            "recovered_count": int
        }
    """
    if not hasattr(container, 'unified_cache') or not container.unified_cache:
        return {"error": "统一缓存未初始化"}

    return container.unified_cache.get_stats()


@router.get("/queue/stats")
async def get_queue_stats(container=Depends(get_container)) -> Dict[str, Any]:
    """获取队列统计

    Returns:
        {
            "write_queue": {...},
            "ticker_queue": {...}
        }
    """
    result = {}
    return result


@router.get("/connection/status")
async def get_connection_status(container=Depends(get_container)) -> Dict[str, Any]:
    """获取连接状态

    Returns:
        {
            "state": str,
            "is_connected": bool
        }
    """
    if not hasattr(container, 'global_connection_manager') or not container.global_connection_manager:
        return {"error": "全局连接管理器未初始化"}

    manager = container.global_connection_manager
    return {
        "state": manager.state.value,
        "is_connected": manager.is_connected,
    }
