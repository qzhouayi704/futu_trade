#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
龙头股识别器

从热门股票中识别板块领涨核心，每板块返回 1-2 只。
严格条件：涨幅 top 1-2、量比 > 2.0、市值达标、连续强势。
"""

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from simple_trade.services.analysis.heat.heat_score_engine import HeatScoreEngine
from simple_trade.services.market_data.hot_stock.hot_stock_filter import HotStockItem


logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_CONFIG = {
    "min_volume_ratio": 2.0,       # 龙头股量比下限
    "max_per_plate": 2,            # 每板块最多龙头数
    "candidate_multiplier": 2,     # 候选倍数（取 top max_per_plate * multiplier）
    "kline_lookback_days": 20,     # 价格位置回看天数
    "strong_day_lookback": 5,      # 连续强势回看天数
}


@dataclass
class LeaderStockItem:
    """龙头股数据项"""

    stock_code: str
    stock_name: str
    market: str
    plate_code: str
    plate_name: str
    last_price: float
    change_pct: float
    volume: int
    volume_ratio: float
    turnover_rate: float
    price_position: float       # 价格位置 (0-100)，-1 表示不可用
    heat_score: float
    leader_score: float         # 龙头评分
    leader_rank: int
    consecutive_strong_days: int
    market_cap: float           # 市值

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，确保 price_position 为有效值"""
        d = asdict(self)
        # 修复 price_position：无效值用 50.0 替代，消除前端 NaN
        if d["price_position"] is None or d["price_position"] < 0:
            d["price_position"] = 50.0
        return d


