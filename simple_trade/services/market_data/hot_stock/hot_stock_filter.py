#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
热门股票筛选器

从板块内筛选交易活跃个股，每板块返回 5-10 只。
筛选流程：活跃度预筛选（成交量/换手率/价格）→ 涨幅+量比筛选 → 评分排序
"""

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from simple_trade.services.analysis.heat.heat_score_engine import HeatScoreEngine
from simple_trade.utils.converters import get_last_price


logger = logging.getLogger(__name__)

# 活跃度筛选默认阈值（与三级筛选器第一级复用）
ACTIVITY_THRESHOLDS = {
    "min_volume_hk": 500_000,       # 港股最低成交量
    "min_volume_us": 3_000_000,     # 美股最低成交量
    "min_turnover_rate_hk": 0.1,    # 港股最低换手率 (%)
    "min_turnover_rate_us": 0.5,    # 美股最低换手率 (%)
    "min_price_hk": 1.0,            # 港股最低价格 (港元)
}

# 默认配置
DEFAULT_CONFIG = {
    "min_volume_ratio": 1.5,      # 量比下限
    "min_per_plate": 5,           # 每板块最少返回数
    "max_per_plate": 10,          # 每板块最多返回数
}


@dataclass
class HotStockItem:
    """热门股票数据项"""

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
    heat_score: float  # 基础评分

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


class HotStockFilter:
    """热门股票筛选器：每板块 5-10 只活跃个股"""

    def __init__(self, score_engine: HeatScoreEngine, config: dict = None):
        self.score_engine = score_engine
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.min_volume_ratio = cfg["min_volume_ratio"]
        self.default_min = cfg["min_per_plate"]
        self.default_max = cfg["max_per_plate"]
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def check_stock_activity(
        stock_code: str, quote: Dict, thresholds: Dict = None,
    ) -> bool:
        """检查单只股票是否满足活跃度条件

        活跃度条件（成交量、换手率、价格门槛），与三级筛选器第一级复用。

        Args:
            stock_code: 股票代码（如 HK.00700, US.AAPL）
            quote: 实时报价字典，需含 volume, turnover_rate, cur_price/last_price
            thresholds: 自定义阈值，默认使用 ACTIVITY_THRESHOLDS

        Returns:
            True 表示满足活跃度条件
        """
        if not quote:
            return False

        t = thresholds or ACTIVITY_THRESHOLDS
        market = "HK" if stock_code.startswith("HK.") else "US"

        # 成交量检查
        volume = quote.get("volume", 0) or 0
        min_volume = t.get(f"min_volume_{market.lower()}", 500_000)
        if volume < min_volume:
            return False

        # 换手率检查
        turnover_rate = quote.get("turnover_rate", 0) or 0
        min_turnover = t.get(f"min_turnover_rate_{market.lower()}", 0.1)
        if turnover_rate < min_turnover:
            return False

        # 价格检查（仅港股）
        if market == "HK":
            price = get_last_price(quote)
            min_price = t.get("min_price_hk", 1.0)
            if price < min_price:
                return False

        return True

    def filter_hot_stocks(
        self,
        plate_code: str,
        plate_name: str,
        stocks: List[Dict],
        quotes_map: Dict[str, Dict],
        min_per_plate: int = None,
        max_per_plate: int = None,
    ) -> List[HotStockItem]:
        """板块内筛选热门股票

        筛选条件：涨幅 > 板块平均涨幅，量比 > 1.5
        按基础评分降序排序，返回 min_per_plate 到 max_per_plate 只。
        如果满足条件的股票不足 min_per_plate，返回所有满足条件的。

        Args:
            plate_code: 板块代码
            plate_name: 板块名称
            stocks: 板块内股票列表，每个元素含 stock_code, stock_name, market
            quotes_map: 实时报价字典，key=stock_code
            min_per_plate: 每板块最少返回数（默认 5）
            max_per_plate: 每板块最多返回数（默认 10）

        Returns:
            按评分降序排列的 HotStockItem 列表
        """
        min_count = min_per_plate if min_per_plate is not None else self.default_min
        max_count = max_per_plate if max_per_plate is not None else self.default_max

        # 收集有报价且满足活跃度条件的股票
        quoted_stocks = []
        for stock in stocks:
            code = stock.get("stock_code", "")
            quote = quotes_map.get(code)
            if not quote:
                continue
            # 活跃度预筛选：成交量、换手率、价格门槛
            if not self.check_stock_activity(code, quote):
                continue
            quoted_stocks.append((stock, quote))

        if not quoted_stocks:
            return []

        # 计算板块平均涨幅
        change_pcts = [q.get("change_pct", 0.0) for _, q in quoted_stocks]
        avg_change = sum(change_pcts) / len(change_pcts)

        # 筛选：涨幅 > 板块平均涨幅 AND 量比 > min_volume_ratio
        candidates = []
        for stock, quote in quoted_stocks:
            change_pct = quote.get("change_pct", 0.0)
            volume_ratio = quote.get("volume_ratio", 0.0)

            if change_pct > avg_change and volume_ratio > self.min_volume_ratio:
                heat_score = self.score_engine.calculate_base_score(
                    change_pct=change_pct,
                    volume_ratio=volume_ratio,
                    turnover_rate=quote.get("turnover_rate", 0.0),
                )
                item = HotStockItem(
                    stock_code=stock.get("stock_code", ""),
                    stock_name=stock.get("stock_name", ""),
                    market=stock.get("market", ""),
                    plate_code=plate_code,
                    plate_name=plate_name,
                    last_price=quote.get("last_price", 0.0),
                    change_pct=change_pct,
                    volume=quote.get("volume", 0),
                    volume_ratio=volume_ratio,
                    turnover_rate=quote.get("turnover_rate", 0.0),
                    heat_score=heat_score,
                )
                candidates.append(item)

        # 按评分降序排序
        candidates.sort(key=lambda x: x.heat_score, reverse=True)

        # 返回 max_per_plate 只（不足 min_per_plate 也全部返回）
        return candidates[:max_count]

    def get_all_hot_stocks(
        self,
        plates_data: List[Dict],
        quotes_map: Dict[str, Dict],
    ) -> Dict[str, List[HotStockItem]]:
        """遍历所有板块，筛选热门股票

        Args:
            plates_data: 板块列表，每个元素含 plate_code, plate_name, stocks
            quotes_map: 实时报价字典

        Returns:
            {plate_code: [HotStockItem, ...]}
        """
        result: Dict[str, List[HotStockItem]] = {}

        for plate in plates_data:
            plate_code = plate.get("plate_code", "")
            plate_name = plate.get("plate_name", "")
            stocks = plate.get("stocks", [])

            if not stocks:
                continue

            hot_stocks = self.filter_hot_stocks(
                plate_code=plate_code,
                plate_name=plate_name,
                stocks=stocks,
                quotes_map=quotes_map,
            )

            if hot_stocks:
                result[plate_code] = hot_stocks

        return result
