#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价位成交分布 - 数据结构与聚合函数

将逐笔成交数据按价格分组，统计每个价位的成交量、成交额、
主动买入量、主动卖出量等，用于前端价位分布可视化。
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import List

from .ticker_service import TickerRecord  # noqa: F401 - 后续函数需要


# ==================== 数据结构 ====================


@dataclass
class PriceLevelItem:
    """单个价位的聚合数据"""
    price: float              # 成交价格
    total_volume: int         # 成交总量
    total_turnover: float     # 成交总额
    trade_count: int          # 成交笔数
    buy_volume: int           # 主动买入量
    sell_volume: int          # 主动卖出量
    neutral_volume: int       # 中性成交量


@dataclass
class PriceLevelData:
    """价位成交分布完整数据"""
    stock_code: str                     # 股票代码
    levels: List[PriceLevelItem]        # 价位列表（按价格从高到低）
    current_price: float                # 当前最新成交价
    total_volume: int                   # 总成交量
    total_turnover: float               # 总成交额
    level_count: int                    # 价位数量


# ==================== 聚合函数 ====================


def compute_price_distribution(
    stock_code: str,
    records: List[TickerRecord],
    max_levels: int = 30,
) -> PriceLevelData:
    """计算价位成交分布

    将逐笔成交记录按价格分组聚合，返回价位分布数据。

    Args:
        stock_code: 股票代码
        records: 逐笔成交记录列表
        max_levels: 最大价位数量，超过时取成交量 Top N 后按价格重新排序

    Returns:
        PriceLevelData 价位分布数据
    """
    # 空记录：返回零值
    if not records:
        return PriceLevelData(
            stock_code=stock_code,
            levels=[],
            current_price=0.0,
            total_volume=0,
            total_turnover=0.0,
            level_count=0,
        )

    # 按价格分组聚合
    groups: dict = defaultdict(lambda: {
        "total_volume": 0,
        "total_turnover": 0.0,
        "trade_count": 0,
        "buy_volume": 0,
        "sell_volume": 0,
        "neutral_volume": 0,
    })

    for r in records:
        g = groups[r.price]
        g["total_volume"] += r.volume
        g["total_turnover"] += r.turnover
        g["trade_count"] += 1
        if r.direction == "BUY":
            g["buy_volume"] += r.volume
        elif r.direction == "SELL":
            g["sell_volume"] += r.volume
        else:
            g["neutral_volume"] += r.volume

    # 构建价位列表，按价格从高到低排序
    levels = [
        PriceLevelItem(
            price=price,
            total_volume=g["total_volume"],
            total_turnover=g["total_turnover"],
            trade_count=g["trade_count"],
            buy_volume=g["buy_volume"],
            sell_volume=g["sell_volume"],
            neutral_volume=g["neutral_volume"],
        )
        for price, g in groups.items()
    ]
    levels.sort(key=lambda x: x.price, reverse=True)

    # 若价位数超过 max_levels，取成交量 Top max_levels 后按价格重新排序
    if len(levels) > max_levels:
        levels.sort(key=lambda x: x.total_volume, reverse=True)
        levels = levels[:max_levels]
        levels.sort(key=lambda x: x.price, reverse=True)

    total_volume = sum(lv.total_volume for lv in levels)
    total_turnover = sum(lv.total_turnover for lv in levels)

    return PriceLevelData(
        stock_code=stock_code,
        levels=levels,
        current_price=records[-1].price,
        total_volume=total_volume,
        total_turnover=total_turnover,
        level_count=len(levels),
    )
