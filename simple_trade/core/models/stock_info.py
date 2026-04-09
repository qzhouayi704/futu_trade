#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票标识信息模型

提供轻量级的股票标识数据类，用于解决 stock_code/stock_name/stock_id 数据泥团问题
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class StockInfo:
    """
    股票标识信息（轻量级）

    用于在系统中传递股票的基本标识信息，避免频繁传递 stock_code, stock_name, stock_id 三个参数。

    Attributes:
        code: 股票代码，如 "HK.00700"
        name: 股票名称，如 "腾讯控股"
        id: 数据库ID，可选

    Examples:
        >>> stock = StockInfo(code="HK.00700", name="腾讯控股", id=1)
        >>> print(stock)
        腾讯控股(HK.00700)
        >>> stock.code
        'HK.00700'
    """
    code: str
    name: str
    id: Optional[int] = None

    def __str__(self) -> str:
        """返回友好的字符串表示"""
        return f"{self.name}({self.code})"

    def __repr__(self) -> str:
        """返回详细的字符串表示"""
        if self.id is not None:
            return f"StockInfo(code='{self.code}', name='{self.name}', id={self.id})"
        return f"StockInfo(code='{self.code}', name='{self.name}')"

    @classmethod
    def from_stock(cls, stock) -> 'StockInfo':
        """
        从 Stock 对象创建 StockInfo

        Args:
            stock: Stock 对象（来自 stock_models.Stock）

        Returns:
            StockInfo 对象
        """
        return cls(
            code=stock.code,
            name=stock.name,
            id=stock.id
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'StockInfo':
        """
        从字典创建 StockInfo

        Args:
            data: 包含 code, name, id 的字典

        Returns:
            StockInfo 对象
        """
        return cls(
            code=data['code'],
            name=data['name'],
            id=data.get('id')
        )

    def to_dict(self) -> dict:
        """
        转换为字典

        Returns:
            包含 code, name, id 的字典
        """
        result = {
            'code': self.code,
            'name': self.name
        }
        if self.id is not None:
            result['id'] = self.id
        return result
