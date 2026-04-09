#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓订单路由

提供单笔订单的仓位查询、止盈配置管理的 API 接口。
"""

import logging

from fastapi import APIRouter, Depends

from ...dependencies import get_container
from ...schemas.common import APIResponse
from ...schemas.take_profit import CreateLotTakeProfitRequest


router = APIRouter(
    prefix="/api/trading/position-orders",
    tags=["持仓订单"],
)


# ==================== Helper ====================

def _get_lot_tp_service(container):
    """获取分仓止盈服务"""
    if not hasattr(container, 'lot_take_profit_service') or not container.lot_take_profit_service:
        raise Exception("分仓止盈服务未初始化")
    return container.lot_take_profit_service


def _get_lot_order_tp_service(container):
    """获取单笔订单止盈服务"""
    if not hasattr(container, 'lot_order_take_profit_service') or not container.lot_order_take_profit_service:
        raise Exception("单笔订单止盈服务未初始化")
    return container.lot_order_take_profit_service


# ==================== API Endpoints ====================

@router.get("/{stock_code}/lots")
async def get_order_lots(stock_code: str, container=Depends(get_container)):
    """
    获取某只股票的订单历史（仓位列表），附带止盈配置状态。

    通过 FIFO 算法还原各仓位的剩余数量，并关联已有的止盈配置信息。
    """
    try:
        lot_tp_service = _get_lot_tp_service(container)
        lot_order_tp_service = _get_lot_order_tp_service(container)

        # 1. 从富途 API 获取仓位列表（FIFO 还原）
        lots = lot_tp_service.get_position_lots(stock_code)
        lots_data = [lot.to_dict() for lot in lots]

        # 2. 附加止盈配置状态
        result = lot_order_tp_service.get_lots_with_take_profit_status(
            stock_code, lots_data,
        )

        return APIResponse.ok(
            data=result,
            message=f"获取到 {len(result)} 条订单记录",
        )
    except Exception as e:
        logging.error(f"获取订单历史失败: {e}")
        return APIResponse.fail(message=str(e))


@router.post("/take-profit")
async def create_lot_take_profit(
    request: CreateLotTakeProfitRequest,
    container=Depends(get_container),
):
    """为单笔订单创建止盈配置"""
    try:
        service = _get_lot_order_tp_service(container)
        result = service.create_lot_take_profit(
            stock_code=request.stock_code,
            deal_id=request.deal_id,
            buy_price=request.buy_price,
            quantity=request.quantity,
            take_profit_pct=request.take_profit_pct,
        )
        if result['success']:
            return APIResponse.ok(
                data=result.get('data'),
                message=result.get('message', '止盈配置创建成功'),
            )
        return APIResponse.fail(message=result['message'])
    except Exception as e:
        logging.error(f"创建止盈配置失败: {e}")
        return APIResponse.fail(message=str(e))


@router.post("/take-profit/{execution_id}/cancel")
async def cancel_lot_take_profit(
    execution_id: int,
    container=Depends(get_container),
):
    """取消单笔订单的止盈配置"""
    try:
        service = _get_lot_order_tp_service(container)
        result = service.cancel_lot_take_profit(execution_id)
        if result['success']:
            return APIResponse.ok(message=result['message'])
        return APIResponse.fail(message=result['message'])
    except Exception as e:
        logging.error(f"取消止盈配置失败: {e}")
        return APIResponse.fail(message=str(e))


@router.get("/{stock_code}/take-profit")
async def get_lot_take_profit_configs(
    stock_code: str,
    container=Depends(get_container),
):
    """获取某只股票的所有止盈配置"""
    try:
        service = _get_lot_order_tp_service(container)
        configs = service.get_lot_take_profit_configs(stock_code)
        return APIResponse.ok(
            data=configs,
            message=f"获取到 {len(configs)} 条止盈配置",
        )
    except Exception as e:
        logging.error(f"获取止盈配置失败: {e}")
        return APIResponse.fail(message=str(e))
