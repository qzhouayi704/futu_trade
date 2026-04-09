#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试多类型订阅功能"""

import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, PropertyMock

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Mock futu module
sys.modules['futu'] = MagicMock()
from futu import SubType, RET_OK

# 正确设置 Mock 的 name 属性
SubType.QUOTE = Mock()
type(SubType.QUOTE).name = PropertyMock(return_value='QUOTE')

SubType.TICKER = Mock()
type(SubType.TICKER).name = PropertyMock(return_value='TICKER')

SubType.ORDER_BOOK = Mock()
type(SubType.ORDER_BOOK).name = PropertyMock(return_value='ORDER_BOOK')

RET_OK = 0

from simple_trade.api.subscription_manager import SubscriptionManager


def test_subscribe_multi_types_with_enum():
    """测试使用 SubType 枚举订阅多类型"""
    # Mock FutuClient
    mock_client = Mock()
    mock_client.is_available.return_value = True
    mock_client.client.subscribe.return_value = (RET_OK, None)

    # 创建 SubscriptionManager
    manager = SubscriptionManager(futu_client=mock_client)

    # 订阅多类型
    stock_codes = ['HK.00700', 'HK.09988']
    sub_types = [SubType.TICKER, SubType.ORDER_BOOK]

    result = manager.subscribe_multi_types(stock_codes, sub_types)

    print(f"[OK] 订阅结果: success={result['success']}, count={result['subscribed_count']}")
    print(f"[OK] 按类型统计: {list(result['by_type'].keys())}")

    assert result['success'] is True, "订阅应该成功"
    assert result['subscribed_count'] > 0, "应该有成功订阅的股票"

    print("\n[SUCCESS] SubType 枚举订阅测试通过")


def test_subscribe_by_type_handles_string():
    """测试 _subscribe_by_type 能够处理字符串类型"""
    # Mock FutuClient
    mock_client = Mock()
    mock_client.is_available.return_value = True
    mock_client.client.subscribe.return_value = (RET_OK, None)

    # 创建 SubscriptionManager
    manager = SubscriptionManager(futu_client=mock_client)

    # 测试传入字符串（模拟旧代码或错误调用）
    stock_codes = ['HK.00700']

    # 直接调用 _subscribe_by_type，传入字符串
    result = manager._subscribe_by_type(stock_codes, 'TICKER')

    print(f"[OK] 字符串类型订阅结果: success={len(result['success'])}, failed={len(result['failed'])}")

    # 应该能够处理字符串而不报错
    assert isinstance(result, dict), "应该返回字典"
    assert 'success' in result, "应该包含 success 字段"
    assert 'failed' in result, "应该包含 failed 字段"

    print("\n[SUCCESS] 字符串类型处理测试通过")


if __name__ == '__main__':
    test_subscribe_multi_types_with_enum()
    test_subscribe_by_type_handles_string()
    print("\n[SUCCESS] 所有多类型订阅测试通过")
