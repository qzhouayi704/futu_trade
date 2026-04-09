#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分仓止盈数据模型

定义仓位（Lot）和止盈任务的强类型数据结构。
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class PositionLot:
    """单个仓位（一笔买入成交记录）"""
    deal_id: str           # 富途成交ID
    stock_code: str
    buy_price: float       # 买入价格
    quantity: int           # 原始买入数量
    remaining_qty: int      # 剩余数量（扣除已卖出）
    deal_time: str          # 成交时间
    current_profit_pct: float = 0.0   # 当前盈亏百分比（实时计算）
    trigger_price: float = 0.0        # 止盈触发价

    def to_dict(self) -> Dict[str, Any]:
        return {
            'deal_id': self.deal_id,
            'stock_code': self.stock_code,
            'buy_price': self.buy_price,
            'quantity': self.quantity,
            'remaining_qty': self.remaining_qty,
            'deal_time': self.deal_time,
            'current_profit_pct': round(self.current_profit_pct, 2),
            'trigger_price': round(self.trigger_price, 3),
        }


@dataclass
class TakeProfitTask:
    """分仓止盈任务"""
    id: int
    stock_code: str
    stock_name: str
    take_profit_pct: float     # 止盈百分比
    status: str                # ACTIVE / COMPLETED / CANCELLED
    total_lots: int
    sold_lots: int
    created_at: str
    updated_at: str = ''
    lots: List[PositionLot] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'take_profit_pct': self.take_profit_pct,
            'status': self.status,
            'total_lots': self.total_lots,
            'sold_lots': self.sold_lots,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'lots': [lot.to_dict() for lot in self.lots],
        }


@dataclass
class TakeProfitExecution:
    """止盈执行记录（每个仓位一条）"""
    id: int
    task_id: int
    stock_code: str
    lot_buy_price: float
    lot_quantity: int
    trigger_price: float
    sell_price: Optional[float] = None
    profit_amount: Optional[float] = None
    status: str = 'PENDING'        # PENDING / TRIGGERED / EXECUTED / FAILED / CANCELLED
    triggered_at: Optional[str] = None
    executed_at: Optional[str] = None
    error_msg: Optional[str] = None
    deal_id: Optional[str] = None   # 关联的富途成交ID
    order_id: Optional[str] = None  # 报单成功后的富途订单ID

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'task_id': self.task_id,
            'stock_code': self.stock_code,
            'lot_buy_price': self.lot_buy_price,
            'lot_quantity': self.lot_quantity,
            'trigger_price': round(self.trigger_price, 3),
            'sell_price': self.sell_price,
            'profit_amount': self.profit_amount,
            'status': self.status,
            'triggered_at': self.triggered_at,
            'executed_at': self.executed_at,
            'error_msg': self.error_msg,
            'deal_id': self.deal_id,
            'order_id': self.order_id,
        }