class LeaderStockIdentifier:
    """龙头股识别器：每板块 1-2 只领涨核心"""

    # 市值下限：港股 5 亿港元，美股 5000 万美元
    MIN_MARKET_CAP = {"HK": 500_000_000, "US": 50_000_000}

    def __init__(
        self,
        score_engine: HeatScoreEngine,
        kline_service=None,
        config: dict = None,
    ):
        self.score_engine = score_engine
        self.kline_service = kline_service
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.min_volume_ratio = cfg["min_volume_ratio"]
        self.default_max_per_plate = cfg["max_per_plate"]
        self.candidate_multiplier = cfg["candidate_multiplier"]
        self.kline_lookback_days = cfg["kline_lookback_days"]
        self.strong_day_lookback = cfg["strong_day_lookback"]
        self.logger = logging.getLogger(__name__)

    def identify_leaders(
        self,
        hot_stocks: List[HotStockItem],
        plate_code: str,
        plate_name: str,
        kline_data: Optional[Dict[str, List[Dict]]] = None,
        quotes_map: Optional[Dict[str, Dict]] = None,
        max_per_plate: int = 2,
    ) -> List[LeaderStockItem]:
        """从热门股票中识别龙头，无满足条件时返回空列表"""
        if not hot_stocks:
            return []

        kline_data = kline_data or {}
        quotes_map = quotes_map or {}

        # 1. 市值过滤
        cap_filtered = []
        for stock in hot_stocks:
            quote = quotes_map.get(stock.stock_code, {})
            if self._check_market_cap(stock.stock_code, quote):
                cap_filtered.append(stock)

        if not cap_filtered:
            return []

        # 2. 按涨幅降序排序，取候选
        cap_filtered.sort(key=lambda x: x.change_pct, reverse=True)
        candidate_count = max_per_plate * self.candidate_multiplier
        candidates = cap_filtered[:candidate_count]

        # 3. 量比 > 2.0 过滤
        volume_filtered = [
            s for s in candidates if s.volume_ratio > self.min_volume_ratio
        ]

        if not volume_filtered:
            return []

        # 4 & 5. 计算附加指标并评分
        plate_size = len(hot_stocks)
        scored_items: List[LeaderStockItem] = []

        for rank_idx, stock in enumerate(volume_filtered, start=1):
            quote = quotes_map.get(stock.stock_code, {})
            kline = kline_data.get(stock.stock_code, [])

            consecutive_days = self._calculate_consecutive_strong_days(
                stock.stock_code, kline_data
            )
            price_pos = self._calculate_price_position(
                stock.stock_code, quote, kline
            )
            market_cap = self._get_market_cap(quote)

            leader_score = self.score_engine.calculate_leader_score(
                change_pct=stock.change_pct,
                volume_ratio=stock.volume_ratio,
                turnover_rate=stock.turnover_rate,
                rank_in_plate=rank_idx,
                plate_size=plate_size,
                consecutive_strong_days=consecutive_days,
                net_inflow_ratio=quote.get("net_inflow_ratio", 0.0),
            )

            item = LeaderStockItem(
                stock_code=stock.stock_code,
                stock_name=stock.stock_name,
                market=stock.market,
                plate_code=plate_code,
                plate_name=plate_name,
                last_price=stock.last_price,
                change_pct=stock.change_pct,
                volume=stock.volume,
                volume_ratio=stock.volume_ratio,
                turnover_rate=stock.turnover_rate,
                price_position=price_pos,
                heat_score=stock.heat_score,
                leader_score=leader_score,
                leader_rank=0,  # 稍后赋值
                consecutive_strong_days=consecutive_days,
                market_cap=market_cap,
            )
            scored_items.append(item)

        # 6. 按龙头评分降序排序，取 top N
        scored_items.sort(key=lambda x: x.leader_score, reverse=True)
        result = scored_items[:max_per_plate]

        # 赋值排名
        for idx, item in enumerate(result, start=1):
            item.leader_rank = idx

        return result

    def _check_market_cap(self, stock_code: str, quote: Dict) -> bool:
        """检查市值是否达标，数据不可用时排除，不设上限"""
        market_cap = self._get_market_cap(quote)
        if market_cap is None or market_cap <= 0:
            self.logger.debug(
                "股票 %s 市值数据不可用，排除出龙头候选", stock_code
            )
            return False

        market = quote.get("market", "")
        # 判断市场类型
        for market_key, min_cap in self.MIN_MARKET_CAP.items():
            if market_key in market.upper():
                return market_cap > min_cap

        # 未知市场类型，默认通过（不设限制）
        return True

    def _calculate_consecutive_strong_days(
        self, stock_code: str, kline_data: Dict[str, List[Dict]]
    ) -> int:
        """计算连续强势天数（从最近一天往前，涨幅<=0 时停止）"""
        kline_list = kline_data.get(stock_code, []) if kline_data else []
        if not kline_list:
            return 0

        # 确保按时间降序（最近的在前）
        sorted_kline = sorted(
            kline_list, key=lambda x: x.get("time_key", ""), reverse=True
        )

        count = 0
        for record in sorted_kline[: self.strong_day_lookback]:
            open_price = record.get("open_price", 0)
            close_price = record.get("close_price", 0)
            if open_price <= 0:
                break
            change = (close_price - open_price) / open_price * 100
            if change <= 0:
                break
            count += 1

        return count

    def _calculate_price_position(
        self, stock_code: str, quote: Dict, kline: List[Dict]
    ) -> float:
        """计算价格位置 (0-100%)，max==min 返回 50.0，数据不可用返回 -1"""
        if not kline:
            return -1.0

        current_price = quote.get("last_price", 0)
        if current_price <= 0:
            return -1.0

        recent = kline[: self.kline_lookback_days]
        highs = [r.get("high_price", 0) for r in recent if r.get("high_price", 0) > 0]
        lows = [r.get("low_price", 0) for r in recent if r.get("low_price", 0) > 0]

        if not highs or not lows:
            return -1.0

        max_price = max(highs)
        min_price = min(lows)

        if max_price == min_price:
            return 50.0

        position = (current_price - min_price) / (max_price - min_price) * 100
        # 限制在 0-100 范围
        return max(0.0, min(100.0, round(position, 2)))

    def get_all_leaders(
        self,
        hot_stocks_by_plate: Dict[str, List[HotStockItem]],
        kline_data: Optional[Dict[str, List[Dict]]] = None,
        quotes_map: Optional[Dict[str, Dict]] = None,
        max_total: int = 10,
    ) -> List[LeaderStockItem]:
        """遍历所有板块识别龙头，按龙头评分排序返回 top N"""
        all_leaders: List[LeaderStockItem] = []

        for plate_code, hot_stocks in hot_stocks_by_plate.items():
            if not hot_stocks:
                continue
            plate_name = hot_stocks[0].plate_name
            leaders = self.identify_leaders(
                hot_stocks=hot_stocks,
                plate_code=plate_code,
                plate_name=plate_name,
                kline_data=kline_data,
                quotes_map=quotes_map,
                max_per_plate=self.default_max_per_plate,
            )
            all_leaders.extend(leaders)

        # 全局按龙头评分降序排序
        all_leaders.sort(key=lambda x: x.leader_score, reverse=True)
        return all_leaders[:max_total]

    @staticmethod
    def _get_market_cap(quote: Dict) -> Optional[float]:
        """从报价数据中提取市值"""
        cap = quote.get("market_cap") or quote.get("circulation_market_cap")
        if cap is not None and cap > 0:
            return float(cap)
        return None
