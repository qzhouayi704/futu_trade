#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐笔成交分析 - 维度3（密集价位）和维度4（成交节奏）"""

from collections import defaultdict
from typing import Any, Dict, List

from ..order_book.order_book_analyzer import _clamp, _score_to_signal
from .ticker_analyzer import TickerDimensionSignal
from .ticker_service import TickerRecord


def _empty_signal(name: str, details: Dict[str, Any]) -> TickerDimensionSignal:
    return TickerDimensionSignal(
        name=name, signal="neutral", score=0.0,
        description="无成交数据", details=details,
    )


def analyze_volume_clusters(
    records: List[TickerRecord], current_price: float,
) -> TickerDimensionSignal:
    """成交密集价位分析：按价格分组统计，取 top 3 密集区，标记支撑/阻力。"""
    if not records:
        return _empty_signal("密集价位", {"clusters": [], "cluster_count": 0})

    groups: Dict[float, Dict[str, Any]] = defaultdict(
        lambda: {"volume": 0, "turnover": 0.0, "buy": 0, "sell": 0, "neutral": 0}
    )
    for r in records:
        g = groups[r.price]
        g["volume"] += r.volume
        g["turnover"] += r.turnover
        if r.direction == "BUY":
            g["buy"] += 1
        elif r.direction == "SELL":
            g["sell"] += 1
        else:
            g["neutral"] += 1

    sorted_prices = sorted(groups.keys(), key=lambda p: groups[p]["volume"], reverse=True)
    top_prices = sorted_prices[:3]

    clusters = []
    for price in top_prices:
        g = groups[price]
        total = g["buy"] + g["sell"] + g["neutral"] or 1
        buy_pct = g["buy"] / total
        sell_pct = g["sell"] / total
        neutral_pct = g["neutral"] / total

        if price < current_price:
            cluster_type = "support"
        elif price > current_price:
            cluster_type = "resistance"
        else:
            cluster_type = "current"

        clusters.append({
            "price": price, "volume": g["volume"],
            "turnover": round(g["turnover"], 2),
            "buy_pct": round(buy_pct, 4), "sell_pct": round(sell_pct, 4),
            "neutral_pct": round(neutral_pct, 4), "type": cluster_type,
        })

    score = _cluster_score(clusters, current_price)
    desc = _cluster_description(clusters, current_price)
    return TickerDimensionSignal(
        name="密集价位", signal=_score_to_signal(score),
        score=round(score, 1), description=desc,
        details={"clusters": clusters, "cluster_count": len(clusters)},
    )


def _cluster_score(clusters: list, current_price: float) -> float:
    if not clusters:
        return 0.0
    score = 0.0
    for c in clusters:
        if c["type"] == "support":
            score += (c["buy_pct"] - c["sell_pct"]) * 40
        elif c["type"] == "resistance":
            score -= (c["sell_pct"] - c["buy_pct"]) * 40
        else:
            score += (c["buy_pct"] - c["sell_pct"]) * 20
    return _clamp(score)


def _cluster_description(clusters: list, current_price: float) -> str:
    support = [c for c in clusters if c["type"] == "support"]
    resistance = [c for c in clusters if c["type"] == "resistance"]
    if support and not resistance:
        return f"下方 {len(support)} 个密集支撑区"
    if resistance and not support:
        return f"上方 {len(resistance)} 个密集阻力区"
    if support and resistance:
        return f"上下均有密集成交区（支撑 {len(support)} / 阻力 {len(resistance)}）"
    return "成交集中在当前价位附近"


def analyze_trade_rhythm(
    records: List[TickerRecord],
) -> TickerDimensionSignal:
    """成交节奏变化分析：宏观（1分钟）+ 微观（10秒）双窗口。
    最终评分 = 宏观 70% + 微观 30%。
    """
    if not records:
        return _empty_signal("成交节奏", {
            "window_count": 0, "latest_window_count": 0,
            "prev_window_count": 0, "change_rate": 0.0,
            "pattern": "平稳", "latest_window_turnover": 0.0,
            "prev_window_turnover": 0.0, "micro_pattern": "平稳",
        })

    windows: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "turnover": 0.0}
    )
    for r in records:
        w = windows[r.time[:16]]
        w["count"] += 1
        w["turnover"] += r.turnover

    window_keys = sorted(windows.keys())
    window_count = len(window_keys)

    if window_count <= 1:
        w = windows[window_keys[0]] if window_keys else {"count": 0, "turnover": 0.0}
        return TickerDimensionSignal(
            name="成交节奏", signal=_score_to_signal(0), score=0.0,
            description="平稳", details={
                "window_count": window_count, "latest_window_count": w["count"],
                "prev_window_count": 0, "change_rate": 0.0, "pattern": "平稳",
                "latest_window_turnover": round(w["turnover"], 2),
                "prev_window_turnover": 0.0, "micro_pattern": "平稳",
            },
        )

    latest = windows[window_keys[-1]]
    prev = windows[window_keys[-2]]
    change_rate = (latest["count"] - prev["count"]) / prev["count"] if prev["count"] > 0 else 0.0
    macro_score = _clamp(change_rate * 50)
    micro_score, micro_pattern = _calc_micro_rhythm(records)

    pattern = _rhythm_pattern(change_rate)
    score = _clamp(macro_score * 0.7 + micro_score * 0.3)
    desc = f"{pattern}（{micro_pattern}）" if micro_pattern != "平稳" else pattern

    return TickerDimensionSignal(
        name="成交节奏", signal=_score_to_signal(score),
        score=round(score, 1), description=desc, details={
            "window_count": window_count,
            "latest_window_count": latest["count"],
            "prev_window_count": prev["count"],
            "change_rate": round(change_rate, 4), "pattern": pattern,
            "latest_window_turnover": round(latest["turnover"], 2),
            "prev_window_turnover": round(prev["turnover"], 2),
            "micro_pattern": micro_pattern,
        },
    )


def _calc_micro_rhythm(records: List[TickerRecord]) -> tuple:
    """10 秒微观窗口节奏分析，返回 (score, pattern)"""
    micro_windows: Dict[str, int] = defaultdict(int)
    for r in records:
        micro_key = r.time[:17] + r.time[17] if len(r.time) >= 19 else r.time[:16]
        micro_windows[micro_key] += 1

    micro_keys = sorted(micro_windows.keys())
    if len(micro_keys) < 3:
        return 0.0, "平稳"

    last_3 = [micro_windows[k] for k in micro_keys[-3:]]
    prev_avg = sum(micro_windows[k] for k in micro_keys[:-3]) / max(len(micro_keys) - 3, 1)

    if prev_avg > 0 and last_3[-1] > prev_avg * 3:
        return 40.0, "脉冲放量"
    if last_3[0] < last_3[1] < last_3[2] and last_3[2] > 3:
        return 25.0, "持续放量"
    if last_3[0] > last_3[1] > last_3[2]:
        return -20.0, "持续缩量"
    return 0.0, "平稳"


def _rhythm_pattern(change_rate: float) -> str:
    if change_rate > 0.5:
        return "加速放量"
    if change_rate > 0.2:
        return "温和放量"
    if change_rate > -0.2:
        return "平稳"
    if change_rate > -0.5:
        return "温和缩量"
    return "急剧缩量"
