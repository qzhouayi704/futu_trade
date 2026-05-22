#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日内资金支撑/阻力位计算服务

融合三个维度识别日内关键价位：
1. 成交量聚集 (Volume Profile) → POC
2. 大单价位聚集 → 主力买入/卖出密集区
3. 盘口挂单墙 → 短期支撑/阻力
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PriceLevel:
    """单个价位"""
    price: float
    strength: int           # 0-100 强度评分
    type: str               # volume_poc / big_order_buy / big_order_sell / order_book_bid / order_book_ask
    label: str              # 中文标签
    volume: int = 0         # 关联成交量/挂单量
    turnover: float = 0.0   # 关联成交额
    reliability: str = "confirmed"  # "confirmed" | "order_book_only" — 价位可信度


@dataclass
class IntradayLevelsResult:
    """日内支撑/阻力位计算结果"""
    stock_code: str
    support_levels: List[PriceLevel] = field(default_factory=list)
    resistance_levels: List[PriceLevel] = field(default_factory=list)
    poc: Optional[Dict] = None           # {"price": x, "volume": y}
    vwap: Optional[Dict] = None          # {"price": x, "deviation_pct": y}
    current_price: float = 0.0
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "support_levels": [
                {"price": l.price, "strength": l.strength, "type": l.type,
                 "label": l.label, "volume": l.volume, "reliability": l.reliability}
                for l in self.support_levels
            ],
            "resistance_levels": [
                {"price": l.price, "strength": l.strength, "type": l.type,
                 "label": l.label, "volume": l.volume, "reliability": l.reliability}
                for l in self.resistance_levels
            ],
            "poc": self.poc,
            "vwap": self.vwap,
            "current_price": self.current_price,
            "updated_at": self.updated_at.isoformat(),
        }


