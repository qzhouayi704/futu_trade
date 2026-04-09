#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
监控控制路由 - FastAPI Router

迁移自 routes/system_routes.py 的 monitor 蓝图
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends

from ...core import get_state_manager
from ...core.exceptions import BusinessError
from ...dependencies import get_container, get_system_coordinator
from ...schemas.common import APIResponse
from ...schemas.system import (
    MonitorControlRequest,
    MonitorStartResponse,
    HealthCheckData,
    MonitorHealth,
    StockPoolHealth,
    SubscriptionHealth,
    ConfigInfo,
)


router = APIRouter(prefix="/api/monitor", tags=["监控控制"])


@router.post("/start", response_model=APIResponse[MonitorStartResponse])
async def start_monitoring(
    container=Depends(get_container),
    system_coordinator=Depends(get_system_coordinator)
):
    """启动监控"""
    from ...utils.logger import print_status

    state = get_state_manager()

    logging.info("【调试】收到启动监控请求 /api/monitor/start")
    print_status("【调试】收到启动监控请求", "info")

    # 检查当前运行状态
    current_status = state.is_running()
    logging.info(f"【调试】当前运行状态: {current_status}")

    if current_status:
        print_status("【调试】监控已在运行中", "warn")
        return APIResponse.ok(
            data=MonitorStartResponse(
                futu_available=container.futu_client.is_available(),
                stock_count=len(state.get_stock_pool().get('stocks', [])),
                subscribed_count=container.subscription_manager.subscribed_count,
                already_running=True
            ),
            message="监控已在运行中"
        )

    # 检查富途API连接状态
    futu_available = container.futu_client.is_available()
    print_status(f"【调试】富途API连接状态: {'可用' if futu_available else '不可用'}", "info")
    logging.info(f"【调试】富途API连接状态: {futu_available}")

    if not futu_available:
        print_status("【警告】富途API不可用，监控功能将受限", "warn")

    # 检查股票池状态
    stock_pool = state.get_stock_pool()
    stock_count = len(stock_pool.get('stocks', []))
    print_status(f"【调试】股票池股票数量: {stock_count}", "info")
    logging.info(f"【调试】股票池股票数量: {stock_count}")

    if stock_count == 0:
        print_status("【警告】股票池为空，请先初始化股票池", "warn")
        raise BusinessError(
            message="股票池为空，请先初始化股票池",
            details={
                'futu_available': futu_available,
                'stock_count': stock_count
            }
        )

    # 启动监控（使用 SystemCoordinator）
    try:
        print_status("【调试】开始启动监控...", "info")

        # 使用系统协调器启动监控
        await system_coordinator.start()

        # 验证启动状态
        new_status = state.is_running()
        logging.info(f"【调试】启动后运行状态: {new_status}")
        print_status(f"【调试】监控启动{'成功' if new_status else '失败'}", "ok" if new_status else "error")

        # 获取订阅状态
        subscribed_count = container.subscription_manager.subscribed_count
        print_status(f"【调试】已订阅股票数量: {subscribed_count}", "info")

        return APIResponse.ok(
            data=MonitorStartResponse(
                futu_available=futu_available,
                stock_count=stock_count,
                subscribed_count=subscribed_count
            ),
            message="监控已启动"
        )
    except Exception as e:
        print_status(f"【错误】启动监控失败: {str(e)}", "error")
        logging.error(f"【调试】启动监控异常: {e}", exc_info=True)
        raise BusinessError(
            message=f"启动监控失败: {str(e)}",
            details={'error': str(e)}
        )


@router.post("/stop", response_model=APIResponse[None])
async def stop_monitoring(
    container=Depends(get_container),
    system_coordinator=Depends(get_system_coordinator)
):
    """停止监控"""
    state = get_state_manager()

    # 使用系统协调器停止监控
    await system_coordinator.stop()

    return APIResponse.ok(message="监控已停止")


@router.get("/health", response_model=APIResponse[HealthCheckData])
async def health_check(container=Depends(get_container)):
    """健康检查接口 - 返回系统各组件状态"""
    from ...utils.logger import print_status

    try:
        state = get_state_manager()

        print_status("【调试】收到健康检查请求", "info")

        # 检查监控运行状态
        is_running = state.is_running()

        # 检查富途API连接状态
        futu_available = container.futu_client.is_available()

        # 检查股票池状态
        stock_pool = state.get_stock_pool()
        stock_count = len(stock_pool.get('stocks', []))

        # 检查订阅状态
        subscribed_count = container.subscription_manager.subscribed_count
        subscribed_stocks = list(container.subscription_manager.subscribed_stocks)[:5]

        # 检查监控线程状态
        # TODO: 需要访问 trading_system.monitor_coordinator
        monitor_thread_alive = False

        # 获取最后更新时间
        last_update = state.get_last_update()

        health_data = HealthCheckData(
            timestamp=datetime.now().isoformat(),
            status=MonitorHealth(
                is_running=is_running,
                futu_api_available=futu_available,
                monitor_thread_alive=monitor_thread_alive
            ),
            stock_pool=StockPoolHealth(
                total_count=stock_count,
                has_data=stock_count > 0
            ),
            subscription=SubscriptionHealth(
                subscribed_count=subscribed_count,
                has_subscription=subscribed_count > 0,
                sample_stocks=subscribed_stocks
            ),
            last_update=last_update.isoformat() if last_update else None,
            config=ConfigInfo(
                auto_trade=container.config.auto_trade,
                update_interval=container.config.update_interval,
                max_stocks=container.config.max_stocks_monitor
            )
        )

        print_status(
            f"【调试】健康检查完成: 运行={is_running}, 富途={futu_available}, 股票池={stock_count}, 订阅={subscribed_count}",
            "info"
        )

        return APIResponse.ok(data=health_data)

    except Exception as e:
        logging.error(f"健康检查失败: {e}", exc_info=True)
        raise BusinessError(message=f"健康检查失败: {str(e)}")


@router.post("/control", response_model=APIResponse[dict])
async def control_system(
    request: MonitorControlRequest,
    container=Depends(get_container),
    system_coordinator=Depends(get_system_coordinator)
):
    """系统控制接口"""
    state = get_state_manager()

    if request.action == 'start':
        if state.is_running():
            return APIResponse.ok(
                data={'is_running': True, 'action': 'start'},
                message="监控已在运行中"
            )
        await system_coordinator.start()
        return APIResponse.ok(
            data={'is_running': True, 'action': 'start'},
            message="监控已启动"
        )
    elif request.action == 'stop':
        if not state.is_running():
            return APIResponse.ok(
                data={'is_running': False, 'action': 'stop'},
                message="监控未在运行"
            )
        await system_coordinator.stop()
        return APIResponse.ok(
            data={'is_running': False, 'action': 'stop'},
            message="监控已停止"
        )
    else:
        raise BusinessError(
            message="无效的控制操作，支持: start, stop",
            details={'action': request.action}
        )
