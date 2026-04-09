#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票数据模型
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class Stock:
    """股票数据模型 (基础)"""
    id: int
    code: str
    name: str
    market: str
    is_manual: bool = False
    stock_priority: int = 0
    heat_score: float = 0.0
    avg_turnover_rate: float = 0.0
    avg_volume: float = 0.0
    active_days: int = 0
    heat_update_time: Optional[datetime] = None
    is_low_activity: bool = False
    low_activity_checked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_db_row(cls, row: tuple) -> 'Stock':
        """从数据库查询结果创建对象 (基础查询: 4个字段)"""
        return cls(
            id=row[0],
            code=row[1],
            name=row[2],
            market=row[3]
        )

    @classmethod
    def from_db_row_full(cls, row: tuple) -> 'Stock':
        """从数据库查询结果创建对象 (完整查询: 所有字段，不含 is_hot)"""
        return cls(
            id=row[0],
            code=row[1],
            name=row[2],
            market=row[3],
            is_manual=bool(row[4]) if row[4] is not None else False,
            stock_priority=row[5] or 0,
            heat_score=float(row[6]) if row[6] else 0.0,
            avg_turnover_rate=float(row[7]) if row[7] else 0.0,
            avg_volume=float(row[8]) if row[8] else 0.0,
            active_days=row[9] or 0,
            heat_update_time=row[10],
            is_low_activity=bool(row[11]) if row[11] is not None else False,
            low_activity_checked_at=row[12],
            created_at=row[13],
            updated_at=row[14]
        )

    def to_dict(self) -> dict:
        """转换为字典 (保持向后兼容)"""
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'market': self.market
        }


@dataclass
class StockWithPlate:
    """股票数据模型 (带板块关联信息)"""
    id: int
    code: str
    name: str
    market: str
    plate_name: Optional[str] = None
    plate_priority: int = 0
    is_manual: bool = False
    stock_priority: int = 0
    is_low_activity: bool = False
    has_kline: bool = False
    final_priority: int = 0
    was_low_activity: bool = False

    @classmethod
    def from_db_row(cls, row: tuple, kline_stocks: set = None) -> 'StockWithPlate':
        """从数据库查询结果创建对象 (带板块关联查询: 9个字段)"""
        code = row[1]
        is_manual = bool(row[6]) if row[6] is not None else False
        stock_priority = row[7] if row[7] is not None else 0
        plate_priority = row[5] or 0
        is_low_activity = bool(row[8]) if row[8] is not None else False

        return cls(
            id=row[0],
            code=code,
            name=row[2],
            market=row[3],
            plate_name=row[4],
            plate_priority=plate_priority,
            is_manual=is_manual,
            stock_priority=stock_priority,
            is_low_activity=is_low_activity,
            has_kline=code in kline_stocks if kline_stocks else False,
            final_priority=stock_priority if is_manual else plate_priority,
            was_low_activity=is_low_activity
        )

    def to_dict(self) -> dict:
        """转换为字典 (保持向后兼容)"""
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'market': self.market,
            'plate_name': self.plate_name,
            'priority': self.plate_priority,
            'is_manual': self.is_manual,
            'stock_priority': self.stock_priority,
            'has_kline': self.has_kline,
            'final_priority': self.final_priority,
            'was_low_activity': self.was_low_activity
        }
