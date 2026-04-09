#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块数据模型
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class Plate:
    """板块数据模型"""
    id: int
    code: str
    name: str
    market: str
    category: Optional[str] = None
    stock_count: int = 0
    priority: int = 0
    match_score: int = 0
    is_target: bool = False
    is_enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_db_row(cls, row: tuple) -> 'Plate':
        """从数据库查询结果创建对象 (基础查询: 8个字段)"""
        return cls(
            id=row[0],
            code=row[1],
            name=row[2],
            market=row[3],
            category=row[4],
            stock_count=row[5] or 0,
            priority=row[6] or 0,
            match_score=row[7] or 0
        )

    @classmethod
    def from_db_row_full(cls, row: tuple) -> 'Plate':
        """从数据库查询结果创建对象 (完整查询: 所有字段)"""
        return cls(
            id=row[0],
            code=row[1],
            name=row[2],
            market=row[3],
            category=row[4],
            stock_count=row[5] or 0,
            is_target=bool(row[6]) if row[6] is not None else False,
            is_enabled=bool(row[7]) if row[7] is not None else True,
            priority=row[8] or 0,
            match_score=row[9] or 0,
            created_at=row[10],
            updated_at=row[11]
        )

    def to_dict(self) -> dict:
        """转换为字典 (保持向后兼容)"""
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'market': self.market,
            'category': self.category or '',
            'stock_count': self.stock_count,
            'priority': self.priority,
            'match_score': self.match_score
        }
