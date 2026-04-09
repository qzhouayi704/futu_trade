#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试持仓股票优先级逻辑"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from simple_trade.services.realtime.activity_calculator import ActivityCalculator


def test_priority_stocks_skip_filter():
    """测试优先股票跳过活跃度筛选"""
    calculator = ActivityCalculator()

    # 模拟股票列表
    stocks = [
        {'code': 'HK.00700', 'name': '腾讯控股'},
        {'code': 'HK.09988', 'name': '阿里巴巴'},
        {'code': 'HK.03690', 'name': '美团'},
    ]

    # 设置优先股票（持仓）
    priority_stocks = ['HK.00700', 'HK.09988']

    # 执行优先股票处理
    remaining, priority_added = calculator.handle_priority_stocks(stocks, priority_stocks)

    # 验证结果
    print(f"[OK] 剩余股票数: {len(remaining)} (预期: 1)")
    print(f"[OK] 优先股票数: {len(priority_added)} (预期: 2)")

    assert len(remaining) == 1, f"剩余股票数应为 1，实际为 {len(remaining)}"
    assert len(priority_added) == 2, f"优先股票数应为 2，实际为 {len(priority_added)}"

    # 验证优先股票标记
    for stock in priority_added:
        assert stock.get('is_priority') is True, f"{stock['code']} 应标记为优先股票"
        assert stock.get('activity_score') == 1.0, f"{stock['code']} 活跃度分数应为 1.0"
        print(f"[OK] {stock['code']} 标记为优先股票，activity_score=1.0")

    # 验证剩余股票
    assert remaining[0]['code'] == 'HK.03690', "剩余股票应为 HK.03690"
    print(f"[OK] 剩余股票: {remaining[0]['code']}")

    print("\n[SUCCESS] 所有测试通过！持仓股票优先级逻辑正常工作")


if __name__ == '__main__':
    test_priority_stocks_skip_filter()
