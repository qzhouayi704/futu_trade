#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置策略 — 多方案对比回测器

包含：
- ComparisonRunner: 多方案对比回测（含日内/次日卖出模式对比）
"""

from typing import Any, Dict, List, Optional

from .constants import (
    PRESET_SCHEMES,
    OptimizationScheme,
    SchemeResult,
    ComparisonReport,
    SellModeMetrics,
    SellModeComparison,
    ScoringWeights,
)
from .grid_optimizer import (
    calculate_composite_score,
    optimize_params_grid,
    optimize_zone_open_type_grid,
)
from .trade_simulator import (
    simulate_trades,
    simulate_trades_next_day,
)


class ComparisonRunner:
    """
    多方案对比回测器。

    对每个方案分别运行网格搜索和模拟交易，
    同时对比日内/次日两种卖出模式，生成对比报告。
    """

    def __init__(
        self,
        strategy: Any,
        metrics: List[Dict[str, Any]],
        zone_stats: Dict[str, Any],
        fee_calculator: Any = None,
        trade_amount: float = 60000.0,
    ):
        self.strategy = strategy
        self.metrics = metrics
        self.zone_stats = zone_stats
        self.fee_calculator = fee_calculator
        self.trade_amount = trade_amount
        self._schemes: List[OptimizationScheme] = []

    def add_scheme(self, scheme: OptimizationScheme) -> None:
        """添加优化方案"""
        self._schemes.append(scheme)

    def load_preset_schemes(self) -> None:
        """加载所有预定义方案"""
        for scheme in PRESET_SCHEMES.values():
            self._schemes.append(scheme)

    def run_comparison(self) -> ComparisonReport:
        """
        执行所有方案的对比回测（含日内/次日卖出模式对比）。

        流程：
        1. 对每个方案运行 optimize_params_grid 获取最优参数
        2. 可选：运行 Zone×OpenType 交叉优化
        3. 使用最优参数分别运行日内和次日模拟
        4. 计算卖出模式对比指标
        5. 基于综合评分选择推荐方案和推荐卖出模式
        """
        report = ComparisonReport()

        for scheme in self._schemes:
            result = self._run_single_scheme(scheme)
            report.scheme_results[scheme.name] = result

            # 统计卖出模式推荐分布
            report.sell_mode_summary[result.recommended_sell_mode] = (
                report.sell_mode_summary.get(result.recommended_sell_mode, 0) + 1
            )

        # 选择推荐方案（综合评分最高）
        if report.scheme_results:
            best_name = max(
                report.scheme_results,
                key=lambda n: report.scheme_results[n].composite_score,
            )
            report.recommended_scheme = best_name

        return report

    def _run_single_scheme(self, scheme: OptimizationScheme) -> SchemeResult:
        """执行单个方案的完整回测流程"""
        # 1. 网格搜索
        grid_results = optimize_params_grid(
            self.strategy, self.metrics, self.zone_stats,
            fee_calculator=self.fee_calculator,
            trade_amount=self.trade_amount,
            min_sell_rise_pct=scheme.min_sell_rise_pct,
            min_buy_dip_pct=scheme.min_buy_dip_pct,
            min_trades=scheme.min_trades,
            scoring_weights=scheme.scoring_weights,
        )

        # 2. 构建交易参数（从 GridSearchResult 转为 dict 格式）
        trade_params = {}
        for zone_name, gr in grid_results.items():
            if gr.best_params:
                trade_params[zone_name] = {
                    'buy_dip_pct': gr.best_params.buy_dip_pct,
                    'sell_rise_pct': gr.best_params.sell_rise_pct,
                    'stop_loss_pct': gr.best_params.stop_loss_pct,
                }
            else:
                trade_params[zone_name] = {
                    'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0,
                }

        # 3. Zone×OpenType 交叉优化（可选）
        zone_ot_params = None
        if scheme.enable_zone_open_type:
            zone_ot_params = optimize_zone_open_type_grid(
                self.strategy, self.metrics, self.zone_stats,
                flat_params=grid_results,
                fee_calculator=self.fee_calculator,
                trade_amount=self.trade_amount,
                min_sell_rise_pct=scheme.min_sell_rise_pct,
                min_buy_dip_pct=scheme.min_buy_dip_pct,
                min_trades=scheme.min_trades,
                scoring_weights=scheme.scoring_weights,
            )

        # 4. 日内模拟
        intraday_trades = simulate_trades(
            self.strategy, self.metrics, trade_params,
            trade_amount=self.trade_amount,
            fee_calculator=self.fee_calculator,
        )

        # 5. 次日模拟
        next_day_trades = simulate_trades_next_day(
            self.strategy, self.metrics, trade_params,
            trade_amount=self.trade_amount,
            fee_calculator=self.fee_calculator,
        )

        # 6. 卖出模式对比
        sell_comparison = _compute_sell_mode_metrics(
            intraday_trades, next_day_trades,
            scheme.min_trades, scheme.scoring_weights,
        )

        # 7. 汇总指标（使用推荐模式的指标）
        if sell_comparison.recommended_mode == 'intraday':
            primary = sell_comparison.intraday
        else:
            primary = sell_comparison.next_day

        return SchemeResult(
            scheme=scheme,
            zone_params=grid_results,
            zone_open_type_params=zone_ot_params,
            trades=intraday_trades,
            next_day_trades=next_day_trades,
            sell_mode_comparison=sell_comparison,
            total_trades=primary.total_trades,
            win_rate=primary.win_rate,
            avg_net_profit=primary.avg_net_profit,
            max_drawdown=primary.max_drawdown,
            stop_loss_rate=primary.stop_loss_rate,
            composite_score=primary.composite_score,
            recommended_sell_mode=sell_comparison.recommended_mode,
        )


# ========== 卖出模式对比 ==========

def _compute_sell_mode_metrics(
    intraday_trades: List[Dict[str, Any]],
    next_day_trades: List[Dict[str, Any]],
    min_trades: int,
    weights: Optional[ScoringWeights] = None,
) -> SellModeComparison:
    """
    计算两种卖出模式的指标对比。

    Args:
        intraday_trades: simulate_trades 的输出
        next_day_trades: simulate_trades_next_day 的输出
        min_trades: 最小交易数门槛
        weights: 综合评分权重

    Returns:
        SellModeComparison 包含两种模式的指标和推荐结果
    """
    intraday_m = _calc_mode_metrics(intraday_trades, weights)
    next_day_m = _calc_mode_metrics(next_day_trades, weights)

    insufficient = next_day_m.total_trades < min_trades

    if insufficient:
        recommended = 'intraday'
    elif intraday_m.composite_score >= next_day_m.composite_score:
        recommended = 'intraday'
    else:
        recommended = 'next_day'

    return SellModeComparison(
        intraday=intraday_m,
        next_day=next_day_m,
        recommended_mode=recommended,
        next_day_insufficient=insufficient,
    )


def _calc_mode_metrics(
    trades: List[Dict[str, Any]],
    weights: Optional[ScoringWeights] = None,
) -> SellModeMetrics:
    """计算单种卖出模式的指标"""
    total = len(trades)
    if total == 0:
        return SellModeMetrics()

    profits = [t['net_profit_pct'] for t in trades]
    avg_net = sum(profits) / total
    win_count = len([p for p in profits if p > 0])
    win_rate = win_count / total * 100
    max_drawdown = min(profits)
    sl_count = len([t for t in trades if t['exit_type'] == 'stop_loss'])
    sl_rate = sl_count / total * 100

    # 利润空间取平均
    spreads = [
        t.get('effective_buy_dip_pct', 0) + t.get('effective_sell_rise_pct', 0)
        for t in trades
    ]
    avg_spread = sum(spreads) / total if spreads else 0

    score = calculate_composite_score(avg_net, win_rate, sl_rate, avg_spread, weights)

    return SellModeMetrics(
        total_trades=total,
        win_rate=round(win_rate, 2),
        avg_net_profit=round(avg_net, 4),
        max_drawdown=round(max_drawdown, 4),
        stop_loss_rate=round(sl_rate, 2),
        composite_score=score,
    )
