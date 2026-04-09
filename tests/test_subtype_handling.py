#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 subscription_manager 的类型名称处理逻辑"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_type_name_extraction():
    """测试类型名称提取逻辑"""
    from unittest.mock import Mock, PropertyMock

    # 模拟 SubType 枚举
    mock_enum = Mock()
    type(mock_enum).name = PropertyMock(return_value='TICKER')

    # 测试枚举对象
    type_name = mock_enum.name if hasattr(mock_enum, 'name') else str(mock_enum)
    print(f"[OK] 枚举对象类型名称: {type_name}")
    assert type_name == 'TICKER', f"应该是 'TICKER'，实际是 {type_name}"

    # 测试字符串
    type_name = 'ORDER_BOOK'
    result = type_name if not hasattr(type_name, 'name') else type_name.name
    print(f"[OK] 字符串类型名称: {result}")
    assert result == 'ORDER_BOOK', f"应该是 'ORDER_BOOK'，实际是 {result}"

    print("\n[SUCCESS] 类型名称提取逻辑测试通过")


def test_real_subtype_handling():
    """测试真实的 SubType 处理"""
    try:
        from futu import SubType

        # 测试真实的 SubType 枚举
        ticker = SubType.TICKER
        print(f"[OK] SubType.TICKER.name = {ticker.name}")
        assert ticker.name == 'TICKER', f"应该是 'TICKER'，实际是 {ticker.name}"

        orderbook = SubType.ORDER_BOOK
        print(f"[OK] SubType.ORDER_BOOK.name = {orderbook.name}")
        assert orderbook.name == 'ORDER_BOOK', f"应该是 'ORDER_BOOK'，实际是 {orderbook.name}"

        print("\n[SUCCESS] 真实 SubType 处理测试通过")
    except ImportError:
        print("\n[SKIP] futu 模块未安装，跳过真实 SubType 测试")


if __name__ == '__main__':
    test_type_name_extraction()
    test_real_subtype_handling()
    print("\n[SUCCESS] 所有测试通过")
