#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置策略模块

公开接口：
- PricePositionStrategy: 策略主类（延迟导入，向后兼容）
- 数据结构: ScoringWeights, TradeParams, GridSearchResult 等
- ComparisonRunner: 多方案对比回测器
- 报告生成: generate_analysis_report, generate_comparison_report, save_report
- 优化器: calculate_composite_score, optimize_params_grid, optimize_zone_open_type_grid
"""

from .constants import (
    ScoringWeights, TradeParams, SearchConfig, SearchStats,
    GridSearchResult, OpenTypeGridResult, SentimentAdjustResult,
    OptimizationScheme, SchemeResult, SellModeMetrics, SellModeComparison,
    ComparisonReport, PRESET_SCHEMES,
)
from .comparison_runner import (
    ComparisonRunner,
)
from .report_generator import (
    generate_analysis_report, generate_comparison_report, save_report,
)
from .grid_optimizer import (
    calculate_composite_score, optimize_params_grid, optimize_zone_open_type_grid,
)


def __getattr__(name):
    """延迟导入 PricePositionStrategy，避免循环依赖"""
    if name == 'PricePositionStrategy':
        from simple_trade.backtest.strategies.price_position_strategy import PricePositionStrategy
        return PricePositionStrategy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'PricePositionStrategy',
    # 数据结构
    'ScoringWeights', 'TradeParams', 'SearchConfig', 'SearchStats',
    'GridSearchResult', 'OpenTypeGridResult', 'SentimentAdjustResult',
    'OptimizationScheme', 'SchemeResult', 'SellModeMetrics', 'SellModeComparison',
    'ComparisonReport', 'PRESET_SCHEMES',
    # 对比回测
    'ComparisonRunner',
    # 报告生成
    'generate_analysis_report', 'generate_comparison_report', 'save_report',
    # 优化器
    'calculate_composite_score', 'optimize_params_grid', 'optimize_zone_open_type_grid',
]
