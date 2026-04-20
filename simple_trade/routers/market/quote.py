#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报价和行情路由 - FastAPI Router

迁移自 routes/quote_routes.py
包含报价、预警、交易条件等接口
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...core import get_state_manager
from ...dependencies import get_container
from ...schemas.common import APIResponse


router = APIRouter(prefix="/api", tags=["报价行情"])


# ==================== Pydantic Models ====================

class QuoteResponse(BaseModel):
    """报价响应"""
    success: bool
    data: List[Dict[str, Any]]
    count: int
    cached: bool
    message: str = ""
    last_update: str


# ==================== API Endpoints ====================

@router.get("/quotes")
async def get_quotes(container=Depends(get_container)):
    """获取实时报价数据"""
    state = get_state_manager()

    # 优先使用缓存
    cached_quotes = state.get_cached_quotes()
    if cached_quotes is not None:
        logging.debug(f"使用缓存的报价数据: {len(cached_quotes)} 条记录")
        return {
            'success': True,
            'data': cached_quotes,
            'count': len(cached_quotes),
            'cached': True,
            'last_update': datetime.now().isoformat()
        }

    # 检查监控状态
    if not state.is_running():
        logging.debug("监控未启动，返回空报价数据")
        return {
            'success': True,
            'data': [],
            'count': 0,
            'cached': False,
            'message': '监控未启动',
            'last_update': datetime.now().isoformat()
        }

    # 缓存无效，从订阅管理器获取股票代码
    subscribed_codes = list(container.subscription_manager.subscribed_stocks)

    if not subscribed_codes:
        logging.debug("暂无订阅股票，返回空报价数据")
        return {
            'success': True,
            'data': [],
            'count': 0,
            'cached': False,
            'message': '暂无监控股票',
            'last_update': datetime.now().isoformat()
        }

    logging.debug(f"获取 {len(subscribed_codes)} 只订阅股票的报价")

    # 从 stock_pool 获取股票详细信息
    stock_pool_data = state.get_stock_pool()
    target_stocks = [
        stock for stock in stock_pool_data['stocks']
        if stock['code'] in subscribed_codes
    ]

    # 使用异步方式获取报价，避免阻塞事件循环
    quotes = await asyncio.to_thread(
        container.stock_data_service.get_real_quotes_from_subscribed, target_stocks
    )

    # 更新缓存
    state.update_quotes_cache(quotes)

    return {
        'success': True,
        'data': quotes,
        'count': len(quotes),
        'cached': False,
        'last_update': datetime.now().isoformat()
    }


@router.get("/quotes/alerts", response_model=APIResponse)
async def get_alerts(container=Depends(get_container)):
    """获取预警信息（返回累积的预警历史）"""
    state = get_state_manager()

    # 从状态管理器获取累积的预警
    alerts = state.get_accumulated_alerts()

    return APIResponse(
        success=True,
        message="获取预警信息成功",
        data=alerts
    )


@router.get("/quotes/conditions", response_model=APIResponse)
async def get_conditions(container=Depends(get_container)):
    """获取交易条件显示数据"""
    state = get_state_manager()
    conditions_data = state.get_trading_conditions()

    # 转换成前端期望的格式
    conditions_list = []
    for stock_code, condition_data in conditions_data.items():
        # 获取信号状态
        buy_signal = condition_data.get('buy_signal', False)
        sell_signal = condition_data.get('sell_signal', False)

        # 获取详细条件列表
        details = condition_data.get('details', [])

        # 如果有详细条件，使用详细条件；否则解析 reason 文本
        if details:
            conditions = _format_condition_details(details)
        else:
            reason = condition_data.get('reason', '')
            conditions = _parse_condition_text(reason)

        # 确定条件类型：
        # 1. 如果有买入信号，显示为买入条件
        # 2. 如果有卖出信号，显示为卖出条件
        # 3. 如果都没有信号，显示为观察状态
        if buy_signal:
            condition_type = 'buy'
        elif sell_signal:
            condition_type = 'sell'
        else:
            condition_type = 'watch'

        # 判断是否所有条件都通过
        all_passed = buy_signal or sell_signal

        conditions_list.append({
            'stock_code': stock_code,
            'stock_name': condition_data.get('stock_name', ''),
            'condition_type': condition_type,
            'conditions': conditions,
            'all_passed': all_passed
        })

    logging.info(f"获取交易条件数据: {len(conditions_list)} 条记录")

    return APIResponse(
        success=True,
        message="获取交易条件成功",
        data=conditions_list
    )


def _format_condition_details(details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """格式化详细条件列表"""
    conditions = []

    for detail in details:
        # 如果是字典格式的 ConditionDetail
        if isinstance(detail, dict):
            name = detail.get('name', '')
            current_value = detail.get('current_value', '')
            target_value = detail.get('target_value', '')
            passed = detail.get('passed', False)
            description = detail.get('description', '')

            # 构建描述文本
            if description:
                desc_text = description
            else:
                desc_text = f"当前值: {current_value}, 目标值: {target_value}"

            conditions.append({
                'name': name,
                'description': desc_text,
                'passed': passed,
                'value': current_value,
                'threshold': target_value
            })

    return conditions


def _parse_condition_text(reason: str) -> List[Dict[str, Any]]:
    """解析条件文本，提取条件列表"""
    conditions = []

    if not reason:
        return conditions

    # 按 " | " 分割条件
    parts = reason.split(' | ')

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # 判断条件是否通过
        passed = part.startswith('✅')

        # 移除前缀符号
        text = part.replace('✅', '').replace('❌', '').strip()

        # 尝试提取名称和描述
        if ':' in text:
            name, description = text.split(':', 1)
            name = name.strip()
            description = description.strip()
        else:
            name = text
            description = text

        conditions.append({
            'name': name,
            'description': description,
            'passed': passed
        })

    return conditions


@router.get("/quotes/trading-conditions", response_model=APIResponse)
async def get_trading_conditions():
    """获取详细交易条件数据"""
    state = get_state_manager()
    conditions_data = state.get_trading_conditions()
    conditions_list = list(conditions_data.values())

    logging.info(f"从状态管理器获取交易条件数据: {len(conditions_list)} 条记录")

    return APIResponse(
        success=True,
        message="获取交易条件成功",
        data=conditions_list
    )


@router.get("/quotes/quota", response_model=APIResponse)
async def get_quota(container=Depends(get_container)):
    """获取K线配额信息"""
    quota_data = await asyncio.to_thread(container.kline_service.get_quota_info)

    return APIResponse(
        success=True,
        message="获取K线配额成功",
        data=quota_data
    )


@router.get("/quotes/subscription-status", response_model=APIResponse)
async def get_subscription_status(container=Depends(get_container)):
    """获取股票订阅状态"""
    status = await asyncio.to_thread(container.realtime_query.check_subscription_status)

    return APIResponse(
        success=True,
        message="获取订阅状态成功",
        data=status
    )


@router.get("/quotes/trade-signals", response_model=APIResponse)
async def get_trade_signals():
    """获取当前交易信号（来自内存状态，实时更新）"""
    state = get_state_manager()
    signals = state.get_trade_signals()

    return APIResponse(
        success=True,
        message="获取交易信号成功",
        data=signals
    )


logging.info("报价行情路由已注册")
