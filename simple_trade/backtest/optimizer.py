"""
回测参数优化器

负责参数优化，支持多种优化模式：
- 单维度优化：固定其他参数，测试单个维度
- 双维度优化：测试两个维度的组合
- 全量优化：测试所有参数组合

优化策略：
1. 基准测试
2. 单维度优化（找到每个维度的最优值）
3. Top-K组合测试
4. 全量网格搜索（可选）
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from itertools import product
import pandas as pd
from datetime import datetime

from simple_trade.backtest.core.engine import BacktestEngine
from simple_trade.backtest.core.data_loader import BacktestDataLoader
from simple_trade.backtest.core.analyzer import BacktestAnalyzer
from simple_trade.backtest.strategies.base_strategy import BaseBacktestStrategy


class ParameterOptimizer:
    """
    参数优化器

    支持多种优化模式，找到最优参数组合。
    """

    def __init__(
        self,
        strategy_class: type,
        data_loader: BacktestDataLoader,
        start_date: str,
        end_date: str,
        base_params: Dict[str, Any]
    ):
        """
        初始化参数优化器

        Args:
            strategy_class: 策略类（非实例）
            data_loader: 数据加载器
            start_date: 回测开始日期
            end_date: 回测结束日期
            base_params: 基准参数
        """
        self.strategy_class = strategy_class
        self.data_loader = data_loader
        self.start_date = start_date
        self.end_date = end_date
        self.base_params = base_params
        self.analyzer = BacktestAnalyzer()
        self.logger = logging.getLogger(__name__)

        # 优化结果
        self.results: List[Dict[str, Any]] = []

    def run_single_test(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        运行单次回测

        Args:
            params: 策略参数

        Returns:
            回测结果（包含参数和统计指标）
        """
        self.logger.info(f"测试参数组合: {params}")

        # 创建策略实例
        strategy = self.strategy_class(**params)

        # 创建回测引擎
        engine = BacktestEngine(
            strategy=strategy,
            data_loader=self.data_loader,
            start_date=self.start_date,
            end_date=self.end_date
        )

        # 运行回测
        result = engine.run()

        # 分析结果
        analysis = self.analyzer.analyze(result.signals)

        # 合并参数和结果
        return {
            'params': params,
            'result': result,
            'analysis': analysis
        }

    def optimize_baseline(self) -> Dict[str, Any]:
        """
        基准测试

        测试基准参数组合。

        Returns:
            基准测试结果
        """
        self.logger.info("=" * 80)
        self.logger.info("开始基准测试")
        self.logger.info("=" * 80)

        result = self.run_single_test(self.base_params)
        self.results.append(result)

        self.logger.info(f"基准测试完成: 胜率={result['analysis']['win_rate']:.2f}%")
        return result

    def optimize_single_dimension(
        self,
        param_name: str,
        param_values: List[Any]
    ) -> List[Dict[str, Any]]:
        """
        单维度优化

        固定其他参数，测试单个参数的不同值。

        Args:
            param_name: 参数名称
            param_values: 参数值列表

        Returns:
            所有测试结果
        """
        self.logger.info("=" * 80)
        self.logger.info(f"单维度优化: {param_name}")
        self.logger.info(f"测试值: {param_values}")
        self.logger.info("=" * 80)

        results = []
        for value in param_values:
            # 复制基准参数
            params = self.base_params.copy()
            params[param_name] = value

            # 运行测试
            result = self.run_single_test(params)
            results.append(result)
            self.results.append(result)

        # 找出最优值
        best_result = max(results, key=lambda x: x['analysis']['win_rate'])
        self.logger.info(
            f"{param_name} 最优值: {best_result['params'][param_name]} "
            f"(胜率={best_result['analysis']['win_rate']:.2f}%)"
        )

        return results

    def optimize_all_single_dimensions(
        self,
        param_grid: Dict[str, List[Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        所有维度的单维度优化

        Args:
            param_grid: 参数网格 {参数名: 值列表}

        Returns:
            每个维度的最优结果
        """
        self.logger.info("=" * 80)
        self.logger.info("开始所有维度的单维度优化")
        self.logger.info("=" * 80)

        best_params = {}
        for param_name, param_values in param_grid.items():
            # 跳过只有一个值的参数
            if len(param_values) <= 1:
                continue

            # 单维度优化
            results = self.optimize_single_dimension(param_name, param_values)

            # 找出最优值
            best_result = max(results, key=lambda x: x['analysis']['win_rate'])
            best_params[param_name] = {
                'value': best_result['params'][param_name],
                'win_rate': best_result['analysis']['win_rate'],
                'result': best_result
            }

        return best_params

    def optimize_grid_search(
        self,
        param_grid: Dict[str, List[Any]],
        max_combinations: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        网格搜索

        测试所有参数组合（或指定数量的组合）。

        Args:
            param_grid: 参数网格
            max_combinations: 最大组合数（None表示测试所有）

        Returns:
            所有测试结果
        """
        # 生成所有参数组合
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        all_combinations = list(product(*param_values))

        total = len(all_combinations)
        self.logger.info("=" * 80)
        self.logger.info(f"网格搜索: 总共 {total} 种组合")
        if max_combinations:
            self.logger.info(f"限制: 只测试前 {max_combinations} 种组合")
        self.logger.info("=" * 80)

        # 限制组合数
        if max_combinations:
            all_combinations = all_combinations[:max_combinations]

        results = []
        for i, combination in enumerate(all_combinations, 1):
            # 构建参数字典
            params = dict(zip(param_names, combination))

            self.logger.info(f"[{i}/{len(all_combinations)}] 测试组合: {params}")

            # 运行测试
            result = self.run_single_test(params)
            results.append(result)
            self.results.append(result)

        return results

    def get_best_params(
        self,
        by: str = 'win_rate',
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        获取最优参数组合

        Args:
            by: ���序依据（'win_rate', 'avg_rise', 'balanced'）
            top_k: 返回前k个结果

        Returns:
            最优参数组合列表
        """
        if not self.results:
            return []

        # 排序
        if by == 'win_rate':
            sorted_results = sorted(
                self.results,
                key=lambda x: x['analysis']['win_rate'],
                reverse=True
            )
        elif by == 'avg_rise':
            sorted_results = sorted(
                self.results,
                key=lambda x: x['analysis']['avg_rise'],
                reverse=True
            )
        elif by == 'balanced':
            # 综合评分：胜率60% + 平均涨幅40%
            sorted_results = sorted(
                self.results,
                key=lambda x: (
                    x['analysis']['win_rate'] * 0.6 +
                    x['analysis']['avg_rise'] * 4.0  # 归一化到0-100
                ),
                reverse=True
            )
        else:
            sorted_results = self.results

        return sorted_results[:top_k]

    def export_results(self, output_path: str):
        """
        导出所有优化结果

        Args:
            output_path: 输出文件路径（CSV格式）
        """
        if not self.results:
            self.logger.warning("没有结果可导出")
            return

        # 准备数据
        rows = []
        for result in self.results:
            row = {}
            # 参数
            for key, value in result['params'].items():
                row[key] = value
            # 统计指标
            analysis = result['analysis']
            row.update({
                'total_signals': analysis['total_signals'],
                'rise_count': analysis['rise_count'],
                'win_rate': analysis['win_rate'],
                'avg_rise': analysis['avg_rise'],
                'max_rise': analysis['max_rise'],
                'avg_days_to_peak': analysis['avg_days_to_peak']
            })
            rows.append(row)

        # 保存为CSV
        df = pd.DataFrame(rows)
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        self.logger.info(f"优化结果已导出到: {output_path}")

    def export_best_params(self, output_path: str):
        """
        导出最优参数

        Args:
            output_path: 输出文件路径（JSON格式）
        """
        best_by_win_rate = self.get_best_params(by='win_rate', top_k=1)
        best_by_avg_rise = self.get_best_params(by='avg_rise', top_k=1)
        best_balanced = self.get_best_params(by='balanced', top_k=1)

        output = {
            'best_by_win_rate': {
                'params': best_by_win_rate[0]['params'] if best_by_win_rate else {},
                'win_rate': best_by_win_rate[0]['analysis']['win_rate'] if best_by_win_rate else 0,
                'total_signals': best_by_win_rate[0]['analysis']['total_signals'] if best_by_win_rate else 0
            },
            'best_by_avg_rise': {
                'params': best_by_avg_rise[0]['params'] if best_by_avg_rise else {},
                'avg_rise': best_by_avg_rise[0]['analysis']['avg_rise'] if best_by_avg_rise else 0,
                'win_rate': best_by_avg_rise[0]['analysis']['win_rate'] if best_by_avg_rise else 0
            },
            'best_balanced': {
                'params': best_balanced[0]['params'] if best_balanced else {},
                'win_rate': best_balanced[0]['analysis']['win_rate'] if best_balanced else 0,
                'avg_rise': best_balanced[0]['analysis']['avg_rise'] if best_balanced else 0
            }
        }

        import json
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        self.logger.info(f"最优参数已导出到: {output_path}")
