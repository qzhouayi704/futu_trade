"""
回测结果分析器

负责分析回测结果，计算各项指标：
- 总信号数
- 胜率
- 平均涨幅
- 最大涨幅
- 涨幅分布
- 参数对比

支持单次回测分析和多参数对比分析。
"""

import pandas as pd
from typing import Dict, List, Optional, Any
import logging


class BacktestAnalyzer:
    """
    回测结果分析器

    分析回测信号，计算统计指标。
    """

    def __init__(self):
        """初始化分析器"""
        self.logger = logging.getLogger(__name__)

    def analyze(self, signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        分析回测结果

        Args:
            signals: 回测信号列表

        Returns:
            分析结果字典
        """
        if not signals:
            return {
                'total_signals': 0,
                'rise_count': 0,
                'fall_count': 0,
                'win_rate': 0.0,
                'avg_rise': 0.0,
                'max_rise': 0.0,
                'min_rise': 0.0,
                'avg_days_to_peak': 0.0,
                'distribution': {}
            }

        # 转换为DataFrame便于分析
        df = pd.DataFrame(signals)

        # 基础统计
        total = len(df)
        rise_count = len(df[df['is_target_reached'] == True])
        fall_count = total - rise_count
        win_rate = (rise_count / total * 100) if total > 0 else 0.0

        # 涨幅统计
        avg_rise = df['max_rise_pct'].mean()
        max_rise = df['max_rise_pct'].max()
        min_rise = df['max_rise_pct'].min()

        # 达到最高点天数统计（只统计成功的）
        success_df = df[df['is_target_reached'] == True]
        avg_days_to_peak = success_df['max_rise_days'].mean() if len(success_df) > 0 else 0.0

        # 涨幅分布
        distribution = self._calculate_distribution(df)

        # 按股票统计
        stock_stats = self._calculate_stock_stats(df)

        return {
            'total_signals': total,
            'rise_count': rise_count,
            'fall_count': fall_count,
            'win_rate': round(win_rate, 2),
            'avg_rise': round(avg_rise, 2),
            'max_rise': round(max_rise, 2),
            'min_rise': round(min_rise, 2),
            'avg_days_to_peak': round(avg_days_to_peak, 2),
            'distribution': distribution,
            'stock_stats': stock_stats
        }

    def _calculate_distribution(self, df: pd.DataFrame) -> Dict[str, int]:
        """
        计算涨幅分布

        Args:
            df: 信号DataFrame

        Returns:
            分布字典
        """
        distribution = {
            '< 0%': 0,
            '0-2%': 0,
            '2-5%': 0,
            '5-10%': 0,
            '> 10%': 0
        }

        for _, row in df.iterrows():
            rise = row['max_rise_pct']
            if rise < 0:
                distribution['< 0%'] += 1
            elif rise < 2:
                distribution['0-2%'] += 1
            elif rise < 5:
                distribution['2-5%'] += 1
            elif rise < 10:
                distribution['5-10%'] += 1
            else:
                distribution['> 10%'] += 1

        return distribution

    def _calculate_stock_stats(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        按股票统计

        Args:
            df: 信号DataFrame

        Returns:
            股票统计字典
        """
        stock_groups = df.groupby('stock_code')

        stock_stats = []
        for stock_code, group in stock_groups:
            total = len(group)
            success = len(group[group['is_target_reached'] == True])
            win_rate = (success / total * 100) if total > 0 else 0.0

            stock_stats.append({
                'stock_code': stock_code,
                'stock_name': group.iloc[0]['stock_name'],
                'total_signals': total,
                'success_count': success,
                'win_rate': round(win_rate, 2),
                'avg_rise': round(group['max_rise_pct'].mean(), 2)
            })

        # 按胜率排序
        stock_stats.sort(key=lambda x: x['win_rate'], reverse=True)

        return stock_stats

    def compare_params(self, results: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        对比不同参数组合的效果

        Args:
            results: 多组回测结果

        Returns:
            对比DataFrame
        """
        if not results:
            return pd.DataFrame()

        # 提取关键指标
        comparison = []
        for result in results:
            params = result.get('params', {})
            analysis = result.get('analysis', {})

            comparison.append({
                'lookback_days': params.get('lookback_days', 0),
                'turnover_threshold': params.get('turnover_threshold', 0),
                'target_rise': params.get('target_rise', 0),
                'holding_days': params.get('holding_days', 0),
                'tolerance': params.get('low_position_tolerance', 0),
                'total_signals': analysis.get('total_signals', 0),
                'win_rate': analysis.get('win_rate', 0),
                'avg_rise': analysis.get('avg_rise', 0),
                'max_rise': analysis.get('max_rise', 0),
                'avg_days_to_peak': analysis.get('avg_days_to_peak', 0)
            })

        df = pd.DataFrame(comparison)

        # 按胜率排序
        df = df.sort_values('win_rate', ascending=False)

        return df

    def find_best_params(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        找到最优参数组合

        Args:
            results: 多组回测结果

        Returns:
            最优参数字典
        """
        if not results:
            return {}

        # 按不同指标找最优
        best_by_win_rate = max(results, key=lambda x: x.get('analysis', {}).get('win_rate', 0))
        best_by_avg_rise = max(results, key=lambda x: x.get('analysis', {}).get('avg_rise', 0))

        # 综合评分：胜率60% + 平均涨幅40%
        def calc_score(result):
            analysis = result.get('analysis', {})
            win_rate = analysis.get('win_rate', 0)
            avg_rise = analysis.get('avg_rise', 0)
            return win_rate * 0.6 + avg_rise * 0.4

        best_balanced = max(results, key=calc_score)

        return {
            'best_by_win_rate': {
                'params': best_by_win_rate.get('params', {}),
                'analysis': best_by_win_rate.get('analysis', {})
            },
            'best_by_avg_rise': {
                'params': best_by_avg_rise.get('params', {}),
                'analysis': best_by_avg_rise.get('analysis', {})
            },
            'best_balanced': {
                'params': best_balanced.get('params', {}),
                'analysis': best_balanced.get('analysis', {}),
                'score': round(calc_score(best_balanced), 2)
            }
        }