class IntradayLevelsService:
    """日内资金支撑/阻力位计算服务"""

    # 大单阈值（成交额，港元）
    DEFAULT_BIG_ORDER_THRESHOLD = 100_000
    # 相近价位合并阈值（百分比）
    MERGE_THRESHOLD_PCT = 0.005  # ±0.5%

    def __init__(self, ticker_service, order_book_service, vwap_service=None):
        self._ticker_service = ticker_service
        self._order_book_service = order_book_service
        self._vwap_service = vwap_service

    async def get_levels(self, stock_code: str) -> IntradayLevelsResult:
        """计算日内支撑/阻力位

        Args:
            stock_code: 股票代码

        Returns:
            IntradayLevelsResult
        """
        result = IntradayLevelsResult(stock_code=stock_code)
        candidates_support = []
        candidates_resistance = []

        # ① 成交量聚集 (Volume Profile) + 大单聚集
        ticker_data = await self._ticker_service.get_ticker_data(stock_code, num=1000)
        if ticker_data and ticker_data.records:
            records = ticker_data.records
            result.current_price = records[-1].price

            # Volume Profile: 按价位聚合成交量
            volume_profile = self._calc_volume_profile(records)
            poc_level = self._find_poc(volume_profile, result.current_price)
            if poc_level:
                result.poc = {"price": poc_level.price, "volume": poc_level.volume}
                if poc_level.price < result.current_price:
                    candidates_support.append(poc_level)
                else:
                    candidates_resistance.append(poc_level)

            # 大单价位聚集
            big_order_levels = self._calc_big_order_levels(records, result.current_price)
            for level in big_order_levels:
                if level.type == "big_order_buy":
                    candidates_support.append(level)
                else:
                    candidates_resistance.append(level)

            # VWAP
            vwap = self._calc_vwap(records)
            if vwap > 0:
                deviation = (result.current_price - vwap) / vwap * 100 if vwap > 0 else 0
                result.vwap = {"price": round(vwap, 3), "deviation_pct": round(deviation, 2)}

        # ② 盘口挂单墙 — 仅用于补充当前价，不纳入支撑/阻力位
        # 挂单随时可撤销，变动频繁，不可作为判断依据
        order_book = await self._order_book_service.get_order_book(stock_code)
        if order_book:
            if result.current_price == 0 and order_book.bid_levels:
                result.current_price = order_book.bid_levels[0].price

        # ③ 合并去重 + 排序
        result.support_levels = self._merge_and_rank(
            candidates_support, result.current_price, top_n=3
        )
        result.resistance_levels = self._merge_and_rank(
            candidates_resistance, result.current_price, top_n=3
        )

        return result

    # ==================== 维度 1: Volume Profile ====================

    def _calc_volume_profile(self, records) -> Dict[float, Dict]:
        """按价位聚合成交量"""
        profile = defaultdict(lambda: {
            "total_volume": 0, "buy_volume": 0, "sell_volume": 0,
            "turnover": 0.0, "trade_count": 0,
        })
        for r in records:
            p = profile[r.price]
            p["total_volume"] += r.volume
            p["turnover"] += r.turnover
            p["trade_count"] += 1
            if r.direction == "BUY":
                p["buy_volume"] += r.volume
            elif r.direction == "SELL":
                p["sell_volume"] += r.volume
        return dict(profile)

    def _find_poc(self, volume_profile: Dict, current_price: float) -> Optional[PriceLevel]:
        """找到 Point of Control（成交量最大的价位）"""
        if not volume_profile:
            return None

        poc_price = max(volume_profile, key=lambda p: volume_profile[p]["total_volume"])
        poc_data = volume_profile[poc_price]
        total_vol = sum(v["total_volume"] for v in volume_profile.values())
        # POC 成交量占总成交量的比例越高，强度越高
        ratio = poc_data["total_volume"] / total_vol if total_vol > 0 else 0
        strength = min(int(ratio * 500), 100)  # 20%以上满分

        return PriceLevel(
            price=poc_price,
            strength=max(strength, 40),  # 最低40分（POC 本身有意义）
            type="volume_poc",
            label="成交密集区",
            volume=poc_data["total_volume"],
            turnover=poc_data["turnover"],
        )

    # ==================== 维度 2: 大单价位聚集 ====================

    def _calc_big_order_levels(self, records, current_price: float) -> List[PriceLevel]:
        """识别大单聚集价位"""
        # 计算大单阈值（使用成交额中位数的 3 倍）
        turnovers = [r.turnover for r in records if r.turnover > 0]
        if not turnovers:
            return []
        median_turnover = sorted(turnovers)[len(turnovers) // 2]
        threshold = max(median_turnover * 3, self.DEFAULT_BIG_ORDER_THRESHOLD)

        # 筛选大单并按价位聚合
        big_by_price = defaultdict(lambda: {"buy_vol": 0, "sell_vol": 0, "buy_amt": 0.0, "sell_amt": 0.0, "count": 0})
        for r in records:
            if r.turnover >= threshold:
                p = big_by_price[r.price]
                p["count"] += 1
                if r.direction == "BUY":
                    p["buy_vol"] += r.volume
                    p["buy_amt"] += r.turnover
                elif r.direction == "SELL":
                    p["sell_vol"] += r.volume
                    p["sell_amt"] += r.turnover

        if not big_by_price:
            return []

        # 找大单买入聚集区（支撑）和卖出聚集区（阻力）
        levels = []
        max_count = max(v["count"] for v in big_by_price.values())

        for price, data in big_by_price.items():
            if data["count"] < 2:  # 至少2笔大单才有意义
                continue

            strength = min(int(data["count"] / max(max_count, 1) * 80) + 20, 100)
            net = data["buy_vol"] - data["sell_vol"]

            if net > 0 and price <= current_price:
                levels.append(PriceLevel(
                    price=price,
                    strength=strength,
                    type="big_order_buy",
                    label="大单买入区",
                    volume=data["buy_vol"],
                    turnover=data["buy_amt"],
                ))
            elif net < 0 and price >= current_price:
                levels.append(PriceLevel(
                    price=price,
                    strength=strength,
                    type="big_order_sell",
                    label="大单卖出区",
                    volume=data["sell_vol"],
                    turnover=data["sell_amt"],
                ))

        return levels

    # ==================== 维度 3: 盘口挂单墙 ====================

    def _calc_order_book_walls(self, order_book, current_price: float) -> List[PriceLevel]:
        """识别盘口中的异常大挂单（挂单墙）"""
        levels = []

        # 买盘挂单墙（支撑）
        if order_book.bid_levels:
            avg_bid_vol = sum(l.volume for l in order_book.bid_levels) / len(order_book.bid_levels)
            for level in order_book.bid_levels:
                if avg_bid_vol > 0 and level.volume >= avg_bid_vol * 2:
                    ratio = level.volume / avg_bid_vol
                    strength = min(int(ratio * 25), 100)
                    levels.append(PriceLevel(
                        price=level.price,
                        strength=strength,
                        type="order_book_bid",
                        label="买盘挂单墙",
                        volume=level.volume,
                        reliability="order_book_only",
                    ))

        # 卖盘挂单墙（阻力）
        if order_book.ask_levels:
            avg_ask_vol = sum(l.volume for l in order_book.ask_levels) / len(order_book.ask_levels)
            for level in order_book.ask_levels:
                if avg_ask_vol > 0 and level.volume >= avg_ask_vol * 2:
                    ratio = level.volume / avg_ask_vol
                    strength = min(int(ratio * 25), 100)
                    levels.append(PriceLevel(
                        price=level.price,
                        strength=strength,
                        type="order_book_ask",
                        label="卖盘挂单墙",
                        volume=level.volume,
                        reliability="order_book_only",
                    ))

        return levels

    # ==================== VWAP 计算 ====================

    @staticmethod
    def _calc_vwap(records) -> float:
        """从逐笔成交计算 VWAP"""
        total_turnover = sum(r.price * r.volume for r in records)
        total_volume = sum(r.volume for r in records)
        return total_turnover / total_volume if total_volume > 0 else 0.0

    # ==================== 合并去重 ====================

    def _merge_and_rank(self, candidates: List[PriceLevel],
                        current_price: float, top_n: int = 3) -> List[PriceLevel]:
        """合并相近价位，按强度排序取 Top N"""
        if not candidates:
            return []

        # 按价格排序
        sorted_levels = sorted(candidates, key=lambda l: l.price)

        # 合并相近价位（±0.5%）
        merged = []
        for level in sorted_levels:
            found_merge = False
            for existing in merged:
                if current_price > 0:
                    diff_pct = abs(level.price - existing.price) / current_price
                    if diff_pct <= self.MERGE_THRESHOLD_PCT:
                        # 合并：取强度更高的，叠加 volume
                        if level.strength > existing.strength:
                            existing.price = level.price
                            existing.type = level.type
                            existing.label = level.label
                        existing.strength = min(existing.strength + level.strength // 3, 100)
                        existing.volume += level.volume
                        found_merge = True
                        break
            if not found_merge:
                merged.append(PriceLevel(
                    price=level.price,
                    strength=level.strength,
                    type=level.type,
                    label=level.label,
                    volume=level.volume,
                    turnover=level.turnover,
                ))

        # 按强度排序，取 Top N
        merged.sort(key=lambda l: l.strength, reverse=True)
        return merged[:top_n]

    @staticmethod
    def get_nearest_strong_support(result: IntradayLevelsResult, current_price: float, min_strength: int = 80) -> Optional[PriceLevel]:
        """寻找距离现价最近的强支撑位"""
        strong_supports = [l for l in result.support_levels if l.strength >= min_strength and l.price < current_price]
        if not strong_supports:
            return None
        strong_supports.sort(key=lambda x: x.price, reverse=True)
        return strong_supports[0]

    @staticmethod
    def get_nearest_strong_resistance(result: IntradayLevelsResult, current_price: float, min_strength: int = 80) -> Optional[PriceLevel]:
        """寻找距离现价最近的强阻力位"""
        strong_resistances = [l for l in result.resistance_levels if l.strength >= min_strength and l.price > current_price]
        if not strong_resistances:
            return None
        strong_resistances.sort(key=lambda x: x.price)
        return strong_resistances[0]
