#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐笔成交分析 - 4维度分析函数（从 ticker_analyzer.py 拆分）"""

from typing import Any, Dict, List, Optional

from ..order_book.order_book_analyzer import _clamp, _score_to_signal
from .ticker_analyzer import TickerDimensionSignal
from .ticker_service import TickerRecord
from .ticker_timeline import calc_buy_sell_timeline


def _calc_net_ratio(records: List[TickerRecord]) -> float:
    """计算一组记录的净额比例（净额 / 总额）"""
    buy_t = sum(r.turnover for r in records if r.direction == "BUY")
    sell_t = sum(r.turnover for r in records if r.direction == "SELL")
    total = buy_t + sell_t
    return (buy_t - sell_t) / total if total > 0 else 0.0


def analyze_active_buy_sell(
    records: List[TickerRecord],
    scalping_delta: Optional[float] = None,
    scalping_delta_direction: Optional[str] = None,
) -> TickerDimensionSignal:
    """主动买卖力量分析：引入时间衰减权重（最早0.3→最新1.0线性插值）。

    当 Scalping 系统运行时，可传入 Delta 数据进行交叉验证：
    - scalping_delta: Scalping DeltaCalculator 的最近周期净动量
    - scalping_delta_direction: "bullish" / "bearish" / "neutral"

    若 Scalping Delta 方向与 Ticker direction 矛盾，评分向 0 收敛（× 0.4）。
    """
    if not records:
        return _empty_signal("主动买卖", {
            "buy_count": 0, "sell_count": 0, "neutral_count": 0,
            "buy_turnover": 0.0, "sell_turnover": 0.0,
            "net_turnover": 0.0, "buy_sell_ratio": 10.0, "total_count": 0,
            "time_range_start": "", "time_range_end": "",
            "trend_direction": "持平", "first_half_ratio": 0.0, "second_half_ratio": 0.0,
        })

    buy_count = sell_count = neutral_count = 0
    buy_turnover = sell_turnover = 0.0
    # 时间衰减加权统计
    weighted_buy_turnover = weighted_sell_turnover = 0.0

    n = len(records)
    for i, r in enumerate(records):
        # 线性衰减权重：最早 0.3 → 最新 1.0
        weight = 0.3 + 0.7 * (i / (n - 1)) if n > 1 else 1.0

        if r.direction == "BUY":
            buy_count += 1
            buy_turnover += r.turnover
            weighted_buy_turnover += r.turnover * weight
        elif r.direction == "SELL":
            sell_count += 1
            sell_turnover += r.turnover
            weighted_sell_turnover += r.turnover * weight
        else:
            neutral_count += 1

    total_count = len(records)
    net_turnover = buy_turnover - sell_turnover

    # 数据质量检查：如果所有记录都是 NEUTRAL，记录警告
    if buy_count == 0 and sell_count == 0 and neutral_count > 0:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"主动买卖分析: 所有 {neutral_count} 条记录方向都是 NEUTRAL，"
            f"数据可能异常，请检查字段名映射"
        )

    # 计算力量比：优化默认值逻辑
    if sell_turnover > 0:
        buy_sell_ratio = buy_turnover / sell_turnover
    elif buy_turnover > 0:
        buy_sell_ratio = 10.0  # 纯买入，用 10 表示"极大"
    else:
        buy_sell_ratio = 1.0   # 无买卖数据，返回中性值 1.0

    # 评分：基于时间衰减加权后的净额占比
    weighted_total = weighted_buy_turnover + weighted_sell_turnover
    if weighted_total > 0:
        weighted_net = weighted_buy_turnover - weighted_sell_turnover
        score = (weighted_net / weighted_total) * 100
    else:
        score = 0.0
    score = _clamp(score)

    # Scalping Delta 交叉验证：方向矛盾时衰减评分
    delta_cross_note = ""
    if scalping_delta_direction and scalping_delta_direction != "neutral" and abs(score) > 5:
        ticker_bullish = score > 0
        delta_bullish = scalping_delta_direction == "bullish"
        if ticker_bullish != delta_bullish:
            delta_cross_note = (
                f"Scalping Delta({scalping_delta:.1f})方向与成交方向矛盾，评分衰减"
            )
            score *= 0.4  # 矛盾时向 0 收敛

    # 数据时间范围
    time_range_start = records[0].time
    time_range_end = records[-1].time

    # 近期趋势计算：按索引分前后半段
    mid = len(records) // 2
    first_half_ratio = _calc_net_ratio(records[:mid])
    second_half_ratio = _calc_net_ratio(records[mid:])

    diff = second_half_ratio - first_half_ratio
    if diff > 0.05:
        trend_direction = "买方增强"
    elif diff < -0.05:
        trend_direction = "卖方增强"
    else:
        trend_direction = "持平"

    details: Dict[str, Any] = {
        "buy_count": buy_count,
        "sell_count": sell_count,
        "neutral_count": neutral_count,
        "buy_turnover": round(buy_turnover, 2),
        "sell_turnover": round(sell_turnover, 2),
        "net_turnover": round(net_turnover, 2),
        "buy_sell_ratio": round(buy_sell_ratio, 2),
        "total_count": total_count,
        "time_range_start": time_range_start,
        "time_range_end": time_range_end,
        "trend_direction": trend_direction,
        "first_half_ratio": round(first_half_ratio, 4),
        "second_half_ratio": round(second_half_ratio, 4),
        "timeline": calc_buy_sell_timeline(records),
    }

    # 附加 Scalping Delta 交叉验证信息
    if scalping_delta is not None:
        details["scalping_delta"] = round(scalping_delta, 2)
        details["scalping_delta_direction"] = scalping_delta_direction or "neutral"
    if delta_cross_note:
        details["delta_cross_note"] = delta_cross_note

    desc = _buy_sell_description(score, buy_sell_ratio)
    return TickerDimensionSignal(
        name="主动买卖",
        signal=_score_to_signal(score),
        score=round(score, 1),
        description=desc,
        details=details,
    )



