#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持仓健康度评估器 - 分析每个持仓的当前状态"""

import logging
from typing import List, Dict, Any, Optional

from .models import PositionHealth, HealthLevel
from .kline_utils import extract_closes, extract_volumes


logger = logging.getLogger(__name__)

# 评分权重
PROFIT_WEIGHT = 0.25
TREND_WEIGHT = 0.25
ACTIVITY_WEIGHT = 0.25
MOMENTUM_WEIGHT = 0.25


class HealthEvaluator:
    """持仓健康度评估器"""

    def evaluate_all(
        self,
        positions: List[Dict[str, Any]],
        quotes: List[Dict[str, Any]],
        kline_cache: Dict[str, List],
    ) -> List[PositionHealth]:
        """批量评估所有持仓的健康度"""
        results: List[PositionHealth] = []
        quotes_map = {q.get('code', ''): q for q in quotes}

        for pos in positions:
            stock_code = pos.get('stock_code', pos.get('code', ''))
            if not stock_code:
                continue
            quote = quotes_map.get(stock_code, {})
            klines = kline_cache.get(stock_code, [])
            health = self.evaluate_position(pos, quote, klines)
            results.append(health)

        return results

    def evaluate_position(
        self,
        position: Dict[str, Any],
        quote: Dict[str, Any],
        klines: List,
    ) -> PositionHealth:
        """评估单个持仓的健康度"""
        stock_code = position.get('stock_code', position.get('code', ''))
        stock_name = position.get('stock_name', position.get('name', ''))

        # 提取基础数据
        profit_pct = self._get_profit_pct(position)
        turnover_rate = quote.get('turnover_rate', 0.0)
        amplitude = self._calc_amplitude(quote)
        change_pct = quote.get('change_rate', quote.get('change_percent', 0.0))
        current_volume = quote.get('volume', 0)

        # 计算各维度评分
        profit_score = self._calc_profit_score(profit_pct)
        trend, trend_score = self._calc_trend_score(klines)
        activity_score = self._calc_activity_score(turnover_rate)
        volume_ratio = self._calc_volume_ratio(klines, current_volume)
        momentum_score = self._calc_momentum_score(volume_ratio, change_pct)

        # 综合评分
        total_score = (
            profit_score * PROFIT_WEIGHT
            + trend_score * TREND_WEIGHT
            + activity_score * ACTIVITY_WEIGHT
            + momentum_score * MOMENTUM_WEIGHT
        )

        health_level = self._determine_health_level(total_score)
        reasons = self._build_reasons(
            profit_pct, trend, turnover_rate, volume_ratio, health_level
        )

        return PositionHealth(
            stock_code=stock_code,
            stock_name=stock_name,
            health_level=health_level,
            score=total_score,
            profit_pct=profit_pct,
            turnover_rate=turnover_rate,
            amplitude=amplitude,
            volume_ratio=volume_ratio,
            trend=trend,
            reasons=reasons,
        )

    # ==================== 评分计算 ====================

    @staticmethod
    def _get_profit_pct(position: Dict[str, Any]) -> float:
        """从持仓数据中提取盈亏比例"""
        pl_ratio = position.get('pl_ratio', None)
        if pl_ratio is not None:
            return float(pl_ratio) * 100 if abs(float(pl_ratio)) < 1 else float(pl_ratio)
        cost = position.get('cost_price', 0)
        current = position.get('current_price', position.get('nominal_price', 0))
        if cost and cost > 0:
            return (current - cost) / cost * 100
        return 0.0

    @staticmethod
    def _calc_amplitude(quote: Dict[str, Any]) -> float:
        """计算当日振幅"""
        high = quote.get('high_price', 0)
        low = quote.get('low_price', 0)
        prev_close = quote.get('prev_close_price', quote.get('last_close_price', 0))
        if prev_close and prev_close > 0 and high > 0 and low > 0:
            return (high - low) / prev_close * 100
        return 0.0

    @staticmethod
    def _calc_profit_score(profit_pct: float) -> float:
        """盈亏评分: 盈利越多越健康"""
        if profit_pct >= 5:
            return 100.0
        if profit_pct >= 0:
            return 50.0 + (profit_pct / 5.0) * 50.0
        if profit_pct >= -3:
            return 30.0 + (3.0 + profit_pct) / 3.0 * 20.0
        return max(0.0, 30.0 + profit_pct * 10.0)

    @staticmethod
    def _calc_trend_score(klines: List) -> tuple:
        """通过均线判断趋势并评分"""
        if not klines or len(klines) < 20:
            return "SIDEWAYS", 50.0

        closes = extract_closes(klines, 20)
        if len(closes) < 20:
            return "SIDEWAYS", 50.0

        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20

        if ma5 > ma10 > ma20:
            return "UP", 100.0
        if ma5 > ma10:
            return "UP", 70.0
        if ma5 < ma10 < ma20:
            return "DOWN", 20.0
        if ma5 < ma10:
            return "DOWN", 35.0
        return "SIDEWAYS", 50.0

    @staticmethod
    def _calc_activity_score(turnover_rate: float) -> float:
        """活跃度评分: 换手率越高越活跃"""
        if turnover_rate >= 3.0:
            return 100.0
        if turnover_rate >= 1.0:
            return 50.0 + (turnover_rate - 1.0) / 2.0 * 50.0
        if turnover_rate > 0:
            return turnover_rate / 1.0 * 50.0
        return 0.0

    @staticmethod
    def _calc_volume_ratio(klines: List, current_volume: int) -> float:
        """计算量比（当前成交量 / 5日平均成交量）"""
        if not klines or len(klines) < 5 or current_volume <= 0:
            return 1.0

        volumes = extract_volumes(klines[-6:-1], 5)

        if not volumes or sum(volumes) == 0:
            return 1.0

        avg_volume = sum(volumes) / len(volumes)
        return current_volume / avg_volume if avg_volume > 0 else 1.0

    @staticmethod
    def _calc_momentum_score(volume_ratio: float, change_pct: float) -> float:
        """动量评分: 量价配合"""
        if volume_ratio >= 1.5 and change_pct > 0:
            return 100.0  # 放量上涨
        if volume_ratio >= 1.5 and change_pct < 0:
            return 30.0   # 放量下跌
        if volume_ratio < 0.8:
            return 40.0   # 缩量
        return 60.0

    @staticmethod
    def _determine_health_level(score: float) -> HealthLevel:
        """根据评分确定健康等级"""
        if score >= 70:
            return HealthLevel.STRONG
        if score >= 40:
            return HealthLevel.NEUTRAL
        if score >= 20:
            return HealthLevel.WEAK
        return HealthLevel.DANGER

    @staticmethod
    def _build_reasons(
        profit_pct: float,
        trend: str,
        turnover_rate: float,
        volume_ratio: float,
        health_level: HealthLevel,
    ) -> List[str]:
        """构建健康度评估理由"""
        reasons: List[str] = []

        # 盈亏
        if profit_pct >= 5:
            reasons.append(f"盈利 {profit_pct:.1f}%，表现良好")
        elif profit_pct >= 0:
            reasons.append(f"微利 {profit_pct:.1f}%")
        elif profit_pct >= -3:
            reasons.append(f"小幅亏损 {profit_pct:.1f}%")
        else:
            reasons.append(f"亏损 {profit_pct:.1f}%，需关注")

        # 趋势
        trend_labels = {"UP": "趋势向上", "DOWN": "趋势向下", "SIDEWAYS": "横盘震荡"}
        reasons.append(trend_labels.get(trend, "趋势不明"))

        # 活跃度
        if turnover_rate < 0.5:
            reasons.append(f"换手率极低 {turnover_rate:.2f}%，流动性差")
        elif turnover_rate < 1.0:
            reasons.append(f"换手率偏低 {turnover_rate:.2f}%")

        # 量比
        if volume_ratio >= 2.0:
            reasons.append(f"量比 {volume_ratio:.1f}，明显放量")
        elif volume_ratio < 0.5:
            reasons.append(f"量比 {volume_ratio:.1f}，严重缩量")

        return reasons
