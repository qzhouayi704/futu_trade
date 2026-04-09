"""
Scalping 数据转换工具

将 futu API 返回的原始数据转换为 ScalpingEngine 使用的 TickData/OrderBookData 模型。
从 ScalpingDataPoller 提取的纯函数，供 CentralScheduler 和 DataPoller 共用。
"""

import logging
import time
from typing import Optional

from simple_trade.services.scalping.models import (
    OrderBookData,
    OrderBookLevel,
    TickData,
    TickDirection,
)

logger = logging.getLogger("scalping.converter")

# 方向映射
_DIRECTION_MAP = {
    "BUY": TickDirection.BUY,
    "SELL": TickDirection.SELL,
    "NEUTRAL": TickDirection.NEUTRAL,
}


def row_to_tick(stock_code: str, row) -> Optional[TickData]:
    """将 futu Ticker DataFrame 行转换为 TickData

    Args:
        stock_code: 股票代码
        row: DataFrame 行（包含 price, volume, ticker_direction, time 等字段）

    Returns:
        TickData 或 None（转换失败时）
    """
    try:
        direction_str = str(row.get("ticker_direction", "NEUTRAL")).upper()
        direction = _DIRECTION_MAP.get(direction_str, TickDirection.NEUTRAL)
        price = float(row["price"])
        return TickData(
            stock_code=stock_code,
            price=price,
            volume=int(row["volume"]),
            direction=direction,
            timestamp=parse_time_to_ms(row.get("time", "")),
            ask_price=price,
            bid_price=price,
        )
    except Exception as e:
        logger.debug(f"[{stock_code}] 转换 Tick 失败: {e}")
        return None


def dict_to_order_book(stock_code: str, data: dict) -> Optional[OrderBookData]:
    """将 futu get_order_book 返回的 dict 转换为 OrderBookData

    Args:
        stock_code: 股票代码
        data: futu 返回的字典，格式 {'Ask': [...], 'Bid': [...]}

    Returns:
        OrderBookData 或 None（转换失败时）
    """
    try:
        ask_levels = _parse_levels(data, "Ask")
        bid_levels = _parse_levels(data, "Bid")
        return OrderBookData(
            stock_code=stock_code,
            ask_levels=ask_levels,
            bid_levels=bid_levels,
            timestamp=time.time() * 1000,
        )
    except Exception as e:
        logger.debug(f"[{stock_code}] 转换 OrderBook 失败: {e}")
        return None


def _parse_levels(data: dict, side: str) -> list[OrderBookLevel]:
    """解析盘口档位

    futu get_order_book 返回格式:
    {'Ask': [(price, volume, order_count), ...], 'Bid': [...]}
    """
    raw = data.get(side, [])
    levels: list[OrderBookLevel] = []
    for item in raw[:10]:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            levels.append(
                OrderBookLevel(
                    price=float(item[0]),
                    volume=int(item[1]),
                    order_count=int(item[2]) if len(item) > 2 else 0,
                )
            )
    return levels


def parse_time_to_ms(time_str) -> float:
    """将 futu 返回的时间字符串转为毫秒时间戳

    futu 格式: '2026-02-26 10:30:00.123'
    """
    if not time_str:
        return time.time() * 1000
    try:
        from datetime import datetime
        try:
            dt = datetime.strptime(str(time_str), "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            dt = datetime.strptime(str(time_str), "%Y-%m-%d %H:%M:%S")
        return dt.timestamp() * 1000
    except Exception:
        return time.time() * 1000
