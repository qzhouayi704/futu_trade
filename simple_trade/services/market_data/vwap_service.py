#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VWAP 计算服务 - 公共接口，供 Gemini 分析师和其他功能复用"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from futu import RET_OK

logger = logging.getLogger(__name__)


@dataclass
class VWAPData:
    """VWAP 数据"""
    stock_code: str
    vwap: float                    # 成交量加权平均价
    current_price: float
    deviation_pct: float           # 当前价与VWAP偏离度
    above_vwap: bool               # 是否在VWAP上方
    cumulative_volume: int         # 累计成交量
    cumulative_turnover: float     # 累计成交额
    updated_at: datetime


class VWAPService:
    """VWAP 计算服务

    提供日内 VWAP（成交量加权平均价）计算，
    基于富途 get_rt_ticker 逐笔成交数据。
    """

    def __init__(self, futu_client):
        self._futu_client = futu_client
        self._cache: Dict[str, VWAPData] = {}
        self._cache_ttl = 60  # 60秒缓存
        self._ticker_subscribed: set = set()
        self._ticker_failed: set = set()  # 订阅失败的股票集合

    def _ensure_ticker_subscribed(self, stock_code: str):
        """确保已订阅该股票的 Ticker 数据（富途要求先订阅才能获取逐笔成交）"""
        # 跳过已订阅或已知失败的股票
        if stock_code in self._ticker_subscribed or stock_code in self._ticker_failed:
            return
        try:
            from futu import SubType, RET_OK
            client = self._futu_client.client if hasattr(self._futu_client, 'client') else self._futu_client
            if client is None:
                return
            ret, err = client.subscribe([stock_code], [SubType.TICKER])
            if ret == RET_OK:
                self._ticker_subscribed.add(stock_code)
                logger.debug(f"VWAP: 已订阅 Ticker: {stock_code}")
            else:
                # 记录失败的股票，避免重复尝试和警告
                self._ticker_failed.add(stock_code)
                logger.debug(f"VWAP: 订阅 Ticker 失败(已记录): {stock_code}, {err}")
        except Exception as e:
            self._ticker_failed.add(stock_code)
            logger.error(f"VWAP: 订阅 Ticker 异常: {stock_code}, {e}")

    async def get_vwap(self, stock_code: str, current_price: float = 0) -> Optional[VWAPData]:
        """获取单只股票的VWAP数据

        Args:
            stock_code: 股票代码
            current_price: 当前价格（用于计算偏离度）
        """
        # 检查缓存
        cached = self._cache.get(stock_code)
        if cached and (datetime.now() - cached.updated_at).total_seconds() < self._cache_ttl:
            # 更新当前价格和偏离度
            if current_price > 0 and cached.vwap > 0:
                cached.current_price = current_price
                cached.deviation_pct = (current_price - cached.vwap) / cached.vwap * 100
                cached.above_vwap = current_price > cached.vwap
            return cached

        # 从富途获取逐笔成交
        try:
            # 确保已订阅 Ticker（富途要求先订阅才能获取逐笔成交）
            self._ensure_ticker_subscribed(stock_code)

            loop = asyncio.get_event_loop()
            ret, data = await loop.run_in_executor(
                None, lambda: self._futu_client.get_rt_ticker(stock_code, num=1000)
            )

            if ret != RET_OK or data is None or data.empty:
                logger.debug(f"获取逐笔成交失败: {stock_code}")
                return None

            vwap = self.calculate_vwap_from_tickers(data)
            if vwap <= 0:
                return None

            total_volume = int(data['volume'].sum())
            total_turnover = float(data['turnover'].sum()) if 'turnover' in data.columns else 0.0

            price = current_price if current_price > 0 else float(data['price'].iloc[-1])
            deviation = (price - vwap) / vwap * 100 if vwap > 0 else 0.0

            result = VWAPData(
                stock_code=stock_code,
                vwap=round(vwap, 3),
                current_price=price,
                deviation_pct=round(deviation, 2),
                above_vwap=price > vwap,
                cumulative_volume=total_volume,
                cumulative_turnover=total_turnover,
                updated_at=datetime.now(),
            )

            self._cache[stock_code] = result
            return result

        except Exception as e:
            logger.error(f"计算VWAP异常 {stock_code}: {e}")
            return None

    async def get_vwap_batch(self, stock_codes: List[str],
                             quotes: Optional[Dict[str, float]] = None) -> Dict[str, VWAPData]:
        """批量获取VWAP数据

        Args:
            stock_codes: 股票代码列表
            quotes: 当前价格字典 {stock_code: price}
        """
        results: Dict[str, VWAPData] = {}
        tasks = []
        for code in stock_codes:
            price = quotes.get(code, 0) if quotes else 0
            tasks.append(self.get_vwap(code, price))

        vwap_results = await asyncio.gather(*tasks, return_exceptions=True)
        for code, result in zip(stock_codes, vwap_results):
            if isinstance(result, VWAPData):
                results[code] = result

        return results

    @staticmethod
    def calculate_vwap_from_tickers(tickers) -> float:
        """从逐笔成交数据计算VWAP（纯计算，可被其他服务调用）

        Args:
            tickers: DataFrame，包含 price 和 volume 列

        Returns:
            VWAP 值，失败返回 0.0
        """
        if tickers is None or tickers.empty:
            return 0.0

        total_turnover = (tickers['price'] * tickers['volume']).sum()
        total_volume = tickers['volume'].sum()
        return float(total_turnover / total_volume) if total_volume > 0 else 0.0

    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()