def _buy_sell_description(score: float, ratio: float) -> str:
    if score > 25:
        return f"主动买入力量占优，力量比 {ratio:.2f}"
    if score > 10:
        return f"主动买入略强，力量比 {ratio:.2f}"
    if score > -10:
        return "主动买卖力量均衡"
    if score > -25:
        return f"主动卖出略强，力量比 {ratio:.2f}"
    return f"主动卖出力量占优，力量比 {ratio:.2f}"


def analyze_big_order_ratio(
    records: List[TickerRecord], min_order_amount: float,
) -> TickerDimensionSignal:
    """大单成交占比分析：按阈值筛选大单，计算占比、买卖金额和评分。"""
    if not records:
        return _empty_signal("大单占比", {
            "big_order_count": 0, "big_order_turnover": 0.0, "total_turnover": 0.0,
            "big_order_pct": 0.0, "big_buy_turnover": 0.0,
            "big_sell_turnover": 0.0, "big_net_buy": 0.0,
        })

    total_turnover = sum(r.turnover for r in records)
    big_buy_turnover = 0.0
    big_sell_turnover = 0.0
    big_order_count = 0
    big_order_turnover = 0.0

    for r in records:
        if r.turnover >= min_order_amount:
            big_order_count += 1
            big_order_turnover += r.turnover
            if r.direction == "BUY":
                big_buy_turnover += r.turnover
            elif r.direction == "SELL":
                big_sell_turnover += r.turnover

    big_order_pct = (
        big_order_turnover / total_turnover * 100 if total_turnover > 0 else 0.0
    )
    big_net_buy = big_buy_turnover - big_sell_turnover

    # 评分：大单净买入占大单总额的比例 × 占比权重
    if big_order_turnover > 0:
        direction_factor = big_net_buy / big_order_turnover  # -1 ~ 1
        pct_factor = min(big_order_pct / 50.0, 1.0)  # 占比越高影响越大
        score = direction_factor * pct_factor * 100
    else:
        score = 0.0
    score = _clamp(score)

    details: Dict[str, Any] = {
        "big_order_count": big_order_count,
        "big_order_turnover": round(big_order_turnover, 2),
        "total_turnover": round(total_turnover, 2),
        "big_order_pct": round(big_order_pct, 2),
        "big_buy_turnover": round(big_buy_turnover, 2),
        "big_sell_turnover": round(big_sell_turnover, 2),
        "big_net_buy": round(big_net_buy, 2),
    }

    desc = _big_order_description(score, big_order_pct)
    return TickerDimensionSignal(
        name="大单占比",
        signal=_score_to_signal(score),
        score=round(score, 1),
        description=desc,
        details=details,
    )


def _big_order_description(score: float, pct: float) -> str:
    if pct < 5:
        return "大单成交极少，散户主导"
    if score > 25:
        return f"大单净买入明显，占比 {pct:.1f}%"
    if score > 10:
        return f"大单偏买入，占比 {pct:.1f}%"
    if score > -10:
        return f"大单买卖均衡，占比 {pct:.1f}%"
    if score > -25:
        return f"大单偏卖出，占比 {pct:.1f}%"
    return f"大单净卖出明显，占比 {pct:.1f}%"


def _empty_signal(name: str, details: Dict[str, Any]) -> TickerDimensionSignal:
    """空记录列表时返回中性信号"""
    return TickerDimensionSignal(
        name=name, signal="neutral", score=0.0,
        description="无成交数据", details=details,
    )
