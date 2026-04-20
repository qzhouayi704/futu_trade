#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统状态路由 - FastAPI Router

迁移自 routes/system_routes.py 的 system 蓝图
"""

import logging
from datetime import datetime
from typing import Dict

from fastapi import APIRouter, Depends, Query

from ...core import get_state_manager
from ...dependencies import get_container
from ...schemas.common import APIResponse
from ...schemas.system import (
    SystemStatus,
    ConfigInfo,
    DiagnosisResult,
    FutuAPIDiagnosis,
    DatabaseDiagnosis,
    DataStats,
)


router = APIRouter(prefix="/api/system", tags=["系统状态"])


@router.get("/status", response_model=APIResponse[SystemStatus])
async def get_status(container=Depends(get_container)):
    """获取系统状态"""
    state = get_state_manager()

    subscription_status = container.realtime_query.check_subscription_status()
    last_update = state.get_last_update()

    status_data = SystemStatus(
        is_running=state.is_running(),
        last_update=last_update.isoformat() if last_update else None,
        futu_connected=container.futu_client.is_available(),
        subscription_status=subscription_status,
        config=ConfigInfo(
            auto_trade=container.config.auto_trade,
            update_interval=container.config.update_interval,
            max_stocks=container.config.max_stocks_monitor
        )
    )

    return APIResponse.ok(data=status_data)


@router.get("/info", response_model=APIResponse[Dict])
async def get_system_info(
    types: str = Query(default="status", description="信息类型，逗号分隔"),
    container=Depends(get_container)
):
    """获取详细系统信息"""
    state = get_state_manager()
    info_types = types.split(',')
    result_data = {}

    if 'status' in info_types:
        last_update = state.get_last_update()
        result_data['status'] = {
            'is_running': state.is_running(),
            'last_update': last_update.isoformat() if last_update else None,
            'futu_connected': container.futu_client.is_available() if container.futu_client else False,
            'config': {
                'auto_trade': container.config.auto_trade,
                'update_interval': container.config.update_interval,
                'max_stocks': container.config.max_stocks_monitor
            }
        }

    return APIResponse.ok(data=result_data, message="获取系统信息成功")


@router.get("/diagnosis", response_model=DiagnosisResult)
async def get_diagnosis(container=Depends(get_container)):
    """系统诊断API"""
    diagnosis_result = {
        'success': True,
        'timestamp': datetime.now().isoformat(),
        'futu_api': {},
        'database': {},
        'data_initialization': {},
        'recommendations': []
    }

    # 1. 富途API诊断
    futu_status = container.futu_client.get_connection_status()
    diagnosis_result['futu_api'] = {
        'status': futu_status,
        'test_results': {}
    }

    if not futu_status.get('futu_api_available', False):
        diagnosis_result['recommendations'].append('富途API包未安装，请运行: pip install futu-api')
    elif not futu_status.get('is_connected', False):
        diagnosis_result['recommendations'].append('富途API未连接，请检查富途客户端是否已启动')

    # 2. 数据库诊断
    try:
        table_rows = container.db_manager.execute_query(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        existing_tables = [row[0] for row in table_rows]

        required_tables = ['plates', 'stocks', 'kline_data', 'system_config']
        missing_tables = [t for t in required_tables if t not in existing_tables]

        plates_result = container.db_manager.execute_query("SELECT COUNT(*) FROM plates")
        plates_count = plates_result[0][0] if plates_result else 0

        stocks_result = container.db_manager.execute_query("SELECT COUNT(*) FROM stocks")
        stocks_count = stocks_result[0][0] if stocks_result else 0

        diagnosis_result['database'] = {
            'connection': True,
            'existing_tables': existing_tables,
            'missing_tables': missing_tables,
            'tables_complete': len(missing_tables) == 0,
            'data_stats': {
                'plates_total': plates_count,
                'stocks_active': stocks_count
            }
        }

        if missing_tables:
            diagnosis_result['recommendations'].append(f'数据库表缺失: {", ".join(missing_tables)}')

    except Exception as db_error:
        diagnosis_result['database'] = {
            'connection': False,
            'error': str(db_error)
        }
        diagnosis_result['recommendations'].append('数据库连接失败')

    # 3. 数据初始化诊断
    try:
        init_status = container.data_initializer.get_initialization_status()
        diagnosis_result['data_initialization'] = init_status

        if not init_status.get('is_initialized', False):
            diagnosis_result['recommendations'].append('数据未初始化，请执行数据初始化')

    except Exception as init_error:
        diagnosis_result['data_initialization'] = {'error': str(init_error)}

    if not diagnosis_result['recommendations']:
        diagnosis_result['recommendations'].append('系统状态正常')

    return diagnosis_result


@router.get("/metrics", response_model=APIResponse[Dict])
async def get_metrics_snapshot():
    """系统 Metrics 快照

    返回所有已注册的计数器、瞬时值、直方图和速率指标。
    """
    from ...utils.metrics import get_metrics
    return APIResponse.ok(data=get_metrics().snapshot(), message="Metrics 快照")
