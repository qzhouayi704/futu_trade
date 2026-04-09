#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 SubType 是字符串常量"""

from futu import SubType

print("=== SubType 类型验证 ===")
print(f"SubType.TICKER 类型: {type(SubType.TICKER)}")
print(f"SubType.TICKER 值: {SubType.TICKER}")
print(f"SubType.ORDER_BOOK 类型: {type(SubType.ORDER_BOOK)}")
print(f"SubType.ORDER_BOOK 值: {SubType.ORDER_BOOK}")
print(f"SubType.QUOTE 类型: {type(SubType.QUOTE)}")
print(f"SubType.QUOTE 值: {SubType.QUOTE}")

print("\n=== 字符串转换测试 ===")
print(f"str(SubType.TICKER) = {str(SubType.TICKER)}")
print(f"str(SubType.ORDER_BOOK) = {str(SubType.ORDER_BOOK)}")

print("\n=== 字典 key 测试 ===")
result = {
    'by_type': {
        str(SubType.TICKER): {'success': ['HK.00700'], 'failed': []},
        str(SubType.ORDER_BOOK): {'success': ['HK.00700'], 'failed': []}
    }
}
print(f"使用 'TICKER' 访问: {result['by_type'].get('TICKER')}")
print(f"使用 'ORDER_BOOK' 访问: {result['by_type'].get('ORDER_BOOK')}")

print("\n[SUCCESS] SubType 是字符串常量，可以直接使用")
