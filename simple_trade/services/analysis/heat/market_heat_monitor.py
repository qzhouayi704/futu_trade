#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场热度监控器

职责：
1. 基于实时报价数据计算整体市场热度（0-100）
2. 基于实时数据计算板块热度并排序
3. 推荐仓位比例
4. 检测市场情绪
"""

import logging
from typing import List, Dict, Optional

from .heat_score_engine import HeatScoreEngine

logger = logging.getLogger(__name__)

# 大涨股涨幅阈值（港美股无涨停板，3% 视为大涨）
BIG_RISE_THRESHOLD = 3.0


class MarketHeatMonitor:
    """市场热度监控器

    通过实时报价数据计算市场热度和板块热度，
    替代旧版基于数据库历史值和静态 priority 的实现。
    """

    def __init__(
        self,
        db_manager,
        config: dict,
        score_engine: Optional[HeatScoreEngine] = None,
    ):
        """
        Args:
            db_manager: 数据库管理器（保留，其他方法可能需要）
            config: 配置字典
            score_engine: 统一评分引擎（可选，默认创建新实例）
        """
        self.db_manager = db_manager
        self.config = config
        self.score_engine = score_engine or HeatScoreEngine()

    # ── 市场热度 ────────────────────────────────────────────

    def calculate_market_heat(self, quotes: List[Dict] = None) -> float:
        """基于实时报价计算市场热度（0-100）

        维度：上涨比例×40% + 平均涨幅归一化×30% + 平均换手率归一化×30%

        Args:
            quotes: 实时报价列表，每项需包含 change_pct 和 turnover_rate
                    为 None 或空列表时返回默认值 50.0

        Returns:
            0-100 的市场热度分数
        """
        if not quotes:
            logger.warning("实时报价数据不可用，返回默认市场热度 50.0")
            return 50.0

        total = len(quotes)

        # 1. 上涨股票比例（change_pct > 0）
        up_count = sum(1 for q in quotes if q.get("change_pct", 0) > 0)
        up_ratio = up_count / total  # 0-1

        # 2. 平均涨幅
        avg_change = sum(q.get("change_pct", 0) for q in quotes) / total

        # 3. 平均换手率
        avg_turnover = sum(q.get("turnover_rate", 0) for q in quotes) / total

        # 归一化
        up_score = up_ratio * 100  # 已经是 0-1，直接映射到 0-100
        change_score = self.score_engine.normalize(avg_change, cap=10)
        turnover_score = self.score_engine.normalize(avg_turnover, cap=20)

        # 加权
        score = up_score * 0.4 + change_score * 0.3 + turnover_score * 0.3

        return round(min(max(score, 0), 100), 2)

    # ── 热门板块 ────────────────────────────────────────────

    def get_hot_plates(
        self,
        plates: List[Dict] = None,
        quotes_map: Dict[str, Dict] = None,
        top_n: int = 10,
    ) -> List[Dict]:
        """基于实时数据计算板块热度并排序

        Args:
            plates: 板块列表，每项需包含 plate_code, plate_name,
                    stock_count, stocks（板块内股票代码列表）
            quotes_map: {stock_code: quote_dict} 实时报价字典
            top_n: 返回前 N 个板块

        Returns:
            按热度分降序排列的板块列表，每项包含：
            plate_code, plate_name, stock_count,
            avg_change_pct, up_ratio, hot_stock_count,
            leading_stock_name, heat_score
        """
        if not plates or quotes_map is None:
            logger.warning("板块数据或报价数据不可用，返回空列表")
            return []

        result = []
        for plate in plates:
            plate_info = self._calculate_plate_info(plate, quotes_map)
            result.append(plate_info)

        # 按热度分降序排序
        result.sort(key=lambda x: x["heat_score"], reverse=True)
        return result[:top_n]

    # ── 仓位推荐 & 情绪检测（保持不变）──────────────────────

    def recommend_position_ratio(self, market_heat: float) -> float:
        """根据市场热度推荐仓位比例（0-1）"""
        if market_heat >= 80:
            return 0.8
        elif market_heat >= 60:
            return 0.6
        elif market_heat >= 40:
            return 0.4
        else:
            return 0.2

    def detect_market_sentiment(self, market_heat: float) -> str:
        """检测市场情绪"""
        if market_heat >= 80:
            return "极度活跃"
        elif market_heat >= 60:
            return "活跃"
        elif market_heat >= 40:
            return "正常"
        elif market_heat >= 20:
            return "冷淡"
        else:
            return "极度冷淡"

    # ── 内部方法 ────────────────────────────────────────────

    def _calculate_plate_info(
        self, plate: Dict, quotes_map: Dict[str, Dict]
    ) -> Dict:
        """计算单个板块的热度信息"""
        plate_code = plate.get("plate_code", "")
        plate_name = plate.get("plate_name", "")
        stock_count = plate.get("stock_count", 0)
        stock_codes = plate.get("stocks", [])

        # 收集板块内有报价的股票
        plate_quotes = [
            quotes_map[code] for code in stock_codes if code in quotes_map
        ]

        if not plate_quotes:
            # 无报价数据，热度分设为 0
            return {
                "plate_code": plate_code,
                "plate_name": plate_name,
                "stock_count": stock_count,
                "avg_change_pct": 0.0,
                "up_ratio": 0.0,
                "hot_stock_count": 0,
                "leading_stock_name": "",
                "heat_score": 0.0,
            }

        total = len(plate_quotes)

        # 平均涨幅
        avg_change_pct = round(
            sum(q.get("change_pct", 0) for q in plate_quotes) / total, 2
        )

        # 涨跌比
        up_count = sum(1 for q in plate_quotes if q.get("change_pct", 0) > 0)
        up_ratio = round(up_count / total, 4)

        # 大涨股数量（涨幅 > 3%）
        hot_stock_count = sum(
            1
            for q in plate_quotes
            if q.get("change_pct", 0) > BIG_RISE_THRESHOLD
        )

        # 大涨股占比
        big_rise_ratio = hot_stock_count / total

        # 领涨股（涨幅最高的股票名称）
        leading = max(plate_quotes, key=lambda q: q.get("change_pct", 0))
        leading_stock_name = leading.get("stock_name", "")

        # 资金净流入占比（如果报价中有该字段）
        net_inflow_ratio = self._calc_net_inflow_ratio(plate_quotes)

        # 使用评分引擎计算板块热度
        heat_score = self.score_engine.calculate_plate_heat(
            up_ratio=up_ratio,
            avg_change_pct=avg_change_pct,
            big_rise_ratio=big_rise_ratio,
            net_inflow_ratio=net_inflow_ratio,
        )

        return {
            "plate_code": plate_code,
            "plate_name": plate_name,
            "stock_count": stock_count,
            "avg_change_pct": avg_change_pct,
            "up_ratio": up_ratio,
            "hot_stock_count": hot_stock_count,
            "leading_stock_name": leading_stock_name,
            "heat_score": heat_score,
        }

    @staticmethod
    def _calc_net_inflow_ratio(plate_quotes: List[Dict]) -> float:
        """计算板块资金净流入占比（0-1），数据不可用时返回 0"""
        inflows = [q.get("net_inflow_ratio", 0) for q in plate_quotes]
        if not inflows:
            return 0.0
        avg = sum(inflows) / len(inflows)
        return max(avg, 0.0)
