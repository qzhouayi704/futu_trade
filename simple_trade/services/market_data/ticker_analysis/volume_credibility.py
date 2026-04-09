#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成交量可信度分析（第5维度）

将当日成交额与历史日均成交额对比，评估当前买卖信号的可信度。
检测缩量拉升等典型诱多模式。
"""

from typing import Any, Dict

from ..order_book.order_book_analyzer import _clamp, _score_to_signal
from .ticker_analyzer import TickerDimensionSignal


# 港股美股量能标准差异
# 港股日均成交额普遍较低，美股流动性更好
MARKET_VOLUME_RATIO_THRESHOLDS = {
    "HK": {
        "strong": 1.2,    # >= 1.2倍日均 → 放量
        "normal": 0.7,    # >= 0.7倍 → 正常
        "weak": 0.4,      # >= 0.4倍 → 偏低
        # < 0.4倍 → 严重不足
    },
    "US": {
        "strong": 1.5,    # 美股流动性好，需要更高倍数才算放量
        "normal": 0.8,
        "weak": 0.5,
    },
}


def analyze_volume_credibility(
    stock_code: str,
    today_turnover: float,
    avg_daily_turnover: float,
    change_pct: float,
) -> TickerDimensionSignal:
    """成交量可信度分析

    Args:
        stock_code: 股票代码（用于判断市场）
        today_turnover: 当日已有成交额
        avg_daily_turnover: 历史日均成交额（从K线数据库计算）
        change_pct: 当日涨跌幅（百分比，如 4.0 表示涨4%）

    Returns:
        TickerDimensionSignal 量能可信度维度信号
    """
    if avg_daily_turnover <= 0 or today_turnover <= 0:
        return TickerDimensionSignal(
            name="量能可信度",
            signal="neutral",
            score=0.0,
            description="历史成交数据不足，无法评估量能",
            details={
                "today_turnover": round(today_turnover, 2),
                "avg_daily_turnover": round(avg_daily_turnover, 2),
                "volume_ratio": 0.0,
                "trap_warning": "",
            },
        )

    market = "US" if stock_code.startswith("US.") else "HK"
    thresholds = MARKET_VOLUME_RATIO_THRESHOLDS.get(market, MARKET_VOLUME_RATIO_THRESHOLDS["HK"])

    volume_ratio = today_turnover / avg_daily_turnover

    # 1. 量能充足度评分
    sufficiency_score = _calc_sufficiency_score(volume_ratio, thresholds)

    # 2. 诱多/诱空模式检测
    trap_score, trap_warning = _detect_trap_pattern(
        volume_ratio, change_pct, thresholds,
    )

    score = _clamp(sufficiency_score + trap_score)
    desc = _credibility_description(volume_ratio, trap_warning, market)

    details: Dict[str, Any] = {
        "today_turnover": round(today_turnover, 2),
        "avg_daily_turnover": round(avg_daily_turnover, 2),
        "volume_ratio": round(volume_ratio, 3),
        "sufficiency_score": round(sufficiency_score, 1),
        "trap_score": round(trap_score, 1),
        "trap_warning": trap_warning,
        "market": market,
    }

    return TickerDimensionSignal(
        name="量能可信度",
        signal=_score_to_signal(score),
        score=round(score, 1),
        description=desc,
        details=details,
    )


def _calc_sufficiency_score(volume_ratio: float, thresholds: dict) -> float:
    """量能充足度评分（-50 ~ 50）"""
    if volume_ratio >= thresholds["strong"]:
        return 50.0
    if volume_ratio >= thresholds["normal"]:
        # 线性插值：normal → strong 对应 20 → 50
        t = (volume_ratio - thresholds["normal"]) / (thresholds["strong"] - thresholds["normal"])
        return 20.0 + t * 30.0
    if volume_ratio >= thresholds["weak"]:
        # weak → normal 对应 -20 → 20
        t = (volume_ratio - thresholds["weak"]) / (thresholds["normal"] - thresholds["weak"])
        return -20.0 + t * 40.0
    # < weak → 严重不足
    return -50.0


def _detect_trap_pattern(
    volume_ratio: float, change_pct: float, thresholds: dict,
) -> tuple:
    """检测诱多/诱空模式

    Returns:
        (扣分, 警告文字)
    """
    is_low_volume = volume_ratio < thresholds["normal"]

    # 缩量拉升 → 典型诱多
    if change_pct > 2.0 and is_low_volume:
        severity = min((thresholds["normal"] - volume_ratio) / thresholds["normal"], 1.0)
        penalty = -30.0 - severity * 20.0  # -30 ~ -50
        return penalty, f"缩量拉升（涨{change_pct:.1f}%但量能仅{volume_ratio:.1f}倍日均），警惕诱多"

    # 缩量下跌 → 可能是洗盘，轻微扣分
    if change_pct < -2.0 and is_low_volume:
        return -10.0, f"缩量下跌（跌{abs(change_pct):.1f}%量能{volume_ratio:.1f}倍日均），可能洗盘"

    # 放量下跌 → 真实抛压
    if change_pct < -2.0 and volume_ratio >= thresholds["strong"]:
        return -20.0, f"放量下跌（跌{abs(change_pct):.1f}%量能{volume_ratio:.1f}倍日均），抛压较重"

    return 0.0, ""


def _credibility_description(
    volume_ratio: float, trap_warning: str, market: str,
) -> str:
    """生成可信度描述"""
    if trap_warning:
        return trap_warning

    market_label = "港股" if market == "HK" else "美股"
    if volume_ratio >= 1.5:
        return f"量能充沛（{volume_ratio:.1f}倍{market_label}日均），信号可信度高"
    if volume_ratio >= 0.8:
        return f"量能正常（{volume_ratio:.1f}倍{market_label}日均）"
    if volume_ratio >= 0.4:
        return f"量能偏低（{volume_ratio:.1f}倍{market_label}日均），信号可信度一般"
    return f"量能严重不足（{volume_ratio:.1f}倍{market_label}日均），信号可信度低"
