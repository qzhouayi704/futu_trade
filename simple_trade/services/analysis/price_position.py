#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置分析模块

计算股票在20日价格区间中的位置，用于建仓时机判断。
提供日线级别和当日级别的双重信号。
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PricePositionResult:
    """价格位置分析结果"""
    position: float          # 0~1，当前价在20日区间的位置
    level: str               # low / mid / high
    high_20d: float          # 20日最高
    low_20d: float           # 20日最低
    daily_signal: str        # 日线级别信号
    daily_label: str         # 日线信号中文

    # 当日级别
    intraday_signal: str     # 当日级别信号
    intraday_label: str      # 当日信号中文
    warnings: List[str]      # 风险警告列表

    # 建仓时机综合
    entry_signal: str        # opportunity/momentum/risky/conflicting/neutral
    entry_label: str         # 中文标签


def _calc_position(current: float, low: float, high: float) -> float:
    """计算价格位置 0~1"""
    if high <= low or high <= 0:
        return 0.5
    return max(0.0, min(1.0, (current - low) / (high - low)))


def _position_to_level(pos: float) -> str:
    if pos <= 0.3:
        return "low"
    if pos >= 0.7:
        return "high"
    return "mid"


LEVEL_LABELS = {"low": "低位", "mid": "中位", "high": "高位"}

DAILY_SIGNAL_MAP = {
    "low_accumulating": "低位吸筹",
    "low_declining": "低位下探",
    "mid_rising": "中位上攻",
    "mid_falling": "中位回落",
    "high_distribution": "高位派发",
    "high_breakout": "高位突破",
    "neutral": "震荡",
}

INTRADAY_SIGNAL_MAP = {
    "strong_buy": "强势买入",
    "buy": "偏多",
    "neutral": "中性",
    "sell": "偏空",
    "strong_sell": "强势卖出",
    "divergence": "量价背离",
}

ENTRY_SIGNAL_MAP = {
    "opportunity": "🟢 建仓",
    "momentum": "🔵 追涨",
    "risky": "🟡 风险",
    "conflicting": "⚠️ 矛盾",
    "neutral": "⚪ 观望",
}


def batch_get_price_range(
    db_manager, stock_codes: List[str], days: int = 20,
) -> Dict[str, Dict]:
    """批量查询20日最高/最低价

    Returns:
        {stock_code: {high_20d, low_20d}}
    """
    if not stock_codes or not db_manager:
        return {}

    try:
        placeholders = ",".join("?" for _ in stock_codes)
        rows = db_manager.execute_query(f"""
            SELECT stock_code,
                   MAX(high_price) AS high_20d,
                   MIN(low_price)  AS low_20d
            FROM kline_data
            WHERE stock_code IN ({placeholders})
              AND time_key >= date('now', '-{days} days')
            GROUP BY stock_code
        """, tuple(stock_codes))

        result = {}
        for row in (rows or []):
            result[row[0]] = {
                "high_20d": float(row[1] or 0),
                "low_20d": float(row[2] or 0),
            }
        return result
    except Exception as e:
        logger.warning(f"批量查询20日价格区间失败: {e}")
        return {}


def _calc_daily_signal(
    level: str, change_rate: float, capital_score: float,
) -> str:
    """日线级别信号：价格位置 + 资金方向"""
    capital_bullish = capital_score >= 55
    capital_bearish = capital_score <= 45

    if level == "low":
        return "low_accumulating" if capital_bullish else "low_declining"
    if level == "high":
        if change_rate > 2 and capital_bullish:
            return "high_breakout"
        return "high_distribution" if capital_bearish else "high_breakout"
    # mid
    if change_rate > 0.5 and capital_bullish:
        return "mid_rising"
    if change_rate < -0.5 and capital_bearish:
        return "mid_falling"
    return "neutral"


