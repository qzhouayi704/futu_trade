"""FastAPI 依赖注入 — 纯薄封装，所有服务统一从 ServiceContainer 获取

重构说明（A1）：
- 删除 _AppState dataclass 和 6 个 set_xxx() 函数
- 唯一入口：set_container() 注册 ServiceContainer
- 所有 get_xxx() 函数从 container 获取，不持有独立状态
"""

from typing import Optional

from fastapi import Query

from .core import ServiceContainer
from .core.exceptions import BusinessError


# 唯一的全局引用
_container: Optional[ServiceContainer] = None


def set_container(container: ServiceContainer) -> None:
    """设置服务容器（由 app.py lifespan 调用，唯一的 setter）"""
    global _container
    _container = container


def reset() -> None:
    """重置服务容器引用（用于测试和优雅重启）"""
    global _container
    _container = None


# ========== 服务获取函数（薄封装） ==========

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
    container = get_container()
    if container.state_manager is None:
        raise BusinessError("状态管理器未初始化")
    return container.state_manager


def get_system_coordinator():
    """获取系统协调器"""
    container = get_container()
    if container.system_coordinator is None:
        raise BusinessError("系统协调器未初始化")
    return container.system_coordinator


def get_socket_manager():
    """获取 Socket 管理器"""
    from .websocket import get_socket_manager as _get_socket_manager
    return _get_socket_manager()


def get_quote_pusher():
    """获取行情推送服务"""
    container = get_container()
    if container.quote_pusher is None:
        raise BusinessError("行情推送服务未初始化")
    return container.quote_pusher


def get_quote_pipeline():
    """获取行情处理管道"""
    container = get_container()
    if container.quote_pipeline is None:
        raise BusinessError("行情处理管道未初始化")
    return container.quote_pipeline


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
