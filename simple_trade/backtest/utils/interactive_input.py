"""
回测交互式输入模块

提供统一的交互式参数输入功能
"""

import sys
from typing import Dict, Optional
from datetime import datetime, timedelta


class InteractiveInput:
    """交互式参数输入类"""

    def __init__(self, backtest_type: str):
        """
        初始化

        Args:
            backtest_type: 回测类型（'low_turnover' 或 'intraday'）
        """
        self.backtest_type = backtest_type

    def get_backtest_config(self) -> Dict:
        """
        获取回测配置

        Returns:
            配置字典
        """
        print("\n" + "=" * 80)
        print(f"{'低换手率' if self.backtest_type == 'low_turnover' else '日内交易'}回测系统 - 交互式配置")
        print("=" * 80)
        print()

        config = {}

        # 1. 选择模式
        config['mode'] = self._get_mode()

        # 2. 日期范围
        config['start_date'], config['end_date'] = self._get_date_range()

        # 3. 策略参数
        if config['mode'] == 'baseline':
            if self.backtest_type == 'low_turnover':
                config['strategy_params'] = self._get_low_turnover_params()
            elif self.backtest_type == 'intraday':
                config['strategy_params'] = self._get_intraday_params()
        else:
            # 优化模式使用默认参数
            config['strategy_params'] = {}

        # 4. API配置
        config['api_config'] = self._get_api_config()

        # 5. 输出目录
        config['output_dir'] = self._get_output_dir()

        # 6. 确认
        self._print_summary(config)
        if not self._confirm():
            print("已取消")
            sys.exit(0)

        return config

    def _get_mode(self) -> str:
        """获取运行模式"""
        print("请选择运行模式：")
        print("  1. 基准回测（测试单组参数）")
        print("  2. 参数优化 - 单维度（推荐）")
        print("  3. 参数优化 - 全量测试")
        choice = input("请输入选项 [1-3] (默认: 1): ").strip() or "1"
        print()

        mode_map = {
            '1': 'baseline',
            '2': 'optimize_single',
            '3': 'optimize_full'
        }
        return mode_map.get(choice, 'baseline')

    def _get_date_range(self) -> tuple[str, str]:
        """获取日期范围"""
        print("请输入回测时间范围：")

        default_start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        default_end = datetime.now().strftime('%Y-%m-%d')

        start = input(f"  开始日期 (YYYY-MM-DD，默认: {default_start}): ").strip()
        start_date = start if start else default_start

        end = input(f"  结束日期 (YYYY-MM-DD，默认: {default_end}): ").strip()
        end_date = end if end else default_end

        print()
        return start_date, end_date

    def _get_low_turnover_params(self) -> Dict:
        """获取低换手率策略参数"""
        print("请输入策略参数（直接回车使用默认值）：")

        lookback = input("  回看天数 (默认: 6): ").strip()
        turnover = input("  换手率阈值 %% (默认: 0.15): ").strip()
        target_rise = input("  目标涨幅 %% (默认: 5.0): ").strip()
        holding_days = input("  持有天数 (默认: 3): ").strip()
        tolerance = input("  低位容忍度 (默认: 1.05): ").strip()
        print()

        return {
            'lookback': int(lookback) if lookback else 6,
            'turnover': float(turnover) if turnover else 0.15,
            'target_rise': float(target_rise) if target_rise else 5.0,
            'holding_days': int(holding_days) if holding_days else 3,
            'tolerance': float(tolerance) if tolerance else 1.05
        }

    def _get_intraday_params(self) -> Dict:
        """获取日内交易策略参数"""
        print("【股票筛选参数】")
        print("提示: 直接回车使用默认值")

        min_turnover = input("  最低换手率 (%%) [默认: 1.0]: ").strip()
        max_turnover = input("  最高换手率 (%%) [默认: 8.0]: ").strip()
        min_amount = input("  最低成交额 (万港币) [默认: 1000]: ").strip()
        min_amplitude = input("  最低日内振幅 (%%) [默认: 2.0]: ").strip()

        print("\n【交易参数】")
        buy_deviation = input("  买入偏离度 (%%) [默认: 1.5]: ").strip()
        target_profit = input("  目标收益率 (%%) [默认: 2.0]: ").strip()
        stop_loss = input("  止损比例 (%%) [默认: 1.5]: ").strip()
        trade_amount = input("  每笔交易金额 (港币) [默认: 100000]: ").strip()
        print()

        return {
            'min_turnover': float(min_turnover) if min_turnover else 1.0,
            'max_turnover': float(max_turnover) if max_turnover else 8.0,
            'min_amount': float(min_amount) * 10000 if min_amount else 10000000,
            'min_amplitude': float(min_amplitude) if min_amplitude else 2.0,
            'buy_deviation': float(buy_deviation) if buy_deviation else 1.5,
            'target_profit': float(target_profit) if target_profit else 2.0,
            'stop_loss': float(stop_loss) if stop_loss else 1.5,
            'trade_amount': float(trade_amount) if trade_amount else 100000
        }

    def _get_api_config(self) -> Dict:
        """获取API配置（已禁用，回测只使用数据库数据）"""
        # 回测系统不再支持API下载，只使用数据库中的数据
        # 如需下载数据，请使用主菜单的"获取K线数据"功能
        return {
            'enable_api': False,
            'max_api_requests': 0
        }

    def _get_output_dir(self) -> str:
        """获取输出目录"""
        output_dir = input("输出目录 (默认: backtest_results): ").strip()
        print()
        return output_dir if output_dir else "backtest_results"

    def _print_summary(self, config: Dict):
        """打印配置摘要"""
        print("=" * 80)
        print("配置摘要：")
        print("=" * 80)

        mode_name = {
            'baseline': '基准回测',
            'optimize_single': '参数优化 - 单维度',
            'optimize_full': '参数优化 - 全量'
        }.get(config['mode'], '未知')

        print(f"运行模式: {mode_name}")
        print(f"时间范围: {config['start_date']} 至 {config['end_date']}")

        if config['mode'] == 'baseline' and config['strategy_params']:
            print("策略参数:")
            for key, value in config['strategy_params'].items():
                print(f"  - {key}: {value}")

        print(f"数据来源: 数据库（如需下载数据，请使用主菜单的'获取K线数据'功能）")

        print(f"输出目录: {config['output_dir']}")
        print("=" * 80)
        print()

    def _confirm(self) -> bool:
        """确认开始"""
        confirm = input("确认开始回测？[Y/n]: ").strip().lower()
        return confirm != 'n'
