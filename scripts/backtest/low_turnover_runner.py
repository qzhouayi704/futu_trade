"""
低换手率回测运行器

实现低换手率策略的回测流程
"""

from .base_runner import BaseBacktestRunner
from simple_trade.backtest.core.engine import BacktestEngine
from simple_trade.backtest.core.analyzer import BacktestAnalyzer
from simple_trade.backtest.core.reporter import BacktestReporter
from simple_trade.backtest.strategies.low_turnover_strategy import LowTurnoverStrategy
from simple_trade.backtest.optimizer import ParameterOptimizer


class LowTurnoverRunner(BaseBacktestRunner):
    """低换手率回测运行器"""

    def get_strategy_name(self) -> str:
        """获取策略名称"""
        return "低换手率策略"

    def create_strategy(self) -> LowTurnoverStrategy:
        """创建低换手率策略实例"""
        return LowTurnoverStrategy(
            lookback_days=getattr(self.args, 'lookback', 6),
            turnover_threshold=getattr(self.args, 'turnover', 0.15),
            low_position_tolerance=getattr(self.args, 'tolerance', 1.05),
            target_rise=getattr(self.args, 'target_rise', 5.0),
            holding_days=getattr(self.args, 'holding_days', 3)
        )

    def run_baseline(self):
        """运行基准回测"""
        self.logger.info("开始基准回测")

        # 创建策略
        strategy = self.create_strategy()
        self.logger.info(f"策略：{strategy.get_strategy_name()}")
        self.logger.info(f"参数：{strategy.get_params()}")

        # 创建回测引擎
        engine = BacktestEngine(
            strategy=strategy,
            data_loader=self.data_loader,
            start_date=self.args.start,
            end_date=self.args.end
        )

        # 运行回测
        self.logger.info("正在运行回测...")
        result = engine.run()

        # 分析结果
        self.logger.info("正在分析结果...")
        analyzer = BacktestAnalyzer()
        signals_dict = [s.to_dict() for s in result.signals]
        analysis = analyzer.analyze(signals_dict)

        # 生成报告
        self.logger.info("正在生成报告...")
        reporter = BacktestReporter(output_dir=self.args.output)

        params = {
            'start_date': self.args.start,
            'end_date': self.args.end,
            'market': 'HK',
            'total_stocks': result.stock_count,
            'strategy_name': strategy.get_strategy_name(),
            'strategy_params': strategy.get_params()
        }

        report_files = reporter.generate_report(
            analysis=analysis,
            signals=signals_dict,
            params=params,
            strategy_name=strategy.get_strategy_name()
        )

        for file_type, file_path in report_files.items():
            self.logger.info(f"{file_type}报告已生成：{file_path}")

        # 打印摘要
        self.print_summary(analysis)

    def run_optimization(self):
        """运行参数优化"""
        self.logger.info(f"开始参数优化（模式：{self.args.mode}）")

        # 基准参数
        base_params = {
            'lookback_days': getattr(self.args, 'lookback', 6),
            'turnover_threshold': getattr(self.args, 'turnover', 0.15),
            'low_position_tolerance': getattr(self.args, 'tolerance', 1.05),
            'target_rise': getattr(self.args, 'target_rise', 5.0),
            'holding_days': getattr(self.args, 'holding_days', 3)
        }

        # 创建优化器
        optimizer = ParameterOptimizer(
            strategy_class=LowTurnoverStrategy,
            data_loader=self.data_loader,
            start_date=self.args.start,
            end_date=self.args.end,
            base_params=base_params
        )

        # 定义参数网格
        param_grid = {
            'lookback_days': [6, 8, 10, 12, 15],
            'turnover_threshold': [0.05, 0.08, 0.1, 0.12, 0.15],
            'target_rise': [3.0, 5.0, 8.0, 10.0],
            'holding_days': [3, 5, 7],
            'low_position_tolerance': [1.00, 1.02, 1.05]
        }

        # 运行优化
        if self.args.mode == 'single':
            self.logger.info("运行单维度优化...")
            optimizer.optimize_baseline()
            best_params = optimizer.optimize_all_single_dimensions(param_grid)

            self.logger.info("=" * 80)
            self.logger.info("单维度优化结果")
            self.logger.info("=" * 80)
            for param_name, result in best_params.items():
                self.logger.info(
                    f"{param_name}: {result['value']} "
                    f"(胜率={result['win_rate']:.2f}%)"
                )
        else:  # full
            self.logger.info("运行全量优化（这可能需要很长时间）...")
            max_combinations = 100
            self.logger.info(f"限制为前 {max_combinations} 种组合")
            optimizer.optimize_grid_search(
                param_grid, max_combinations=max_combinations
            )

        # 获取最优参数
        self.logger.info("正在分析优化结果...")
        best_by_win_rate = optimizer.get_best_params(by='win_rate', top_k=1)

        # 导出结果
        import os
        results_csv = os.path.join(self.args.output, 'optimization_results.csv')
        optimizer.export_results(results_csv)
        self.logger.info(f"优化结果已导出：{results_csv}")

        best_params_json = os.path.join(self.args.output, 'best_params.json')
        optimizer.export_best_params(best_params_json)
        self.logger.info(f"最优参数已导出：{best_params_json}")

        # 打印最优参数
        self.logger.info("=" * 80)
        self.logger.info("最优参数（按胜率）")
        self.logger.info("=" * 80)
        if best_by_win_rate:
            result = best_by_win_rate[0]
            self.logger.info(f"参数：{result['params']}")
            self.logger.info(f"胜率：{result['analysis']['win_rate']:.2f}%")
            self.logger.info(f"平均涨幅：{result['analysis']['avg_rise']:.2f}%")
            self.logger.info(f"信号数：{result['analysis']['total_signals']}")
        self.logger.info("=" * 80)
