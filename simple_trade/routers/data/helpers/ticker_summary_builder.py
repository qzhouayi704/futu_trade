#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成交分析摘要构建器

将 TickerAnalysis 结果转换为前端所需的摘要格式，
并执行偏多/偏空判定逻辑。
"""

from dataclasses import dataclass, asdict
from typing import Optional

from ....services.market_data.ticker_analysis.ticker_analyzer import TickerAnalysis

# ==================== 判定阈值 ====================

DEFAULT_BIAS_THRESHOLD = 20
"""偏多/偏空判定阈值（综合评分绝对值）"""

DEFAULT_STRONG_RATIO_THRESHOLD = 1.5
"""强烈偏多的力量比阈值"""


# ==================== 数据结构 ====================


@dataclass
class TickerSummary:
    """成交分析摘要 - 附加到高换手率股票数据中"""

    score: float          # 综合评分 -100~100
    signal: str           # bullish/slightly_bullish/neutral/slightly_bearish/bearish
    label: str            # 中文标签（看涨/偏多/中性/偏空/看跌）
    buy_sell_ratio: float  # 主动买卖力量比
    net_turnover: float   # 主动买卖净额
    bias: str             # 判定结果: strong_bullish/bullish/bearish/neutral
    bias_label: str       # 判定中文标签: 强买/偏多/偏空/中性
    big_order_pct: float = 0.0  # 大单成交占比（%）

    def to_dict(self) -> dict:
        """转为字典，方便 JSON 序列化"""
        return asdict(self)



# ==================== 构建函数 ====================


def build_ticker_summary(
    analysis: Optional[TickerAnalysis],
    bias_threshold: float = DEFAULT_BIAS_THRESHOLD,
    strong_ratio_threshold: float = DEFAULT_STRONG_RATIO_THRESHOLD,
) -> Optional[TickerSummary]:
    """从 TickerAnalysis 构建前端摘要

    Args:
        analysis: 成交分析结果，为 None 时直接返回 None
        bias_threshold: 偏多/偏空判定阈值，默认 20
        strong_ratio_threshold: 强烈偏多的力量比阈值，默认 1.5

    Returns:
        TickerSummary 或 None
    """
    if analysis is None:
        return None

    # 从各维度提取关键指标
    buy_sell_ratio = 1.0
    net_turnover = 0.0
    big_order_pct = 0.0
    for dim in analysis.dimensions:
        if dim.name == "主动买卖":
            buy_sell_ratio = dim.details.get("buy_sell_ratio", 1.0)
            net_turnover = dim.details.get("net_turnover", 0.0)
        elif dim.name == "大单占比":
            big_order_pct = dim.details.get("big_order_pct", 0.0)

    # 偏多/偏空判定
    score = analysis.total_score
    if score > bias_threshold and buy_sell_ratio > strong_ratio_threshold:
        bias, bias_label = "strong_bullish", "强买"
    elif score > bias_threshold:
        bias, bias_label = "bullish", "偏多"
    elif score < -bias_threshold:
        bias, bias_label = "bearish", "偏空"
    else:
        bias, bias_label = "neutral", "中性"

    return TickerSummary(
        score=analysis.total_score,
        signal=analysis.signal,
        label=analysis.label,
        buy_sell_ratio=round(buy_sell_ratio, 2),
        net_turnover=round(net_turnover, 2),
        bias=bias,
        bias_label=bias_label,
        big_order_pct=round(big_order_pct, 2),
    )

