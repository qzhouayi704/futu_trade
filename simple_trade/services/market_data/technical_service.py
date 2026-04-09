#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技术指标聚合服务 - 整合 VWAP、盘口、资金流向等指标"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TechnicalIndicators:
    """技术指标数据包"""
    stock_code: str
    # 价格指标
    current_price: float = 0.0
    change_pct: float = 0.0
    vwap: float = 0.0
    vwap_deviation: float = 0.0
    # 均线位置
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    price_vs_ma5: str = "AT"      # "ABOVE" / "BELOW" / "AT"
    price_vs_ma10: str = "AT"
    price_vs_ma20: str = "AT"
    trend: str = "SIDEWAYS"       # "UP" / "DOWN" / "SIDEWAYS"
    # 动量指标
    rsi_14: float = 50.0
    rsi_signal: str = "NEUTRAL"   # "OVERBOUGHT" / "OVERSOLD" / "NEUTRAL"
    volume_ratio: float = 1.0
    turnover_rate: float = 0.0
    # 资金指标
    capital_score: float = 50.0
    main_net_inflow: float = 0.0
    big_order_strength: float = 0.0
    # 盘口指标
    order_imbalance: float = 0.0
    spread_pct: float = 0.0
    # 形态结论
    pattern_summary: str = ""
    updated_at: datetime = field(default_factory=datetime.now)


