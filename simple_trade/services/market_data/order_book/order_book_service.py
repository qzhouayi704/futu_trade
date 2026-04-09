#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘口数据服务 - 公共接口，获取买卖一到十档挂单情况"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set

from futu import RET_OK, SubType

logger = logging.getLogger(__name__)


@dataclass
class OrderBookLevel:
    """盘口单档数据"""
    price: float
    volume: int
    order_count: int = 0          # 挂单笔数（如有）


@dataclass
class OrderBookData:
    """盘口完整数据"""
    stock_code: str
    bid_levels: List[OrderBookLevel] = field(default_factory=list)  # 买盘1-10档
    ask_levels: List[OrderBookLevel] = field(default_factory=list)  # 卖盘1-10档
    bid_total_volume: int = 0     # 买盘总量
    ask_total_volume: int = 0     # 卖盘总量
    imbalance: float = 0.0        # 买卖失衡度 (-1到1)
    spread: float = 0.0           # 买卖价差
    spread_pct: float = 0.0       # 价差百分比
    updated_at: datetime = field(default_factory=datetime.now)


class OrderBookService:
    """盘口数据服务

    提供买卖一到十档挂单数据，
    基于富途 get_order_book API。
    """

    def __init__(self, futu_client):
        self._futu_client = futu_client
        self._cache: Dict[str, OrderBookData] = {}
        self._cache_ttl = 30  # 30秒缓存（盘口变化快）
        self._subscribed: Set[str] = set()  # 已订阅 ORDER_BOOK 的股票

    def _ensure_subscribed(self, stock_code: str) -> bool:
        """确保股票已订阅 ORDER_BOOK 类型，按需订阅"""
        if stock_code in self._subscribed:
            return True
        try:
            ret, err = self._futu_client.client.subscribe(
                [stock_code], [SubType.ORDER_BOOK]
            )
            if ret == RET_OK:
                self._subscribed.add(stock_code)
                logger.debug(f"订阅盘口成功: {stock_code}")
                return True
            else:
                # 额度不足时标记为特殊状态，仍可尝试获取数据
                if '额度不足' in str(err):
                    logger.info(f"盘口订阅额度不足: {stock_code}，将尝试直接获取数据")
                    return False
                logger.warning(f"订阅盘口失败: {stock_code}, {err}")
                return False
        except Exception as e:
            logger.error(f"订阅盘口异常: {stock_code}, {e}")
            return False


    async def get_order_book(self, stock_code: str) -> Optional[OrderBookData]:
        """获取单只股票的盘口数据"""
        # 检查缓存
        cached = self._cache.get(stock_code)
        if cached and (datetime.now() - cached.updated_at).total_seconds() < self._cache_ttl:
            return cached

        try:
            loop = asyncio.get_event_loop()

            # 尝试订阅（即使失败也继续尝试获取，可能已被其他服务订阅）
            await loop.run_in_executor(
                None, self._ensure_subscribed, stock_code
            )

            ret, data = await loop.run_in_executor(
                None, lambda: self._futu_client.get_order_book(stock_code)
            )

            if ret != RET_OK or data is None:
                logger.debug(f"获取盘口数据失败: {stock_code}")
                return None

            result = self._parse_order_book(stock_code, data)
            if result:
                self._cache[stock_code] = result
            return result

        except Exception as e:
            logger.error(f"获取盘口数据异常 {stock_code}: {e}")
            return None


    async def get_order_book_batch(
        self, stock_codes: List[str]
    ) -> Dict[str, OrderBookData]:
        """批量获取盘口数据"""
        results: Dict[str, OrderBookData] = {}
        tasks = [self.get_order_book(code) for code in stock_codes]
        order_books = await asyncio.gather(*tasks, return_exceptions=True)

        for code, result in zip(stock_codes, order_books):
            if isinstance(result, OrderBookData):
                results[code] = result

        return results

    def _parse_order_book(self, stock_code: str, data) -> Optional[OrderBookData]:
        """解析富途返回的盘口数据"""
        try:
            bid_levels: List[OrderBookLevel] = []
            ask_levels: List[OrderBookLevel] = []

            # 富途 get_order_book 返回 dict 格式:
            # {'Bid': [(price, volume, order_count, order_details), ...],
            #  'Ask': [(price, volume, order_count, order_details), ...]}
            if isinstance(data, dict):
                for item in data.get('Bid', [])[:10]:
                    price, volume = float(item[0]), int(item[1])
                    count = int(item[2]) if len(item) > 2 and item[2] else 0
                    if price > 0:
                        bid_levels.append(OrderBookLevel(
                            price=price, volume=volume, order_count=count,
                        ))
                for item in data.get('Ask', [])[:10]:
                    price, volume = float(item[0]), int(item[1])
                    count = int(item[2]) if len(item) > 2 and item[2] else 0
                    if price > 0:
                        ask_levels.append(OrderBookLevel(
                            price=price, volume=volume, order_count=count,
                        ))

            bid_total = sum(l.volume for l in bid_levels)
            ask_total = sum(l.volume for l in ask_levels)
            imbalance = self.calculate_imbalance(bid_total, ask_total)

            spread = 0.0
            spread_pct = 0.0
            if ask_levels and bid_levels:
                spread = ask_levels[0].price - bid_levels[0].price
                mid_price = (ask_levels[0].price + bid_levels[0].price) / 2
                spread_pct = (spread / mid_price * 100) if mid_price > 0 else 0.0

            return OrderBookData(
                stock_code=stock_code,
                bid_levels=bid_levels,
                ask_levels=ask_levels,
                bid_total_volume=bid_total,
                ask_total_volume=ask_total,
                imbalance=round(imbalance, 3),
                spread=round(spread, 3),
                spread_pct=round(spread_pct, 4),
                updated_at=datetime.now(),
            )

        except Exception as e:
            logger.error(f"解析盘口数据异常 {stock_code}: {e}")
            return None

    @staticmethod
    def calculate_imbalance(bid_total: int, ask_total: int) -> float:
        """计算买卖失衡度

        公式: (买盘总量 - 卖盘总量) / (买盘总量 + 卖盘总量)
        返回: -1（极度卖压）到 1（极度买压）
        """
        total = bid_total + ask_total
        if total == 0:
            return 0.0
        return (bid_total - ask_total) / total

    def get_support_resistance(self, order_book: OrderBookData) -> Dict:
        """从盘口识别支撑位和阻力位（大单挂单位置）"""
        support = None
        resistance = None

        # 找买盘中最大挂单量的档位作为支撑
        if order_book.bid_levels:
            max_bid = max(order_book.bid_levels, key=lambda l: l.volume)
            support = {'price': max_bid.price, 'volume': max_bid.volume}

        # 找卖盘中最大挂单量的档位作为阻力
        if order_book.ask_levels:
            max_ask = max(order_book.ask_levels, key=lambda l: l.volume)
            resistance = {'price': max_ask.price, 'volume': max_ask.volume}

        return {'support': support, 'resistance': resistance}

    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()
