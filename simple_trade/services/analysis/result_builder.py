#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析结果构建器

将 GridSearchResult / OpenTypeGridResult 等 dataclass 转换为前端兼容的 dict 格式。
从 analysis_service.py 中提取，保持主服务文件精简。
"""

from typing import Any, Dict

from ...backtest.strategies.price_position.constants import (
    ZONE_NAMES,
    OPEN_TYPE_GAP_UP, OPEN_TYPE_FLAT, OPEN_TYPE_GAP_DOWN,
)
from ...backtest.strategies.price_position.trade_simulator import (
    simulate_trades as sim_trades,
)


def build_params_from_grid(
    grid_results: Dict[str, Any],
) -> tuple:
    """
    从 GridSearchResult 字典构建 trade_params 和 best_params_output。

    Returns:
        (trade_params, best_params_output) 二元组
    """
    trade_params: Dict[str, Dict[str, float]] = {}
    best_params_output: Dict[str, Dict[str, Any]] = {}

    for zn in ZONE_NAMES:
        gr = grid_results.get(zn)
        if gr and gr.best_params and gr.best_params.buy_dip_pct > 0:
            bp = gr.best_params
            trade_params[zn] = {
                'buy_dip_pct': bp.buy_dip_pct,
                'sell_rise_pct': bp.sell_rise_pct,
                'stop_loss_pct': bp.stop_loss_pct,
            }
            searched = gr.search_stats.total_combos if gr.search_stats else 0
            best_params_output[zn] = {
                'buy_dip_pct': bp.buy_dip_pct,
                'sell_rise_pct': bp.sell_rise_pct,
                'stop_loss_pct': bp.stop_loss_pct,
                'profit_spread': gr.profit_spread,
                'avg_net_profit': gr.avg_net_profit,
                'win_rate': gr.win_rate,
                'trades_count': gr.trades_count,
                'stop_loss_rate': gr.stop_loss_rate,
                'searched_combos': searched,
                'composite_score': gr.composite_score,
                'degraded': gr.degraded,
            }
        else:
            trade_params[zn] = {'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0}
            searched = gr.search_stats.total_combos if gr and gr.search_stats else 0
            best_params_output[zn] = {
                'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0,
                'profit_spread': 0, 'avg_net_profit': 0, 'win_rate': 0,
                'trades_count': 0, 'stop_loss_rate': 0, 'searched_combos': searched,
                'composite_score': 0, 'degraded': False,
            }

    return trade_params, best_params_output


def build_open_type_stats(
    metrics: list, total: int,
) -> Dict[str, Dict[str, Any]]:
    """构建开盘类型分布统计。"""
    counts = {OPEN_TYPE_GAP_UP: 0, OPEN_TYPE_FLAT: 0, OPEN_TYPE_GAP_DOWN: 0}
    for m in metrics:
        ot = m.get('open_type', OPEN_TYPE_FLAT)
        if ot in counts:
            counts[ot] += 1

    return {
        ot: {
            'count': c,
            'pct': round(c / total * 100, 1) if total > 0 else 0,
        }
        for ot, c in counts.items()
    }


def build_open_type_params(
    ot_grid: Dict[str, Dict[str, Any]],
) -> tuple:
    """
    从 Zone×OpenType 网格结果中聚合出全局 open_type_params。

    策略：对每种开盘类型，取所有区间中 composite_score 最高的参数。

    Returns:
        (open_type_params, enable_open_type_anchor) 二元组
    """
    open_type_params: Dict[str, Dict[str, Any]] = {}
    enable_open_type_anchor = False

    for ot in [OPEN_TYPE_GAP_UP, OPEN_TYPE_GAP_DOWN]:
        best_score = -999.0
        best_result = None
        for zn in ZONE_NAMES:
            zone_ot = ot_grid.get(zn, {})
            result = zone_ot.get(ot)
            if not result or not result.best_params or result.fallback_to_flat:
                continue
            if result.composite_score > best_score:
                best_score = result.composite_score
                best_result = result

        if best_result and best_result.best_params:
            bp = best_result.best_params
            open_type_params[ot] = {
                'buy_dip_pct': bp.buy_dip_pct,
                'sell_rise_pct': bp.sell_rise_pct,
                'stop_loss_pct': bp.stop_loss_pct,
                'avg_net_profit': best_result.avg_net_profit,
                'win_rate': best_result.win_rate,
                'trades_count': best_result.trades_count,
            }
            enable_open_type_anchor = True

    return open_type_params, enable_open_type_anchor


def evaluate_gap_down(
    open_type_params: Dict[str, Any],
    metrics: list,
    trade_params: Dict[str, Dict[str, float]],
    strategy: Any,
    fee_calculator: Any,
    trade_amount: float,
) -> tuple:
    """
    评估低开日是否值得交易。

    Returns:
        (skip_gap_down, gap_down_recommendation) 二元组
    """
    gap_down_metrics = [m for m in metrics if m.get('open_type') == OPEN_TYPE_GAP_DOWN]

    if OPEN_TYPE_GAP_DOWN in open_type_params:
        if open_type_params[OPEN_TYPE_GAP_DOWN].get('avg_net_profit', 0) > 0:
            return False, 'trade'
        return True, 'skip'

    if len(gap_down_metrics) >= 3:
        gd_test = sim_trades(
            strategy, gap_down_metrics, trade_params,
            trade_amount=trade_amount,
            fee_calculator=fee_calculator,
        )
        if gd_test:
            gd_avg = sum(t['net_profit_pct'] for t in gd_test) / len(gd_test)
            if gd_avg > 0:
                return False, 'trade'
    return True, 'skip'


def build_trade_summary(trades: list) -> Dict[str, Any]:
    """从交易记录列表构建汇总统计。"""
    total = len(trades)
    if total == 0:
        return {
            'total_trades': 0, 'win_count': 0, 'win_rate': 0,
            'avg_profit': 0, 'avg_net_profit': 0,
            'max_profit': 0, 'max_loss': 0,
            'stop_loss_count': 0, 'stop_loss_rate': 0,
        }

    profitable = [t for t in trades if t['net_profit_pct'] > 0]
    sl_trades = [t for t in trades if t['exit_type'] == 'stop_loss']
    return {
        'total_trades': total,
        'win_count': len(profitable),
        'win_rate': round(len(profitable) / total * 100, 2),
        'avg_profit': round(sum(t['profit_pct'] for t in trades) / total, 4),
        'avg_net_profit': round(sum(t['net_profit_pct'] for t in trades) / total, 4),
        'max_profit': round(max(t['profit_pct'] for t in trades), 4),
        'max_loss': round(min(t['profit_pct'] for t in trades), 4),
        'stop_loss_count': len(sl_trades),
        'stop_loss_rate': round(len(sl_trades) / total * 100, 2),
    }


def build_open_type_response(
    open_type_params: Dict[str, Any],
    gap_down_recommendation: str,
) -> Dict[str, Any]:
    """构建前端兼容的 open_type_params 响应。"""
    return {
        OPEN_TYPE_GAP_UP: {
            'enabled': OPEN_TYPE_GAP_UP in open_type_params,
            'anchor': 'open_price',
            **(open_type_params.get(OPEN_TYPE_GAP_UP, {})),
        },
        OPEN_TYPE_FLAT: {
            'enabled': True,
            'anchor': 'prev_close',
        },
        OPEN_TYPE_GAP_DOWN: {
            'enabled': OPEN_TYPE_GAP_DOWN in open_type_params and gap_down_recommendation == 'trade',
            'anchor': 'prev_close',
            'recommendation': gap_down_recommendation,
            **(open_type_params.get(OPEN_TYPE_GAP_DOWN, {})),
        },
    }