class TechnicalService:
    """技术指标聚合服务

    整合 VWAP、盘口、资金流向、大单追踪等数据，
    提供统一的技术指标数据包。
    """

    def __init__(
        self,
        vwap_service=None,
        order_book_service=None,
        capital_flow_analyzer=None,
        big_order_tracker=None,
    ):
        self._vwap = vwap_service
        self._order_book = order_book_service
        self._capital = capital_flow_analyzer
        self._big_order = big_order_tracker

    async def get_indicators(
        self,
        stock_code: str,
        quote: Dict[str, Any],
        klines: List,
    ) -> TechnicalIndicators:
        """获取完整的技术指标数据包"""
        current_price = quote.get('last_price', 0) or quote.get('price', 0)
        change_pct = quote.get('change_rate', 0) or quote.get('change_pct', 0)
        turnover_rate = quote.get('turnover_rate', 0)

        # 并行获取各项数据
        vwap_data, order_book, capital_data, big_order_data = await asyncio.gather(
            self._safe_get_vwap(stock_code, current_price),
            self._safe_get_order_book(stock_code),
            self._safe_get_capital(stock_code),
            self._safe_get_big_order(stock_code),
        )

        # 计算均线
        ma5, ma10, ma20 = self._calculate_mas(klines)

        # 计算 RSI
        rsi = self._calculate_rsi(klines)
        rsi_signal = "OVERBOUGHT" if rsi > 70 else ("OVERSOLD" if rsi < 30 else "NEUTRAL")

        # 判断趋势
        trend = self._determine_trend(ma5, ma10, ma20)

        # 量比
        volume_ratio = self._calculate_volume_ratio(klines, quote)

        # VWAP 数据
        vwap = vwap_data.vwap if vwap_data else 0.0
        vwap_deviation = vwap_data.deviation_pct if vwap_data else 0.0

        # 盘口数据
        order_imbalance = order_book.imbalance if order_book else 0.0
        spread_pct = order_book.spread_pct if order_book else 0.0

        # 资金数据
        capital_score = capital_data.get('score', 50.0) if capital_data else 50.0
        main_net_inflow = capital_data.get('main_net_inflow', 0) if capital_data else 0.0

        # 大单数据
        big_order_strength = big_order_data.get('strength', 0) if big_order_data else 0.0

        # 生成形态结论
        pattern_summary = self._generate_pattern_summary(
            change_pct, vwap, vwap_deviation, rsi, volume_ratio, trend
        )

        return TechnicalIndicators(
            stock_code=stock_code,
            current_price=current_price,
            change_pct=change_pct,
            vwap=vwap,
            vwap_deviation=vwap_deviation,
            ma5=ma5, ma10=ma10, ma20=ma20,
            price_vs_ma5=self._price_vs_ma(current_price, ma5),
            price_vs_ma10=self._price_vs_ma(current_price, ma10),
            price_vs_ma20=self._price_vs_ma(current_price, ma20),
            trend=trend,
            rsi_14=round(rsi, 1),
            rsi_signal=rsi_signal,
            volume_ratio=round(volume_ratio, 2),
            turnover_rate=turnover_rate,
            capital_score=capital_score,
            main_net_inflow=main_net_inflow,
            big_order_strength=big_order_strength,
            order_imbalance=order_imbalance,
            spread_pct=spread_pct,
            pattern_summary=pattern_summary,
            updated_at=datetime.now(),
        )

    # --- 安全获取方法（任一失败不影响整体） ---

    async def _safe_get_vwap(self, stock_code: str, price: float):
        try:
            if self._vwap:
                return await self._vwap.get_vwap(stock_code, price)
        except Exception as e:
            logger.warning(f"获取VWAP失败 {stock_code}: {e}")
        return None

    async def _safe_get_order_book(self, stock_code: str):
        try:
            if self._order_book:
                return await self._order_book.get_order_book(stock_code)
        except Exception as e:
            logger.warning(f"获取盘口失败 {stock_code}: {e}")
        return None

    async def _safe_get_capital(self, stock_code: str) -> Optional[Dict]:
        try:
            if self._capital:
                result = await self._capital.fetch_capital_flow_data([stock_code])
                return result.get(stock_code) if result else None
        except Exception as e:
            logger.warning(f"获取资金流向失败 {stock_code}: {e}")
        return None

    async def _safe_get_big_order(self, stock_code: str) -> Optional[Dict]:
        try:
            if self._big_order:
                result = await self._big_order.track_rt_tickers([stock_code])
                return result.get(stock_code) if result else None
        except Exception as e:
            logger.warning(f"获取大单数据失败 {stock_code}: {e}")
        return None

    # --- 计算方法 ---

    @staticmethod
    def _calculate_mas(klines: List) -> tuple:
        """计算 MA5, MA10, MA20"""
        if not klines or len(klines) < 5:
            return 0.0, 0.0, 0.0

        closes = [k.get('close', 0) if isinstance(k, dict) else getattr(k, 'close', 0)
                   for k in klines]

        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else 0.0
        ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else 0.0
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else 0.0

        return round(ma5, 3), round(ma10, 3), round(ma20, 3)

    @staticmethod
    def _calculate_rsi(klines: List, period: int = 14) -> float:
        """计算 RSI 指标"""
        if not klines or len(klines) < period + 1:
            return 50.0

        closes = [k.get('close', 0) if isinstance(k, dict) else getattr(k, 'close', 0)
                   for k in klines]

        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))

        if len(gains) < period:
            return 50.0

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 1)

    @staticmethod
    def _determine_trend(ma5: float, ma10: float, ma20: float) -> str:
        """判断趋势方向"""
        if ma5 <= 0 or ma10 <= 0:
            return "SIDEWAYS"
        if ma5 > ma10 > ma20 > 0:
            return "UP"
        if ma5 < ma10 < ma20 and ma20 > 0:
            return "DOWN"
        return "SIDEWAYS"

    @staticmethod
    def _price_vs_ma(price: float, ma: float) -> str:
        """判断价格相对均线位置"""
        if ma <= 0 or price <= 0:
            return "AT"
        pct = (price - ma) / ma * 100
        if pct > 0.5:
            return "ABOVE"
        elif pct < -0.5:
            return "BELOW"
        return "AT"

    @staticmethod
    def _calculate_volume_ratio(klines: List, quote: Dict) -> float:
        """计算量比"""
        if not klines or len(klines) < 5:
            return 1.0

        volumes = [k.get('volume', 0) if isinstance(k, dict) else getattr(k, 'volume', 0)
                    for k in klines[-5:]]
        avg_vol = sum(volumes) / len(volumes) if volumes else 0
        current_vol = quote.get('volume', 0)

        if avg_vol <= 0:
            return 1.0
        return current_vol / avg_vol

    @staticmethod
    def _generate_pattern_summary(
        change_pct: float, vwap: float, vwap_dev: float,
        rsi: float, vol_ratio: float, trend: str,
    ) -> str:
        """生成一句话技术形态结论"""
        parts = []

        # 量价关系
        if vol_ratio > 1.5 and change_pct > 0:
            parts.append("放量上涨")
        elif vol_ratio > 1.5 and change_pct < 0:
            parts.append("放量下跌")
        elif vol_ratio < 0.5:
            parts.append("缩量整理")

        # VWAP 位置
        if vwap > 0:
            if vwap_dev < -1.5:
                parts.append("跌破VWAP")
            elif vwap_dev > 1.5:
                parts.append("站上VWAP")

        # RSI 状态
        if rsi > 70:
            parts.append("RSI超买")
        elif rsi < 30:
            parts.append("RSI超卖")

        # 趋势
        if trend == "UP":
            parts.append("多头排列")
        elif trend == "DOWN":
            parts.append("空头排列")

        return "，".join(parts) if parts else "震荡整理"
