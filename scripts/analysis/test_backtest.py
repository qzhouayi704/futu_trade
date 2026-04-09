"""
回测系统快速测试脚本

测试回测框架的基本功能。
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.backtest.strategies.low_turnover_strategy import LowTurnoverStrategy


def test_strategy():
    """测试策略基本功能"""
    print("=" * 80)
    print("测试1：策略初始化")
    print("=" * 80)

    strategy = LowTurnoverStrategy(
        lookback_days=8,
        turnover_threshold=0.1,
        low_position_tolerance=1.02,
        target_rise=5.0,
        holding_days=3
    )

    print(f"策略名称：{strategy.get_strategy_name()}")
    print(f"策略参数：{strategy.get_params()}")
    print(f"策略描述：{strategy.get_strategy_description()}")
    print("✓ 策略初始化成功\n")


def test_data_loader():
    """测试数据加载器"""
    print("=" * 80)
    print("测试2：数据加载器")
    print("=" * 80)

    try:
        from simple_trade.backtest.core.data_loader import BacktestDataLoader

        db_manager = DatabaseManager()
        data_loader = BacktestDataLoader(db_manager, market='HK')

        # 加载股票列表
        stocks = data_loader.load_stock_list()
        print(f"加载股票列表：{len(stocks)}只")

        if stocks:
            print(f"示例股票：{stocks[0]}")
            print("✓ 数据加载器测试成功\n")
        else:
            print("⚠ 警告：股票列表为空\n")

    except Exception as e:
        print(f"✗ 数据加载器测试失败：{e}\n")


def test_analyzer():
    """测试分析器"""
    print("=" * 80)
    print("测试3：结果分析器")
    print("=" * 80)

    try:
        from simple_trade.backtest.core.analyzer import BacktestAnalyzer

        analyzer = BacktestAnalyzer()

        # 模拟信号数据
        signals = [
            {
                'date': '2024-12-01',
                'stock_code': 'HK.00700',
                'stock_name': '腾讯控股',
                'buy_price': 300.0,
                'turnover_rate': 0.08,
                'max_rise_pct': 6.5,
                'max_rise_days': 2,
                'is_target_reached': True
            },
            {
                'date': '2024-12-02',
                'stock_code': 'HK.00941',
                'stock_name': '中国移动',
                'buy_price': 50.0,
                'turnover_rate': 0.09,
                'max_rise_pct': 3.2,
                'max_rise_days': 1,
                'is_target_reached': False
            }
        ]

        analysis = analyzer.analyze(signals)
        print(f"总信号数：{analysis['total_signals']}")
        print(f"胜率：{analysis['win_rate']:.2f}%")
        print(f"平均涨幅：{analysis['avg_rise']:.2f}%")
        print("✓ 分析器测试成功\n")

    except Exception as e:
        print(f"✗ 分析器测试失败：{e}\n")


def test_reporter():
    """测试报告生成器"""
    print("=" * 80)
    print("测试4：报告生成器")
    print("=" * 80)

    try:
        from simple_trade.backtest.core.reporter import BacktestReporter
        import tempfile

        reporter = BacktestReporter(output_dir=tempfile.mkdtemp())

        # 模拟数据
        params = {
            'start_date': '2024-02-06',
            'end_date': '2025-02-06',
            'market': 'HK',
            'strategy_name': '低换手率策略',
            'strategy_params': {
                'lookback_days': 8,
                'turnover_threshold': 0.1
            }
        }

        analysis = {
            'total_signals': 100,
            'rise_count': 60,
            'win_rate': 60.0,
            'avg_rise': 6.5,
            'max_rise': 15.2,
            'distribution': {
                '< 0%': 10,
                '0-2%': 20,
                '2-5%': 30,
                '5-10%': 25,
                '> 10%': 15
            }
        }

        signals = []

        file_paths = reporter.generate_report(analysis, signals, params, 'test')
        print(f"生成的文件：")
        for key, path in file_paths.items():
            print(f"  - {key}: {path}")
        print("✓ 报告生成器测试成功\n")

    except Exception as e:
        print(f"✗ 报告生成器测试失败：{e}\n")


def main():
    """运行所有测试"""
    print("\n")
    print("=" * 80)
    print("回测系统快速测试")
    print("=" * 80)
    print("\n")

    test_strategy()
    test_data_loader()
    test_analyzer()
    test_reporter()

    print("=" * 80)
    print("测试完成！")
    print("=" * 80)


if __name__ == '__main__':
    main()
