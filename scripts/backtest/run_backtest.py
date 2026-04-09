4#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测系统统一入口脚本

直接运行即可进入交互式菜单：
    python scripts/backtest/run_backtest.py
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from simple_trade.backtest.utils.interactive_input import InteractiveInput


def show_main_menu():
    """显示主菜单"""
    print("\n" + "=" * 80)
    print("回测系统统一入口")
    print("=" * 80)
    print()
    print("请选择要执行的操作：")
    print()
    print("  1. 日内交易回测")
    print("  2. 低换手率回测")
    print("  3. 获取K线数据")
    print("  4. 价格位置统计分析")
    print("  5. 隔日交易对比分析")
    print("  6. 多方案参数优化对比")
    print("  0. 退出")
    print()

    choice = input("请输入选项 [0-6]: ").strip()
    return choice


def handle_data_fetch():
    """处理数据获取"""
    print("\n" + "=" * 80)
    print("获取K线数据")
    print("=" * 80)
    print()

    # 选择K线类型
    print("请选择要获取的K线类型：")
    print("  1. 日线数据（用于低换手率回测）")
    print("  2. 5分钟线数据（用于日内交易回测）")
    print("  3. 两者都获取")
    print()

    kline_choice = input("请输入选项 [1-3]: ").strip()

    kline_type_map = {
        '1': 'daily',
        '2': '5min',
        '3': 'both'
    }

    if kline_choice not in kline_type_map:
        print("无效的选项")
        return None

    kline_type = kline_type_map[kline_choice]
    kline_type_name = {
        'daily': '日线数据',
        '5min': '5分钟线数据',
        'both': '日线 + 5分钟线数据'
    }[kline_type]

    # 股票范围选择（仅5分钟线需要）
    stock_filter = None
    if kline_type in ('5min', 'both'):
        print("\n请选择股票范围：")
        print("  1. 热门科网股（15只，推荐，约15分钟）")
        print("  2. 全部有日线数据的股票（可能数百只，耗时数小时）")
        print("  3. 自定义数量限制")
        print()

        scope_choice = input("请输入选项 [1-3] (默认1): ").strip() or '1'

        if scope_choice == '1':
            stock_filter = 'hot_tech'
        elif scope_choice == '3':
            stock_filter = None  # 使用 limit 控制

    limit = None
    if stock_filter != 'hot_tech':
        limit_input = input("\n限制股票数量 (留空=不限制) [建议: 50]: ").strip()
        limit = int(limit_input) if limit_input else None

    # 创建参数对象
    class Args:
        pass

    args = Args()
    args.kline_type = kline_type
    args.limit = limit
    args.stock_filter = stock_filter

    # 确认
    stock_scope_name = {
        'hot_tech': '热门科网股（15只）',
        None: f'全部股票' + (f'（限制{limit}只）' if limit else '')
    }.get(stock_filter, '全部股票')

    print("\n" + "=" * 80)
    print("配置摘要：")
    print("=" * 80)
    print(f"K线类型: {kline_type_name}")
    print(f"股票范围: {stock_scope_name}")
    print(f"限制数量: {args.limit if args.limit else '不限制'}")
    print("=" * 80)
    print()

    confirm = input("确认开始获取数据？[Y/n]: ").strip().lower()
    if confirm and confirm != 'y':
        print("已取消")
        return None

    return args


def _run_price_position_config():
    """价格位置统计分析的简化配置"""
    from datetime import datetime, timedelta

    print("\n" + "=" * 80)
    print("价格位置统计分析 - 配置")
    print("=" * 80)
    print()

    default_start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    default_end = datetime.now().strftime('%Y-%m-%d')

    start = input(f"  开始日期 (YYYY-MM-DD，默认: {default_start}): ").strip()
    start_date = start if start else default_start

    end = input(f"  结束日期 (YYYY-MM-DD，默认: {default_end}): ").strip()
    end_date = end if end else default_end

    output_dir = input("  输出目录 (默认: backtest_results): ").strip()
    output_dir = output_dir if output_dir else "backtest_results"

    print(f"\n  时间范围: {start_date} 至 {end_date}")
    print(f"  输出目录: {output_dir}")
    confirm = input("\n确认开始分析？[Y/n]: ").strip().lower()
    if confirm == 'n':
        print("已取消")
        sys.exit(0)

    class Args:
        pass

    args = Args()
    args.start = start_date
    args.end = end_date
    args.output = output_dir
    args.optimize = False
    return args


