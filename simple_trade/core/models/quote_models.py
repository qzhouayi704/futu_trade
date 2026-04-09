#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报价和索引数据模型
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class Quote:
    """实时报价数据模型"""
    code: str
    name: str
    last_price: float
    prev_close: float
    open_price: float
    high_price: float
    low_price: float
    volume: int
    turnover: float
    turnover_rate: float
    change_val: float
    change_rate: float
    amplitude: float
    market: str
    update_time: Optional[datetime] = None

    @classmethod
    def from_api_response(cls, data: dict) -> 'Quote':
        """从富途API响应创建对象"""
        return cls(
            code=data.get('code', ''),
            name=data.get('name', ''),
            last_price=float(data.get('last_price', 0)),
            prev_close=float(data.get('prev_close', 0)),
            open_price=float(data.get('open_price', 0)),
            high_price=float(data.get('high_price', 0)),
            low_price=float(data.get('low_price', 0)),
            volume=int(data.get('volume', 0)),
            turnover=float(data.get('turnover', 0)),
            turnover_rate=float(data.get('turnover_rate', 0)),
            change_val=float(data.get('change_val', 0)),
            change_rate=float(data.get('change_rate', 0)),
            amplitude=float(data.get('amplitude', 0)),
            market=data.get('market', ''),
            update_time=data.get('update_time')
        )

    def to_dict(self) -> dict:
        """转换为字典 (保持向后兼容)"""
        return {
            'code': self.code,
            'name': self.name,
            'last_price': self.last_price,
            'prev_close': self.prev_close,
            'open_price': self.open_price,
            'high_price': self.high_price,
            'low_price': self.low_price,
            'volume': self.volume,
            'turnover': self.turnover,
            'turnover_rate': self.turnover_rate,
            'change_val': self.change_val,
            'change_rate': self.change_rate,
            'amplitude': self.amplitude,
            'market': self.market
        }


@dataclass
class IndexInfo:
    """数据库索引信息"""
    name: str
    table: str
    sql: str

    @classmethod
    def from_db_row(cls, row: tuple) -> 'IndexInfo':
        """从数据库查询结果创建对象"""
        return cls(
            name=row[0],
            table=row[1],
            sql=row[2]
        )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'name': self.name,
            'table': self.table,
            'sql': self.sql
        }
