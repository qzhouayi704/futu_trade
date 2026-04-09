#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心数据库模型
包含：PlateModel, StockModel, StockPlateModel, KlineDataModel
"""

from typing import Optional, List


class PlateModel:
    """板块模型

    字段说明：
    - is_target: 是否为目标板块（用户选择关注的板块）
    - is_enabled: 是否启用（控制板块是否参与实时监控，默认True）
    """

    def __init__(
        self,
        plate_id: Optional[int] = None,
        plate_code: str = "",
        plate_name: str = "",
        market: str = "",
        category: str = "",
        stock_count: int = 0,
        is_target: bool = False,
        is_enabled: bool = True,
        priority: int = 0,
        match_score: int = 0,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None
    ):
        self.id = plate_id
        self.plate_code = plate_code
        self.plate_name = plate_name
        self.market = market
        self.category = category
        self.stock_count = stock_count
        self.is_target = is_target
        self.is_enabled = is_enabled
        self.priority = priority
        self.match_score = match_score
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'plate_code': self.plate_code,
            'plate_name': self.plate_name,
            'market': self.market,
            'category': self.category,
            'stock_count': self.stock_count,
            'is_target': self.is_target,
            'is_enabled': self.is_enabled,
            'priority': self.priority,
            'match_score': self.match_score,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }

    @classmethod
    def from_row(cls, row: tuple) -> 'PlateModel':
        """从数据库行创建模型

        数据库列顺序: id, plate_code, plate_name, market, category,
                     stock_count, is_target, is_enabled, priority, match_score,
                     created_at, updated_at
        """
        return cls(
            plate_id=row[0],
            plate_code=row[1],
            plate_name=row[2],
            market=row[3],
            category=row[4] if len(row) > 4 else "",
            stock_count=row[5] if len(row) > 5 else 0,
            is_target=bool(row[6]) if len(row) > 6 else False,
            is_enabled=bool(row[7]) if len(row) > 7 else True,
            priority=row[8] if len(row) > 8 else 0,
            match_score=row[9] if len(row) > 9 else 0,
            created_at=row[10] if len(row) > 10 else None,
            updated_at=row[11] if len(row) > 11 else None
        )


class StockModel:
    """股票模型"""

    def __init__(
        self,
        stock_id: Optional[int] = None,
        code: str = "",
        name: str = "",
        market: str = "",
        is_manual: bool = False,
        stock_priority: int = 0,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        # 关联数据（非数据库字段）
        plate_names: Optional[List[str]] = None,
        plate_ids: Optional[List[int]] = None
    ):
        self.id = stock_id
        self.code = code
        self.name = name
        self.market = market
        self.is_manual = is_manual
        self.stock_priority = stock_priority
        self.created_at = created_at
        self.updated_at = updated_at
        # 关联的板块信息
        self.plate_names = plate_names or []
        self.plate_ids = plate_ids or []

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'market': self.market,
            'is_manual': self.is_manual,
            'stock_priority': self.stock_priority,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'plate_names': self.plate_names,
            'plate_ids': self.plate_ids
        }

    @classmethod
    def from_row(cls, row: tuple) -> 'StockModel':
        """从数据库行创建模型"""
        return cls(
            stock_id=row[0],
            code=row[1],
            name=row[2],
            market=row[3],
            is_manual=bool(row[4]) if len(row) > 4 else False,
            stock_priority=row[5] if len(row) > 5 else 0,
            created_at=row[6] if len(row) > 6 else None,
            updated_at=row[7] if len(row) > 7 else None
        )


class StockPlateModel:
    """股票-板块关联模型"""

    def __init__(
        self,
        id: Optional[int] = None,
        stock_id: int = 0,
        plate_id: int = 0,
        created_at: Optional[str] = None
    ):
        self.id = id
        self.stock_id = stock_id
        self.plate_id = plate_id
        self.created_at = created_at

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'stock_id': self.stock_id,
            'plate_id': self.plate_id,
            'created_at': self.created_at
        }


class KlineDataModel:
    """K线数据模型"""

    def __init__(
        self,
        kline_id: Optional[int] = None,
        stock_code: str = "",
        time_key: str = "",
        open_price: float = 0.0,
        close_price: float = 0.0,
        high_price: float = 0.0,
        low_price: float = 0.0,
        volume: int = 0,
        turnover: float = 0.0,
        pe_ratio: Optional[float] = None,
        turnover_rate: Optional[float] = None,
        created_at: Optional[str] = None
    ):
        self.id = kline_id
        self.stock_code = stock_code
        self.time_key = time_key
        self.open_price = open_price
        self.close_price = close_price
        self.high_price = high_price
        self.low_price = low_price
        self.volume = volume
        self.turnover = turnover
        self.pe_ratio = pe_ratio
        self.turnover_rate = turnover_rate
        self.created_at = created_at

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'stock_code': self.stock_code,
            'time_key': self.time_key,
            'open_price': self.open_price,
            'close_price': self.close_price,
            'high_price': self.high_price,
            'low_price': self.low_price,
            'volume': self.volume,
            'turnover': self.turnover,
            'pe_ratio': self.pe_ratio,
            'turnover_rate': self.turnover_rate,
            'created_at': self.created_at
        }