def run_backtest(backtest_type: str):
    """运行回测"""
    if backtest_type == 'price_position':
        # 价格位置统计分析：简化配置，不需要策略参数
        return _run_price_position_config()

    # 创建交互式输入
    interactive = InteractiveInput(backtest_type)
    config = interactive.get_backtest_config()

    # 创建参数对象
    class Args:
        pass

    args = Args()
    args.start = config['start_date']
    args.end = config['end_date']
    args.output = config['output_dir']
    args.enable_api = config['api_config']['enable_api']
    args.max_api_requests = config['api_config']['max_api_requests']
    args.disable_api = not config['api_config']['enable_api']

    # 设置模式
    if config['mode'] == 'baseline':
        args.optimize = False
        # 设置策略参数
        for key, value in config['strategy_params'].items():
            setattr(args, key, value)
    else:
        args.optimize = True
        args.mode = 'single' if config['mode'] == 'optimize_single' else 'full'
        # 使用默认策略参数
        if backtest_type == 'low_turnover':
            args.lookback = 6
            args.turnover = 0.15
            args.target_rise = 5.0
            args.holding_days = 3
            args.tolerance = 1.05
        elif backtest_type == 'intraday':
            args.min_turnover = None
            args.max_turnover = None
            args.min_amount = None
            args.min_amplitude = None
            args.buy_deviation = None
            args.target_profit = None
            args.stop_loss = None
            args.trade_amount = None

    return args


def main():
    """主函数"""
    try:
        while True:
            choice = show_main_menu()

            if choice == '0':
                print("\n再见！")
                sys.exit(0)

            elif choice == '1':
                # 日内交易回测
                print("\n正在启动日内交易回测...")
                args = run_backtest('intraday')

                from scripts.backtest.intraday_runner import IntradayRunner
                runner = IntradayRunner(args)
                runner.run()

                # 回测完成后询问是否继续
                print("\n" + "=" * 80)
                continue_choice = input("回测完成！是否继续使用回测系统？[Y/n]: ").strip().lower()
                if continue_choice and continue_choice != 'y':
                    print("\n再见！")
                    break

            elif choice == '2':
                # 低换手率回测
                print("\n正在启动低换手率回测...")
                args = run_backtest('low_turnover')

                from scripts.backtest.low_turnover_runner import LowTurnoverRunner
                runner = LowTurnoverRunner(args)
                runner.run()

                # 回测完成后询问是否继续
                print("\n" + "=" * 80)
                continue_choice = input("回测完成！是否继续使用回测系统？[Y/n]: ").strip().lower()
                if continue_choice and continue_choice != 'y':
                    print("\n再见！")
                    break

            elif choice == '3':
                # 获取K线数据
                args = handle_data_fetch()
                if args is None:
                    continue

                from scripts.backtest.data_fetcher import DataFetcher
                fetcher = DataFetcher(args)
                fetcher.fetch()

                # 数据获取完成后询问是否继续
                print("\n" + "=" * 80)
                continue_choice = input("数据获取完成！是否继续使用回测系统？[Y/n]: ").strip().lower()
                if continue_choice and continue_choice != 'y':
                    print("\n再见！")
                    break

            elif choice == '4':
                # 价格位置统计分析
                print("\n正在启动价格位置统计分析...")
                args = run_backtest('price_position')

                from scripts.backtest.price_position_runner import PricePositionRunner
                runner = PricePositionRunner(args)
                runner.run()

                # 回测完成后询问是否继续
                print("\n" + "=" * 80)
                continue_choice = input("分析完成！是否继续使用回测系统？[Y/n]: ").strip().lower()
                if continue_choice and continue_choice != 'y':
                    print("\n再见！")
                    break

            elif choice == '5':
                # 隔日交易对比分析
                print("\n正在启动隔日交易对比分析...")
                args = run_backtest('price_position')

                from scripts.backtest.next_day_runner import NextDayRunner
                runner = NextDayRunner(args)
                runner.run()

                print("\n" + "=" * 80)
                continue_choice = input("分析完成！是否继续使用回测系统？[Y/n]: ").strip().lower()
                if continue_choice and continue_choice != 'y':
                    print("\n再见！")
                    break

            elif choice == '6':
                # 多方案参数优化对比
                print("\n正在启动多方案参数优化对比...")
                args = run_backtest('price_position')

                from scripts.backtest.comparison_runner import ComparisonBacktestRunner
                runner = ComparisonBacktestRunner(args)
                runner.run()

                print("\n" + "=" * 80)
                continue_choice = input("分析完成！是否继续使用回测系统？[Y/n]: ").strip().lower()
                if continue_choice and continue_choice != 'y':
                    print("\n再见！")
                    break

            else:
                print("\n无效的选项，请重新选择。")

    except KeyboardInterrupt:
        print("\n\n用户中断，再见！")
        sys.exit(1)
    except Exception as e:
        print(f"\n执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
