#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置策略 — 网格搜索评分与评估

从 grid_optimizer.py 提取：
- calculate_composite_score: 综合评分函数
- generate_range: 浮点数范围生成
- _build_dynamic_range: 基于统计数据的动态搜索范围
- _evaluate_zone_trades: 区间交易结果评估
"""

from typing import Any, Dict, List, Optional

from .constants import (
    ScoringWeights,
    TradeParams,
)


# ========== 综合评分函数 ==========

def calculate_composite_score(
    avg_net_profit: float,
    win_rate: float,
    stop_loss_rate: float,
    profit_spread: float,
    weights: Optional[ScoringWeights] = None,
) -> float:
    """
    综合评分，替代单一 avg_net_profit 作为优化目标。

    公式：
        score = w1 * norm(avg_net_profit)
              + w2 * norm(win_rate)
              - w3 * norm(stop_loss_rate)
              + w4 * norm(profit_spread)

    当 stop_loss_rate > 50% 时，施加额外 0.5 惩罚系数。

    归一化方式：
    - avg_net_profit: 除以 5.0（假设 5% 为优秀水平）
    - win_rate: 除以 100.0
    - stop_loss_rate: 除以 100.0
    - profit_spread: 除以 5.0

    Args:
        avg_net_profit: 平均净盈亏（%）
        win_rate: 胜率（%，0-100）
        stop_loss_rate: 止损率（%，0-100）
        profit_spread: 利润空间（buy_dip + sell_rise）
        weights: 权重配置

    Returns:
        综合评分（越高越好）
    """
    if weights is None:
        weights = ScoringWeights()

    # 归一化
    norm_profit = avg_net_profit / 5.0
    norm_win = win_rate / 100.0
    norm_sl = stop_loss_rate / 100.0
    norm_spread = profit_spread / 5.0

    score = (
        weights.net_profit_weight * norm_profit
        + weights.win_rate_weight * norm_win
        - weights.stop_loss_penalty_weight * norm_sl
        + weights.profit_spread_bonus_weight * norm_spread
    )

    # 止损率 > 50% 时施加惩罚
    if stop_loss_rate > 50.0:
        score *= 0.5

    return round(score, 6)


# ========== 辅助函数 ==========

def generate_range(low: float, high: float, step: float) -> List[float]:
    """生成浮点数范围列表"""
    result = []
    val = low
    while val <= high + step * 0.01:
        result.append(round(val, 4))
        val += step
    return result if result else [round(low, 4)]


def _build_dynamic_range(
    stats: Dict[str, Any],
    stat_key: str,
    min_floor: float,
    step: float = 0.25,
) -> List[float]:
    """
    基于区间统计数据动态生成搜索范围。

    Args:
        stats: rise_stats 或 drop_stats
        stat_key: 'rise' 或 'drop'（决定取绝对值的方式）
        min_floor: 搜索范围的最低下限
        step: 步长
    """
    p25 = abs(stats.get('p25', 0))
    p75 = abs(stats.get('p75', 0))
    median = abs(stats.get('median', 0))

    if stat_key == 'drop':
        # 跌幅：P75 较小，P25 较大
        low = max(min_floor, min(p75, median * 0.5))
        high = max(low + 0.5, p25 * 1.2)
    else:
        # 涨幅：P25 较小，P75 较大
        low = max(min_floor, min(p25, median * 0.5))
        high = max(low + 0.5, p75 * 1.2)

    return generate_range(low, high, step)


def _evaluate_zone_trades(
    zone_trades: List[Dict[str, Any]],
    buy_dip: float,
    sell_rise: float,
    sl_pct: float,
    weights: Optional[ScoringWeights] = None,
) -> Optional[Dict[str, Any]]:
    """
    评估某区间的交易结果，返回指标字典。

    Returns:
        指标字典，或 None（交易数为 0）
    """
    total = len(zone_trades)
    if total == 0:
        return None

    avg_net = sum(t['net_profit_pct'] for t in zone_trades) / total
    win_count = len([t for t in zone_trades if t['net_profit_pct'] > 0])
    win_rate = win_count / total * 100
    sl_count = len([t for t in zone_trades if t['exit_type'] == 'stop_loss'])
    sl_rate = sl_count / total * 100
    spread = buy_dip + sell_rise

    score = calculate_composite_score(avg_net, win_rate, sl_rate, spread, weights)

    return {
        'params': TradeParams(
            buy_dip_pct=round(buy_dip, 4),
            sell_rise_pct=round(sell_rise, 4),
            stop_loss_pct=sl_pct,
        ),
        'composite_score': score,
        'avg_net_profit': round(avg_net, 4),
        'win_rate': round(win_rate, 2),
        'trades_count': total,
        'stop_loss_rate': round(sl_rate, 2),
        'profit_spread': round(spread, 4),
    }
