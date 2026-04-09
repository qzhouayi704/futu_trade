#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线数据模型
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class KlineData:
    """K线数据模型"""
    time_key: str  # 日期 (YYYY-MM-DD)
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    turnover: Optional[float] = None
    pe_ratio: Optional[float] = None
    turnover_rate: Optional[float] = None

    @classmethod
    def from_db_row(cls, row: tuple) -> 'KlineData':
        """从数据库查询结果创建对象 (基础查询: 6个字段)

        Note: 统一使用完整字段名 (open_price 而非 open)
        """
        return cls(
            time_key=row[0],
            open_price=float(row[1]) if row[1] else 0.0,
            high_price=float(row[2]) if row[2] else 0.0,
            low_price=float(row[3]) if row[3] else 0.0,
            close_price=float(row[4]) if row[4] else 0.0,
            volume=int(row[5]) if row[5] else 0
        )

    @classmethod
    def from_db_row_full(cls, row: tuple) -> 'KlineData':
        """从数据库查询结果创建对象 (完整查询: 9个字段)"""
        return cls(
            time_key=row[0],
            open_price=float(row[1]) if row[1] else 0.0,
            high_price=float(row[2]) if row[2] else 0.0,
            low_price=float(row[3]) if row[3] else 0.0,
            close_price=float(row[4]) if row[4] else 0.0,
            volume=int(row[5]) if row[5] else 0,
            turnover=float(row[6]) if row[6] else None,
            pe_ratio=float(row[7]) if row[7] else None,
            turnover_rate=float(row[8]) if row[8] else None
        )

    def to_dict(self) -> dict:
        """转换为字典

        Note: 为保持向后兼容,同时提供短字段名和完整字段名
        """
        return {
            # 短字段名 (兼容旧代码)
            'date': self.time_key,
            'open': self.open_price,
            'high': self.high_price,
            'low': self.low_price,
            'close': self.close_price,
            'volume': self.volume,
            # 完整字段名 (推荐使用)
            'time_key': self.time_key,
            'open_price': self.open_price,
            'high_price': self.high_price,
            'low_price': self.low_price,
            'close_price': self.close_price
        }
