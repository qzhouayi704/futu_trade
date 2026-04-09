#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
激进策略语法验证测试

只验证代码语法和导入，不实际运行
"""

import sys
import os
import py_compile

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _check_syntax(file_path, description):
    """测试文件语法"""
    try:
        py_compile.compile(file_path, doraise=True)
        print(f"[OK] {description}")
        return True
    except py_compile.PyCompileError as e:
        print(f"[FAIL] {description}")
        print(f"  错误: {e}")
        return False

def main():
    """主测试函数"""
    print("=" * 60)
    print("激进策略语法验证测试")
    print("=" * 60)

    tests = [
        ("simple_trade/services/market_data/plate/plate_strength_service.py", "板块强势度服务"),
        ("simple_trade/services/market_data/leader_stock_filter.py", "龙头股筛选服务"),
        ("simple_trade/strategy/aggressive_strategy.py", "激进策略主类"),
        ("simple_trade/core/validation/signal_scorer.py", "信号评分器"),
        ("simple_trade/core/validation/risk_checker.py", "风险检查器"),
        ("simple_trade/services/trading/aggressive/aggressive_trade_service.py", "激进策略交易服务"),
        ("simple_trade/core/container/service_container.py", "服务容器"),
    ]

    results = []
    for file_path, description in tests:
        full_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            file_path
        )
        results.append(_check_syntax(full_path, description))

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(results)
    total = len(results)
    print(f"通过: {passed}/{total}")

    if passed == total:
        print("\n所有文件语法检查通过！")
        return True
    else:
        print(f"\n{total - passed} 个文件存在语法错误")
        return False

if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"测试执行失败: {e}")
        sys.exit(1)


def test_all_aggressive_syntax():
    """pytest 入口：验证所有激进策略相关文件的语法"""
    assert main() is True, "存在语法错误的文件"
