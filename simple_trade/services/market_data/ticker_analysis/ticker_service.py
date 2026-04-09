#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐笔成交数据服务

获取和缓存富途 get_rt_ticker 逐笔成交数据，
供 TickerAnalyzer 等分析模块复用。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set

from futu import RET_OK, SubType

logger = logging.getLogger(__name__)


# ==================== 数据结构 ====================


@dataclass
class TickerRecord:
    """单笔成交记录"""
    time: str           # 成交时间
    price: float        # 成交价
    volume: int         # 成交量
    turnover: float     # 成交额
    direction: str      # 成交方向：BUY / SELL / NEUTRAL


@dataclass
class TickerData:
    """逐笔成交数据包"""
    stock_code: str
    records: List[TickerRecord]
    total_count: int
    updated_at: datetime = field(default_factory=datetime.now)


# ==================== 服务 ====================


class TickerService:
    """逐笔成交数据服务

    提供逐笔成交数据的获取与缓存，
    基于富途 get_rt_ticker API。
    """

    CACHE_TTL = 15  # 15秒缓存（逐笔成交数据变化快）

    def __init__(self, futu_client, state_manager=None):
        self._futu_client = futu_client
        self._state_manager = state_manager
        self._cache: Dict[str, TickerData] = {}
        self._subscribed: Set[str] = set()
        self._failed: Set[str] = set()  # 订阅失败的股票集合

    def _ensure_subscribed(self, stock_code: str) -> bool:
        """确保股票已订阅 TICKER 类型，按需订阅"""
        # 跳过已订阅或已知失败的股票
        if stock_code in self._subscribed:
            return True
        if stock_code in self._failed:
            return False
        try:
            ret, err = self._futu_client.client.subscribe(
                [stock_code], [SubType.TICKER]
            )
            if ret == RET_OK:
                self._subscribed.add(stock_code)
                logger.debug(f"订阅逐笔成交成功: {stock_code}")
                return True
            else:
                # 记录失败的股票，避免重复尝试
                self._failed.add(stock_code)
                # 额度不足时标记为特殊状态，仍可尝试获取数据
                if '额度不足' in str(err):
                    logger.debug(f"逐笔成交订阅额度不足(已记录): {stock_code}")
                    return False
                logger.debug(f"订阅逐笔成交失败(已记录): {stock_code}, {err}")
                return False
        except Exception as e:
            self._failed.add(stock_code)
            logger.error(f"订阅逐笔成交异常: {stock_code}, {e}")
            return False


    async def get_ticker_data(
        self, stock_code: str, num: int = 500
    ) -> Optional[TickerData]:
        """获取逐笔成交数据（带缓存）

        Args:
            stock_code: 股票代码，如 'HK.00700'
            num: 获取的成交笔数，最多1000笔

        Returns:
            TickerData 或 None（失败时）
        """
        # 1. 检查自身缓存
        cached = self._cache.get(stock_code)
        if cached and (datetime.now() - cached.updated_at).total_seconds() < self.CACHE_TTL:
            return cached

        # 2. 检查 TickerDataFrameCache（DataFrame 共享缓存）
        if self._state_manager is not None:
            try:
                shared_df = self._state_manager.ticker_df_cache.get(stock_code)
                if shared_df is not None:
                    result = self._parse_ticker_data(stock_code, shared_df)
                    if result:
                        self._cache[stock_code] = result
                        return result
            except Exception as e:
                logger.debug(f"读取 ticker_df_cache 失败 {stock_code}: {e}")

        # 3. 回退到原有 futu API 调用
        try:
            loop = asyncio.get_event_loop()

            # 尝试订阅（即使失败也继续尝试获取，可能已被其他服务订阅）
            await loop.run_in_executor(
                None, self._ensure_subscribed, stock_code
            )

            # 调用富途 API 获取逐笔成交
            ret, data = await loop.run_in_executor(
                None, lambda: self._futu_client.get_rt_ticker(stock_code, num=num)
            )

            if ret != RET_OK or data is None or data.empty:
                logger.debug(f"获取逐笔成交数据失败: {stock_code}")
                return None

            result = self._parse_ticker_data(stock_code, data)
            if result:
                self._cache[stock_code] = result
            return result

        except Exception as e:
            logger.error(f"获取逐笔成交数据异常 {stock_code}: {e}")
            return None


    def _parse_ticker_data(self, stock_code: str, data) -> Optional[TickerData]:
        """解析富途返回的逐笔成交 DataFrame"""
        try:
            records: List[TickerRecord] = []
            for _, row in data.iterrows():
                # 尝试多个可能的字段名（容错处理）
                direction_raw = (
                    row.get('ticker_direction') or
                    row.get('direction') or
                    row.get('side') or
                    'NEUTRAL'
                )
                # 标准化方向值
                direction = self._normalize_direction(direction_raw)

                records.append(TickerRecord(
                    time=str(row.get('time', '')),
                    price=float(row.get('price', 0)),
                    volume=int(row.get('volume', 0)),
                    turnover=float(row.get('turnover', 0)),
                    direction=direction,
                ))

            # 数据质量检查
            buy_count = sum(1 for r in records if r.direction == 'BUY')
            sell_count = sum(1 for r in records if r.direction == 'SELL')
            neutral_count = sum(1 for r in records if r.direction == 'NEUTRAL')

            if sell_count == 0 and buy_count == 0 and neutral_count > 0:
                logger.warning(
                    f"{stock_code} 所有 {neutral_count} 条逐笔记录方向都是 NEUTRAL，"
                    f"可能字段名不匹配。请检查富途API返回的字段名。"
                )

            logger.debug(
                f"{stock_code} 逐笔成交方向统计: "
                f"BUY={buy_count}, SELL={sell_count}, NEUTRAL={neutral_count}"
            )

            return TickerData(
                stock_code=stock_code,
                records=records,
                total_count=len(records),
                updated_at=datetime.now(),
            )
        except Exception as e:
            logger.error(f"解析逐笔成交数据异常 {stock_code}: {e}")
            return None

    def _normalize_direction(self, direction_raw) -> str:
        """标准化成交方向值为 BUY/SELL/NEUTRAL"""
        if not direction_raw:
            return 'NEUTRAL'

        direction_str = str(direction_raw).upper().strip()

        # 处理常见的方向值格式
        if direction_str in ('BUY', 'B', '1', 'BID'):
            return 'BUY'
        elif direction_str in ('SELL', 'S', '2', 'ASK'):
            return 'SELL'
        else:
            return 'NEUTRAL'

    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()
