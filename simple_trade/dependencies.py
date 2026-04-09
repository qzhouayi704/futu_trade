#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 依赖注入

提供路由处理函数所需的公共依赖
"""

from typing import Optional

from fastapi import Query

from .core import ServiceContainer
from .core.exceptions import BusinessError


# 全局服务容器引用（由 app.py 的 lifespan 初始化）
_container: Optional[ServiceContainer] = None
_state_manager = None
_system_coordinator = None
_quote_pipeline = None
_socket_manager = None
_quote_pusher = None


def set_container(container: ServiceContainer) -> None:
    """设置服务容器（由 app.py 调用）"""
    global _container
    _container = container


def set_state_manager(state) -> None:
    """设置状态管理器"""
    global _state_manager
    _state_manager = state


def set_system_coordinator(coordinator) -> None:
    """设置系统协调器"""
    global _system_coordinator
    _system_coordinator = coordinator


def set_quote_pipeline(pipeline) -> None:
    """设置行情处理管道"""
    global _quote_pipeline
    _quote_pipeline = pipeline


def set_socket_manager(manager) -> None:
    """设置 Socket 管理器"""
    global _socket_manager
    _socket_manager = manager


def set_quote_pusher(pusher) -> None:
    """设置行情推送服务"""
    global _quote_pusher
    _quote_pusher = pusher


def get_container() -> ServiceContainer:
    """获取服务容器"""
    if _container is None:
        raise BusinessError("服务容器未初始化")
    return _container


def get_db_manager():
    """获取数据库管理器"""
    return get_container().db_manager


def get_futu_client():
    """获取富途客户端"""
    return get_container().futu_client


def get_stock_pool_service():
    """获取股票池服务"""
    return get_container().stock_pool_service


def get_kline_service():
    """获取K线服务"""
    return get_container().kline_service


def get_realtime_service():
    """获取实时数据服务"""
    return get_container().realtime_service


def get_quote_service():
    """获取报价服务"""
    return get_container().quote_service


def get_trade_service():
    """获取交易服务"""
    return get_container().trade_service


def get_alert_service():
    """获取预警服务"""
    return get_container().alert_service


def get_plate_manager():
    """获取板块管理器"""
    return get_container().plate_manager


def get_hot_stock_service():
    """获取热门股票服务"""
    return get_container().hot_stock_service


def get_strategy_monitor_service():
    """获取策略监控服务"""
    return get_container().strategy_monitor_service


def get_state():
    """获取状态管理器"""
    if _state_manager is None:
        raise BusinessError("状态管理器未初始化")
    return _state_manager


def get_system_coordinator():
    """获取系统协调器"""
    if _system_coordinator is None:
        raise BusinessError("系统协调器未初始化")
    return _system_coordinator


def get_socket_manager():
    """获取 Socket 管理器"""
    if _socket_manager is None:
        raise BusinessError("Socket管理器未初始化")
    return _socket_manager


def get_quote_pusher():
    """获取行情推送服务"""
    if _quote_pusher is None:
        raise BusinessError("行情推送服务未初始化")
    return _quote_pusher


def get_quote_pipeline():
    """获取行情处理管道"""
    if _quote_pipeline is None:
        raise BusinessError("行情处理管道未初始化")
    return _quote_pipeline


# ========== 常用查询参数 ==========

def pagination_params(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=200, description="每页数量")
) -> dict:
    """分页参数"""
    return {"page": page, "page_size": page_size}


def stock_code_param(
    stock_code: str = Query(..., min_length=1, description="股票代码")
) -> str:
    """股票代码参数"""
    return stock_code


def limit_param(
    limit: int = Query(default=50, ge=1, le=500, description="返回数量限制")
) -> int:
    """数量限制参数"""
    return limit
