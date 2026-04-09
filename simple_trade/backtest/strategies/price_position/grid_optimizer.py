#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置策略 — 网格搜索优化器

包含：
- optimize_params_grid: 增强版网格搜索（含参数下限约束、综合评分、min_trades 降级）
- optimize_zone_open_type_grid: Zone×OpenType 交叉参数优化

评分与评估函数已提取到 grid_scorer.py。
"""

from typing import Any, Dict, List, Optional

from .constants import (
    ZONE_NAMES,
    OPEN_TYPE_GAP_UP,
    OPEN_TYPE_GAP_DOWN,
    OPEN_TYPE_FLAT,
    ScoringWeights,
    TradeParams,
    SearchConfig,
    SearchStats,
    GridSearchResult,
    OpenTypeGridResult,
)
from .trade_simulator import (
    simulate_trades,
)
# 评分与评估函数（向后兼容：仍可从此模块导入）
from .grid_scorer import (
    calculate_composite_score,
    generate_range,
    _build_dynamic_range,
    _evaluate_zone_trades,
)


# ========== 增强版网格搜索 ==========

def optimize_params_grid(
    strategy: Any,
    metrics: List[Dict[str, Any]],
    zone_stats: Dict[str, Any],
    fee_calculator: Any = None,
    trade_amount: float = 60000.0,
    min_sell_rise_pct: float = 1.0,
    min_buy_dip_pct: float = 0.5,
    min_trades: int = 10,
    scoring_weights: Optional[ScoringWeights] = None,
    stop_loss_range: Optional[List[float]] = None,
) -> Dict[str, GridSearchResult]:
    """
    增强版网格搜索，支持参数下限约束、综合评分、min_trades 降级。

    改进点（相比原版）：
    1. min_sell_rise_pct / min_buy_dip_pct 参数下限约束
    2. 综合评分替代单一 avg_net_profit
    3. min_trades 门槛提升到 10，不足时降级为 5 并标记 degraded
    4. 结果记录 SearchConfig 和 SearchStats（可追溯性）
    5. 返回 GridSearchResult dataclass

    Args:
        strategy: PricePositionStrategy 实例
        metrics: calculate_daily_metrics() 的输出
        zone_stats: compute_zone_statistics() 的输出
        fee_calculator: FeeCalculator 实例
        trade_amount: 每笔交易金额
        min_sell_rise_pct: 卖出涨幅搜索下限（默认 1.0%）
        min_buy_dip_pct: 买入跌幅搜索下限（默认 0.5%）
        min_trades: 最小交易数门槛（默认 10）
        scoring_weights: 综合评分权重
        stop_loss_range: 止损搜索范围

    Returns:
        {zone_name: GridSearchResult}
    """
    if stop_loss_range is None:
        stop_loss_range = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]

    results: Dict[str, GridSearchResult] = {}

    for zone_name in ZONE_NAMES:
        stats = zone_stats.get(zone_name, {})
        if stats.get('count', 0) == 0:
            results[zone_name] = GridSearchResult()
            continue

        # 动态生成搜索范围（施加下限约束）
        buy_range = _build_dynamic_range(
            stats['drop_stats'], 'drop', min_buy_dip_pct,
        )
        sell_range = _build_dynamic_range(
            stats['rise_stats'], 'rise', min_sell_rise_pct,
        )

        best, search_stats = _grid_search_zone(
            strategy, metrics, zone_name,
            buy_range, sell_range, stop_loss_range,
            min_trades, fee_calculator, trade_amount, scoring_weights,
        )

        config = SearchConfig(
            sell_rise_range=sell_range,
            buy_dip_range=buy_range,
            min_trades=best.actual_min_trades if best.best_params else min_trades,
            scoring_weights=scoring_weights or ScoringWeights(),
        )
        best.search_config = config
        best.search_stats = search_stats
        results[zone_name] = best

    return results


def _grid_search_zone(
    strategy: Any,
    metrics: List[Dict[str, Any]],
    zone_name: str,
    buy_range: List[float],
    sell_range: List[float],
    stop_loss_range: List[float],
    min_trades: int,
    fee_calculator: Any,
    trade_amount: float,
    weights: Optional[ScoringWeights],
) -> tuple:
    """
    对单个区间执行网格搜索。

    支持 min_trades 降级：先用 min_trades 搜索，无结果时降级为 5。

    Returns:
        (GridSearchResult, SearchStats)
    """
    stats = SearchStats()
    best_eval = None

    for buy_dip in buy_range:
        for sell_rise in sell_range:
            for sl_pct in stop_loss_range:
                stats.total_combos += 1

                test_params = {
                    zn: {'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0}
                    for zn in ZONE_NAMES
                }
                test_params[zone_name] = {
                    'buy_dip_pct': round(buy_dip, 4),
                    'sell_rise_pct': round(sell_rise, 4),
                    'stop_loss_pct': sl_pct,
                }

                trades = simulate_trades(
                    strategy, metrics, test_params,
                    trade_amount=trade_amount,
                    fee_calculator=fee_calculator,
                )
                zone_trades = [t for t in trades if t['zone'] == zone_name]

                if len(zone_trades) < min_trades:
                    stats.skipped_combos += 1
                    continue

                stats.valid_combos += 1
                ev = _evaluate_zone_trades(
                    zone_trades, buy_dip, sell_rise, sl_pct, weights,
                )
                if ev and (best_eval is None or ev['composite_score'] > best_eval['composite_score']):
                    best_eval = ev

    # 降级逻辑：无有效结果时用 min_trades=5 重试
    degraded = False
    actual_min = min_trades
    if best_eval is None and min_trades > 5:
        degraded = True
        actual_min = 5
        stats_retry = SearchStats()
        for buy_dip in buy_range:
            for sell_rise in sell_range:
                for sl_pct in stop_loss_range:
                    stats_retry.total_combos += 1
                    test_params = {
                        zn: {'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0}
                        for zn in ZONE_NAMES
                    }
                    test_params[zone_name] = {
                        'buy_dip_pct': round(buy_dip, 4),
                        'sell_rise_pct': round(sell_rise, 4),
                        'stop_loss_pct': sl_pct,
                    }
                    trades = simulate_trades(
                        strategy, metrics, test_params,
                        trade_amount=trade_amount,
                        fee_calculator=fee_calculator,
                    )
                    zone_trades = [t for t in trades if t['zone'] == zone_name]
                    if len(zone_trades) < 5:
                        stats_retry.skipped_combos += 1
                        continue
                    stats_retry.valid_combos += 1
                    ev = _evaluate_zone_trades(
                        zone_trades, buy_dip, sell_rise, sl_pct, weights,
                    )
                    if ev and (best_eval is None or ev['composite_score'] > best_eval['composite_score']):
                        best_eval = ev
        # 合并统计
        stats.total_combos += stats_retry.total_combos
        stats.valid_combos += stats_retry.valid_combos
        stats.skipped_combos += stats_retry.skipped_combos

    if best_eval is None:
        return GridSearchResult(), stats

    return GridSearchResult(
        best_params=best_eval['params'],
        composite_score=best_eval['composite_score'],
        avg_net_profit=best_eval['avg_net_profit'],
        win_rate=best_eval['win_rate'],
        trades_count=best_eval['trades_count'],
        stop_loss_rate=best_eval['stop_loss_rate'],
        profit_spread=best_eval['profit_spread'],
        degraded=degraded,
        actual_min_trades=actual_min,
    ), stats


# ========== Zone×OpenType 交叉参数优化 ==========

def optimize_zone_open_type_grid(
    strategy: Any,
    metrics: List[Dict[str, Any]],
    zone_stats: Dict[str, Any],
    flat_params: Dict[str, GridSearchResult],
    fee_calculator: Any = None,
    trade_amount: float = 60000.0,
    min_sell_rise_pct: float = 1.0,
    min_buy_dip_pct: float = 0.5,
    min_trades: int = 10,
    scoring_weights: Optional[ScoringWeights] = None,
    stop_loss_range: Optional[List[float]] = None,
) -> Dict[str, Dict[str, OpenTypeGridResult]]:
    """
    按 Zone × Open_Type 交叉维度优化参数。

    对每个 Zone，分别对 gap_up 和 gap_down 类型的交易日进行独立网格搜索。
    高开日搜索下限 min_sell_rise_pct=1.0%，低开日搜索下限 min_sell_rise_pct=0.75%。
    若某组合样本不足 min_trades，回退使用该 Zone 的 flat 参数。

    Args:
        strategy: PricePositionStrategy 实例
        metrics: calculate_daily_metrics() 的输出
        zone_stats: compute_zone_statistics() 的输出
        flat_params: 各区间的 flat 参数（optimize_params_grid 的输出）
        fee_calculator: FeeCalculator 实例
        trade_amount: 每笔交易金额
        min_sell_rise_pct: 基础卖出涨幅下限
        min_buy_dip_pct: 买入跌幅下限
        min_trades: 最小交易数门槛
        scoring_weights: 综合评分权重
        stop_loss_range: 止损搜索范围

    Returns:
        {zone_name: {open_type: OpenTypeGridResult}}
    """
    if stop_loss_range is None:
        stop_loss_range = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]

    results: Dict[str, Dict[str, OpenTypeGridResult]] = {}

    for zone_name in ZONE_NAMES:
        stats = zone_stats.get(zone_name, {})
        zone_results: Dict[str, OpenTypeGridResult] = {}

        if stats.get('count', 0) == 0:
            for ot in [OPEN_TYPE_GAP_UP, OPEN_TYPE_GAP_DOWN]:
                zone_results[ot] = OpenTypeGridResult()
            results[zone_name] = zone_results
            continue

        # 按开盘类型过滤 metrics
        gap_up_metrics = [m for m in metrics if m['zone'] == zone_name and m.get('open_type') == OPEN_TYPE_GAP_UP]
        gap_down_metrics = [m for m in metrics if m['zone'] == zone_name and m.get('open_type') == OPEN_TYPE_GAP_DOWN]

        # 高开日优化（min_sell_rise_pct=1.0%）
        zone_results[OPEN_TYPE_GAP_UP] = _optimize_open_type(
            strategy, gap_up_metrics, zone_name, stats,
            max(min_sell_rise_pct, 1.0), min_buy_dip_pct,
            min_trades, scoring_weights, stop_loss_range,
            fee_calculator, trade_amount,
            flat_params.get(zone_name),
        )

        # 低开日优化（min_sell_rise_pct=0.75%）
        zone_results[OPEN_TYPE_GAP_DOWN] = _optimize_open_type(
            strategy, gap_down_metrics, zone_name, stats,
            max(min_sell_rise_pct, 0.75), min_buy_dip_pct,
            min_trades, scoring_weights, stop_loss_range,
            fee_calculator, trade_amount,
            flat_params.get(zone_name),
        )

        results[zone_name] = zone_results

    return results


def _optimize_open_type(
    strategy: Any,
    filtered_metrics: List[Dict[str, Any]],
    zone_name: str,
    zone_stats: Dict[str, Any],
    min_sell_rise: float,
    min_buy_dip: float,
    min_trades: int,
    weights: Optional[ScoringWeights],
    stop_loss_range: List[float],
    fee_calculator: Any,
    trade_amount: float,
    flat_result: Optional[GridSearchResult],
) -> OpenTypeGridResult:
    """
    对单个 Zone × OpenType 组合执行网格搜索。

    样本不足时回退到 flat 参数。
    """
    if len(filtered_metrics) < min_trades:
        # 样本不足，回退到 flat 参数
        if flat_result and flat_result.best_params:
            return OpenTypeGridResult(
                best_params=flat_result.best_params,
                composite_score=flat_result.composite_score,
                avg_net_profit=flat_result.avg_net_profit,
                win_rate=flat_result.win_rate,
                trades_count=flat_result.trades_count,
                stop_loss_rate=flat_result.stop_loss_rate,
                fallback_to_flat=True,
            )
        return OpenTypeGridResult(fallback_to_flat=True)

    # 动态生成搜索范围
    buy_range = _build_dynamic_range(zone_stats['drop_stats'], 'drop', min_buy_dip)
    sell_range = _build_dynamic_range(zone_stats['rise_stats'], 'rise', min_sell_rise)

    best_eval = None
    search_stats = SearchStats()

    for buy_dip in buy_range:
        for sell_rise in sell_range:
            for sl_pct in stop_loss_range:
                search_stats.total_combos += 1

                # 使用过滤后的 metrics 进行模拟
                test_params = {
                    zn: {'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0}
                    for zn in ZONE_NAMES
                }
                test_params[zone_name] = {
                    'buy_dip_pct': round(buy_dip, 4),
                    'sell_rise_pct': round(sell_rise, 4),
                    'stop_loss_pct': sl_pct,
                }

                trades = simulate_trades(
                    strategy, filtered_metrics, test_params,
                    trade_amount=trade_amount,
                    fee_calculator=fee_calculator,
                )
                zone_trades = [t for t in trades if t['zone'] == zone_name]

                if len(zone_trades) < min_trades:
                    search_stats.skipped_combos += 1
                    continue

                search_stats.valid_combos += 1
                ev = _evaluate_zone_trades(
                    zone_trades, buy_dip, sell_rise, sl_pct, weights,
                )
                if ev and (best_eval is None or ev['composite_score'] > best_eval['composite_score']):
                    best_eval = ev

    if best_eval is None:
        # 搜索无结果，回退到 flat
        if flat_result and flat_result.best_params:
            return OpenTypeGridResult(
                best_params=flat_result.best_params,
                composite_score=flat_result.composite_score,
                avg_net_profit=flat_result.avg_net_profit,
                win_rate=flat_result.win_rate,
                trades_count=flat_result.trades_count,
                stop_loss_rate=flat_result.stop_loss_rate,
                fallback_to_flat=True,
                search_stats=search_stats,
            )
        return OpenTypeGridResult(fallback_to_flat=True, search_stats=search_stats)

    return OpenTypeGridResult(
        best_params=best_eval['params'],
        composite_score=best_eval['composite_score'],
        avg_net_profit=best_eval['avg_net_profit'],
        win_rate=best_eval['win_rate'],
        trades_count=best_eval['trades_count'],
        stop_loss_rate=best_eval['stop_loss_rate'],
        fallback_to_flat=False,
        search_stats=search_stats,
    )
