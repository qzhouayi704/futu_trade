"""
回测CLI工具模块

提供统一的命令行参数解析和验证功能
"""

import argparse
from typing import Optional
from .date_utils import validate_date_format, validate_date_range


class BacktestCLI:
    """回测命令行工具类"""

    @staticmethod
    def add_common_args(parser: argparse.ArgumentParser):
        """
        添加通用参数

        Args:
            parser: ArgumentParser实例
        """
        # 交互模式
        parser.add_argument(
            '-i', '--interactive',
            action='store_true',
            help='交互式输入参数'
        )

        # 日期范围
        parser.add_argument(
            '--start',
            type=str,
            help='开始日期（格式：YYYY-MM-DD，默认：1年前）'
        )
        parser.add_argument(
            '--end',
            type=str,
            help='结束日期（格式：YYYY-MM-DD，默认：今天）'
        )

        # 输出目录
        parser.add_argument(
            '--output',
            type=str,
            default='backtest_results',
            help='输出目录（默认：backtest_results/）'
        )

        # 优化模式
        parser.add_argument(
            '--optimize',
            action='store_true',
            help='启用参数优化模式'
        )
        parser.add_argument(
            '--mode',
            type=str,
            choices=['single', 'full'],
            default='single',
            help='优化模式：single=单维度优化，full=全量优化（默认：single）'
        )

    @staticmethod
    def add_data_loader_args(parser: argparse.ArgumentParser):
        """
        添加数据加载器参数（已移除API相关参数）

        回测系统只使用数据库中的数据，不再支持API下载。
        如需下载数据，请使用主菜单的"获取K线数据"功能。
        """
        # 不再添加API相关参数
        pass

    @staticmethod
    def add_strategy_args(
        parser: argparse.ArgumentParser,
        strategy_type: str
    ):
        """
        添加策略参数

        Args:
            parser: ArgumentParser实例
            strategy_type: 策略类型（'low_turnover' 或 'intraday'）
        """
        if strategy_type == 'low_turnover':
            BacktestCLI._add_low_turnover_args(parser)
        elif strategy_type == 'intraday':
            BacktestCLI._add_intraday_args(parser)

    @staticmethod
    def _add_low_turnover_args(parser: argparse.ArgumentParser):
        """添加低换手率策略参数"""
        parser.add_argument(
            '--lookback',
            type=int,
            default=6,
            help='低吸位回看天数（默认：6）'
        )
        parser.add_argument(
            '--turnover',
            type=float,
            default=0.15,
            help='换手率阈值，单位百分比（默认：0.15）'
        )
        parser.add_argument(
            '--target-rise',
            type=float,
            default=5.0,
            help='目标涨幅，单位百分比（默认：5.0）'
        )
        parser.add_argument(
            '--holding-days',
            type=int,
            default=3,
            help='持有天数（默认：3）'
        )
        parser.add_argument(
            '--tolerance',
            type=float,
            default=1.05,
            help='低位容忍度（默认：1.05，即最低点的105%%以内）'
        )

    @staticmethod
    def _add_intraday_args(parser: argparse.ArgumentParser):
        """添加日内交易策略参数"""
        # 股票筛选参数
        parser.add_argument(
            '--min-turnover',
            type=float,
            help='最低换手率（%%）'
        )
        parser.add_argument(
            '--max-turnover',
            type=float,
            help='最高换手率（%%）'
        )
        parser.add_argument(
            '--min-amount',
            type=float,
            help='最低成交额'
        )
        parser.add_argument(
            '--min-amplitude',
            type=float,
            help='最低日内振幅（%%）'
        )

        # 交易参数
        parser.add_argument(
            '--buy-deviation',
            type=float,
            help='买入偏离度（%%）'
        )
        parser.add_argument(
            '--target-profit',
            type=float,
            help='目标收益率（%%）'
        )
        parser.add_argument(
            '--stop-loss',
            type=float,
            help='止损比例（%%）'
        )
        parser.add_argument(
            '--trade-amount',
            type=float,
            help='每笔交易金额'
        )

    @staticmethod
    def validate_args(args) -> tuple[bool, Optional[str]]:
        """
        验证参数

        Args:
            args: 解析后的参数对象

        Returns:
            (is_valid, error_message)
        """
        # 验证日期格式
        if args.start and not validate_date_format(args.start):
            return False, f"开始日期格式错误: {args.start}，应为 YYYY-MM-DD"

        if args.end and not validate_date_format(args.end):
            return False, f"结束日期格式错误: {args.end}，应为 YYYY-MM-DD"

        # 验证日期范围
        if args.start and args.end:
            if not validate_date_range(args.start, args.end):
                return False, f"日期范围无效: {args.start} > {args.end}"

        return True, None

    @staticmethod
    def print_config_summary(args, strategy_name: str):
        """
        打印配置摘要

        Args:
            args: 解析后的参数对象
            strategy_name: 策略名称
        """
        print("=" * 80)
        print(f"{strategy_name} - 配置摘要")
        print("=" * 80)
        print(f"日期范围: {args.start} 至 {args.end}")
        print(f"输出目录: {args.output}")

        if hasattr(args, 'optimize') and args.optimize:
            print(f"运行模式: 参数优化 - {args.mode}")
        else:
            print("运行模式: 基准回测")

        print("=" * 80)