def _calc_intraday_signal(
    change_rate: float,
    capital_score: float,
    scalping_direction: Optional[str],
) -> str:
    """当日级别信号：日内涨跌 + 资金流 + 成交方向"""
    capital_bullish = capital_score >= 55
    capital_bearish = capital_score <= 45

    # 量价背离检测：资金看多但股价跌（或反之）
    if capital_bullish and change_rate < -1.0:
        return "divergence"
    if capital_bearish and change_rate > 1.0:
        return "divergence"

    # Scalping delta 信号可用时优先使用
    if scalping_direction == "bullish" and capital_bullish:
        return "strong_buy"
    if scalping_direction == "bearish" and capital_bearish:
        return "strong_sell"

    if capital_bullish and change_rate > 0.5:
        return "buy"
    if capital_bearish and change_rate < -0.5:
        return "sell"

    return "neutral"


def _calc_entry_signal(
    daily_signal: str,
    intraday_signal: str,
    level: str,
) -> str:
    """综合建仓时机判断"""
    if intraday_signal == "divergence":
        return "conflicting"

    if level == "low" and daily_signal == "low_accumulating":
        if intraday_signal in ("strong_buy", "buy"):
            return "opportunity"
        return "neutral"

    if daily_signal in ("mid_rising", "high_breakout"):
        if intraday_signal in ("strong_buy", "buy"):
            return "momentum"
        return "neutral"

    if level == "high" and daily_signal == "high_distribution":
        return "risky"

    if daily_signal == "mid_falling" and intraday_signal in ("sell", "strong_sell"):
        return "risky"

    return "neutral"


def _generate_warnings(
    level: str,
    change_rate: float,
    capital_score: float,
    intraday_signal: str,
    scalping_direction: Optional[str],
) -> List[str]:
    """生成风险警告列表"""
    warnings = []

    # 量价背离
    if capital_score >= 55 and change_rate < -1.0:
        warnings.append("price_flow_divergence")
    if capital_score <= 45 and change_rate > 1.0:
        warnings.append("price_flow_divergence")

    # 高位资金流入
    if level == "high" and capital_score >= 60:
        warnings.append("high_position_inflow")

    # 成交与资金方向矛盾
    if scalping_direction == "bullish" and capital_score <= 40:
        warnings.append("signal_contradiction")
    if scalping_direction == "bearish" and capital_score >= 60:
        warnings.append("signal_contradiction")

    return warnings


def analyze_price_position(
    current_price: float,
    change_rate: float,
    price_range: Optional[Dict],
    capital_score: float = 50.0,
    scalping_direction: Optional[str] = None,
) -> PricePositionResult:
    """分析单只股票的价格位置和建仓时机

    Args:
        current_price: 当前价格
        change_rate: 当日涨跌幅 (%)
        price_range: {high_20d, low_20d} 来自 batch_get_price_range
        capital_score: 资金评分 0~100
        scalping_direction: Scalping delta 方向 (bullish/bearish/neutral)
    """
    high_20d = price_range.get("high_20d", 0) if price_range else 0
    low_20d = price_range.get("low_20d", 0) if price_range else 0

    position = _calc_position(current_price, low_20d, high_20d)
    level = _position_to_level(position)

    daily_signal = _calc_daily_signal(level, change_rate, capital_score)
    intraday_signal = _calc_intraday_signal(
        change_rate, capital_score, scalping_direction,
    )
    entry_signal = _calc_entry_signal(daily_signal, intraday_signal, level)

    warnings = _generate_warnings(
        level, change_rate, capital_score,
        intraday_signal, scalping_direction,
    )

    return PricePositionResult(
        position=round(position, 3),
        level=level,
        high_20d=high_20d,
        low_20d=low_20d,
        daily_signal=daily_signal,
        daily_label=DAILY_SIGNAL_MAP.get(daily_signal, "震荡"),
        intraday_signal=intraday_signal,
        intraday_label=INTRADAY_SIGNAL_MAP.get(intraday_signal, "中性"),
        warnings=warnings,
        entry_signal=entry_signal,
        entry_label=ENTRY_SIGNAL_MAP.get(entry_signal, "⚪ 观望"),
    )
