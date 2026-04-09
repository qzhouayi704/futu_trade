#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试回测报告导出功能

验证文件命名和报告内容是否符合预期
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.backtest.core.reporter import BacktestReporter


def test_report_naming():
    """测试报告文件命名"""
    print("=" * 80)
    print("测试回测报告文件命名")
    print("=" * 80)

    reporter = BacktestReporter(output_dir='test_reports')

    # 测试数据
    analysis = {
        'total_signals': 100,
        'rise_count': 65,
        'win_rate': 65.0,
        'avg_rise': 3.5,
        'max_rise': 12.8,
        'avg_days_to_peak': 2.3,
        'distribution': {
            '0-3%': 35,
            '3-5%': 20,
            '5-10%': 10,
            '>10%': 0
        }
    }

    signals = [
        {
            'date': '2026-01-01',
            'stock_code': 'HK.00001',
            'stock_name': '测试股票',
            'buy_price': 10.0,
            'turnover_rate': 2.5,
            'is_low_position': True,
            'max_rise_pct': 5.2,
            'max_rise_days': 2,
            'is_target_reached': True
        }
    ]

    params = {
        'start_date': '2026-01-01',
        'end_date': '2026-02-01',
        'market': 'HK',
        'total_stocks': 50,
        'strategy_name': '低换手率策略',
        'strategy_params': {
            'lookback_days': 6,
            'turnover_threshold': 0.15,
            'target_rise': 5.0
        }
    }

    # 测试1：使用策略名称（推荐方式）
    print("\n测试1：使用策略名称自动生成文件名")
    report_files = reporter.generate_report(
        analysis=analysis,
        signals=signals,
        params=params,
        strategy_name='低换手率策略'
    )

    print("\n生成的文件：")
    for file_type, file_path in report_files.items():
        filename = os.path.basename(file_path)
        print(f"  - {file_type}: {filename}")
        # 验证文件名格式
        assert '低换手率策略' in filename, f"文件名应包含策略名: {filename}"
        assert '_' in filename, f"文件名应包含时间戳分隔符: {filename}"

    # 测试2：自定义报告名称
    print("\n测试2：使用自定义报告名称")
    report_files = reporter.generate_report(
        analysis=analysis,
        signals=signals,
        params=params,
        report_name='custom_test_report'
    )

    print("\n生成的文件：")
    for file_type, file_path in report_files.items():
        filename = os.path.basename(file_path)
        print(f"  - {file_type}: {filename}")
        # 验证文件名格式
        assert 'custom_test_report' in filename, f"文件名应包含自定义名称: {filename}"

    # 测试3：默认命名（不提供任何名称）
    print("\n测试3：使用默认命名")
    report_files = reporter.generate_report(
        analysis=analysis,
        signals=signals,
        params=params
    )

    print("\n生成的文件：")
    for file_type, file_path in report_files.items():
        filename = os.path.basename(file_path)
        print(f"  - {file_type}: {filename}")
        # 验证文件名格式
        assert 'backtest_' in filename, f"文件名应以backtest_开头: {filename}"

    print("\n" + "=" * 80)
    print("All tests passed!")
    print("=" * 80)

    # 清理测试文件
    import shutil
    if os.path.exists('test_reports'):
        shutil.rmtree('test_reports')
        print("\n已清理测试文件")


def test_report_content():
    """测试报告内容"""
    print("\n" + "=" * 80)
    print("测试回测报告内容")
    print("=" * 80)

    reporter = BacktestReporter(output_dir='test_reports')

    # 测试数据
    analysis = {
        'total_signals': 100,
        'rise_count': 65,
        'win_rate': 65.0,
        'avg_rise': 3.5,
        'max_rise': 12.8
    }

    signals = []
    params = {
        'start_date': '2026-01-01',
        'end_date': '2026-02-01',
        'market': 'HK',
        'total_stocks': 50,
        'strategy_name': '测试策略'
    }

    report_files = reporter.generate_report(
        analysis=analysis,
        signals=signals,
        params=params,
        strategy_name='测试策略'
    )

    # 读取Markdown报告
    md_path = report_files['markdown']
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    print("\n检查报告内容：")

    # 验证必要的章节
    required_sections = [
        '# 港股回测报告',
        '## 报告说明',
        '## 一、回测参数',
        '## 二、回测结果',
        '数据来源',
        '回测方式',
        '结果解读'
    ]

    for section in required_sections:
        if section in content:
            print(f"  OK: {section}")
        else:
            print(f"  FAIL: {section}")
            raise AssertionError(f"报告缺少必要章节: {section}")

    # 验证参数信息
    assert '测试策略' in content, "报告应包含策略名称"
    assert '2026-01-01' in content, "报告应包含开始日期"
    assert '2026-02-01' in content, "报告应包含结束日期"

    # 验证结果信息
    assert '100' in content, "报告应包含总信号数"
    assert '65.00%' in content, "报告应包含胜率"

    print("\n" + "=" * 80)
    print("Report content validation passed!")
    print("=" * 80)

    # 清理测试文件
    import shutil
    if os.path.exists('test_reports'):
        shutil.rmtree('test_reports')
        print("\n已清理测试文件")


if __name__ == '__main__':
    test_report_naming()
    test_report_content()

    print("\n" + "=" * 80)
    print("All tests completed! Backtest reporter is working correctly")
    print("=" * 80)
