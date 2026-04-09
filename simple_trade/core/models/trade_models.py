#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易信号和条件数据模型
"""

from dataclasses import dataclass
from typing import Optional, List


@dataclass
class TradeSignal:
    """交易信号数据模型

    完整 14 个字段（与数据库 JOIN 查询字段顺序一致）:
    id, stock_id, signal_type, signal_price, target_price, stop_loss_price,
    condition_text, is_executed, executed_time, created_at,
    stock_code, stock_name, strategy_id, strategy_name
    """
    id: int
    stock_id: int
    signal_type: str  # BUY / SELL
    signal_price: float
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    condition_text: Optional[str] = None
    is_executed: bool = False
    executed_time: Optional[str] = None
    created_at: Optional[str] = None
    # JOIN 字段 (来自 stocks 表)
    stock_code: Optional[str] = None
    stock_name: Optional[str] = None
    # 策略字段
    strategy_id: Optional[str] = None
    strategy_name: Optional[str] = None

    @classmethod
    def from_db_row(cls, row: tuple) -> 'TradeSignal':
        """从数据库查询结果创建对象 (基础查询: 10个字段)"""
        return cls(
            id=row[0],
            stock_id=row[1],
            signal_type=row[2],
            signal_price=float(row[3]) if row[3] else 0.0,
            target_price=float(row[4]) if row[4] else None,
            stop_loss_price=float(row[5]) if row[5] else None,
            condition_text=row[6],
            is_executed=bool(row[7]) if row[7] is not None else False,
            executed_time=row[8],
            created_at=row[9]
        )

    @classmethod
    def from_db_row_with_stock(cls, row: tuple) -> 'TradeSignal':
        """从数据库查询结果创建对象 (带股票和策略信息: 14个字段)

        字段顺序: id, stock_id, signal_type, signal_price, target_price,
        stop_loss_price, condition_text, is_executed, executed_time, created_at,
        stock_code, stock_name, strategy_id, strategy_name
        """
        return cls(
            id=row[0],
            stock_id=row[1],
            signal_type=row[2],
            signal_price=float(row[3]) if row[3] else 0.0,
            target_price=float(row[4]) if row[4] else None,
            stop_loss_price=float(row[5]) if row[5] else None,
            condition_text=row[6],
            is_executed=bool(row[7]) if row[7] is not None else False,
            executed_time=row[8],
            created_at=row[9],
            stock_code=row[10] if len(row) > 10 else None,
            stock_name=row[11] if len(row) > 11 else None,
            strategy_id=row[12] if len(row) > 12 else None,
            strategy_name=row[13] if len(row) > 13 else None,
        )

    def to_dict(self) -> dict:
        """转换为 API 响应字典

        始终包含所有字段，确保 API 响应格式一致。
        注意: signal_price 在 API 中映射为 'price'。
        """
        return {
            'id': self.id,
            'stock_id': self.stock_id,
            'signal_type': self.signal_type,
            'price': self.signal_price,  # API 使用 'price' 而非 'signal_price'
            'target_price': self.target_price,
            'stop_loss_price': self.stop_loss_price,
            'condition_text': self.condition_text,
            'is_executed': self.is_executed,
            'executed_time': self.executed_time,
            'created_at': self.created_at,
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'strategy_id': self.strategy_id,
            'strategy_name': self.strategy_name,
        }


@dataclass
class TradingCondition:
    """交易条件数据模型"""
    stock_code: str
    stock_name: str
    market: str
    buy_conditions: List[dict]
    sell_conditions: List[dict]
    has_buy_signal: bool = False
    has_sell_signal: bool = False
    last_price: Optional[float] = None

    def to_dict(self) -> dict:
        """转换为字典 (保持向后兼容)"""
        return {
            'code': self.stock_code,
            'name': self.stock_name,
            'market': self.market,
            'buy_conditions': self.buy_conditions,
            'sell_conditions': self.sell_conditions,
            'has_buy_signal': self.has_buy_signal,
            'has_sell_signal': self.has_sell_signal,
            'last_price': self.last_price
        }
