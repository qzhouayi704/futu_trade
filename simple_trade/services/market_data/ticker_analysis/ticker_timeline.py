#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
买卖比分时走势计算

按 5 分钟窗口聚合逐笔成交数据，输出每个窗口的买卖力量比，
供前端绘制分时走势图。

5 分钟窗口比 1 分钟窗口样本量更大，力量比更稳定可靠。
"""

from collections import defaultdict
from typing import Any, Dict, List

from .ticker_service import TickerRecord


def _minute_to_5min_key(time_str: str) -> str:
    """将时间字符串转为 5 分钟窗口键。

    输入: "2026-02-25 10:12:52.251" 或 "2026-02-25 10:12"
    输出: "10:10"（向下取整到 5 分钟）
    """
    # 取 HH:MM 部分
    parts = time_str.split(" ")
    hm = parts[1] if len(parts) > 1 else parts[0]
    hm = hm[:5]  # "HH:MM"
    h, m = hm.split(":")
    m_int = int(m)
    m_floor = (m_int // 5) * 5
    return f"{h}:{m_floor:02d}"


def calc_buy_sell_timeline(records: List[TickerRecord]) -> List[Dict[str, Any]]:
    """按 5 分钟窗口聚合，计算每个窗口的买卖力量比。

    Args:
        records: 逐笔成交记录列表（已按时间排序）

    Returns:
        窗口列表，每项包含:
        - time: HH:MM 格式（5 分钟窗口起始时间）
        - buy_turnover / sell_turnover: 买卖金额
        - ratio: 力量比（buy/sell，1.0 = 均衡）
        - trade_count: 窗口内成交笔数
        - cumulative_net: 累计净额
    """
    if not records:
        return []

    # 按 5 分钟窗口分组
    windows: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"buy": 0.0, "sell": 0.0, "count": 0}
    )
    for r in records:
        key = _minute_to_5min_key(r.time)
        windows[key]["count"] += 1
        if r.direction == "BUY":
            windows[key]["buy"] += r.turnover
        elif r.direction == "SELL":
            windows[key]["sell"] += r.turnover

    sorted_keys = sorted(windows.keys())
    if not sorted_keys:
        return []

    timeline: List[Dict[str, Any]] = []
    cumulative = 0.0

    for key in sorted_keys:
        w = windows[key]
        buy_t = w["buy"]
        sell_t = w["sell"]
        count = int(w["count"])
        cumulative += buy_t - sell_t

        # 力量比计算
        if sell_t > 0 and buy_t > 0:
            ratio = buy_t / sell_t
        elif buy_t > 0:
            ratio = 5.0  # 纯买无卖，cap 到 5
        elif sell_t > 0:
            ratio = 0.2  # 纯卖无买，floor 到 0.2
        else:
            ratio = 1.0

        # cap 到合理范围 [0.1, 5.0]
        ratio = max(0.1, min(5.0, ratio))

        timeline.append({
            "time": key,
            "buy_turnover": round(buy_t, 2),
            "sell_turnover": round(sell_t, 2),
            "ratio": round(ratio, 3),
            "trade_count": count,
            "cumulative_net": round(cumulative, 2),
        })

    return timeline
