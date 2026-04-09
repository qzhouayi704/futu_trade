#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
强类型数据模型定义（向后兼容层）

使用 dataclass 替代硬编码索引访问,提供:
1. 更好的代码可读性
2. IDE 自动补全支持
3. 类型检查
4. 防止索引错位

注意：此文件已重构为向后兼容层，实际实现已拆分到 models/ 子目录
"""

# 从子模块导入所有类和函数，保持向后兼容
from .models import (
    Plate,
    Stock,
    StockWithPlate,
    KlineData,
    TradeSignal,
    Quote,
    TradingCondition,
    IndexInfo,
    stocks_to_dict_list,
    plates_to_dict_list,
    klines_to_dict_list,
    signals_to_dict_list,
    quotes_to_dict_list,
)

__all__ = [
    'Plate',
    'Stock',
    'StockWithPlate',
    'KlineData',
    'TradeSignal',
    'Quote',
    'TradingCondition',
    'IndexInfo',
    'stocks_to_dict_list',
    'plates_to_dict_list',
    'klines_to_dict_list',
    'signals_to_dict_list',
    'quotes_to_dict_list',
]
