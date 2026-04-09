#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API接口测试

测试关键API端点，确保响应格式正确
需要先启动服务: python run.py
"""

import sys
import requests

BASE_URL = "http://localhost:5000"


def test_signals_api_today():
    """测试今日信号API"""
    try:
        resp = requests.get(f"{BASE_URL}/api/strategy/signals?type=today&limit=10", timeout=5)
        data = resp.json()
        
        assert data.get('success') == True, f"API返回失败: {data.get('message')}"
        assert 'data' in data, "响应缺少 data 字段"
        assert 'signals' in data['data'], "响应缺少 signals 字段"
        
        signals = data['data']['signals']
        print(f"  返回 {len(signals)} 条信号")
        
        # 验证信号字段格式
        if signals:
            signal = signals[0]
            required_fields = ['id', 'stock_id', 'signal_type', 'price', 'stock_code', 'stock_name']
            for field in required_fields:
                assert field in signal, f"信号缺少字段: {field}"
            print(f"  信号字段验证通过")
        
        return True
    except requests.exceptions.ConnectionError:
        print(f"  ⚠ 服务未启动，跳过测试")
        return None


def test_signals_api_history():
    """测试历史信号API"""
    try:
        resp = requests.get(f"{BASE_URL}/api/strategy/signals?type=history&limit=10", timeout=5)
        data = resp.json()
        
        assert data.get('success') == True, f"API返回失败: {data.get('message')}"
        assert 'data' in data, "响应缺少 data 字段"
        
        print(f"  返回 {len(data['data'].get('signals', []))} 条信号")
        return True
    except requests.exceptions.ConnectionError:
        print(f"  ⚠ 服务未启动，跳过测试")
        return None


def test_stock_pool_api():
    """测试股票池API"""
    try:
        resp = requests.get(f"{BASE_URL}/api/stocks/pool", timeout=5)
        data = resp.json()
        
        assert data.get('success') == True, f"API返回失败: {data.get('message')}"
        assert 'data' in data, "响应缺少 data 字段"
        assert 'stocks' in data['data'], "响应缺少 stocks 字段"
        
        stocks = data['data']['stocks']
        print(f"  返回 {len(stocks)} 只股票")
        
        # 验证股票字段格式
        if stocks:
            stock = stocks[0]
            required_fields = ['id', 'code', 'name']
            for field in required_fields:
                assert field in stock, f"股票缺少字段: {field}"
            print(f"  股票字段验证通过")
        
        return True
    except requests.exceptions.ConnectionError:
        print(f"  ⚠ 服务未启动，跳过测试")
        return None


def test_monitor_status_api():
    """测试监控状态API"""
    try:
        resp = requests.get(f"{BASE_URL}/api/monitor/status", timeout=5)
        data = resp.json()
        
        assert data.get('success') == True, f"API返回失败: {data.get('message')}"
        assert 'data' in data, "响应缺少 data 字段"
        
        status = data['data']
        assert 'is_running' in status, "状态缺少 is_running 字段"
        print(f"  监控状态: {'运行中' if status['is_running'] else '已停止'}")
        
        return True
    except requests.exceptions.ConnectionError:
        print(f"  ⚠ 服务未启动，跳过测试")
        return None


def test_strategy_list_api():
    """测试策略列表API"""
    try:
        resp = requests.get(f"{BASE_URL}/api/strategy/list", timeout=5)
        data = resp.json()
        
        assert data.get('success') == True, f"API返回失败: {data.get('message')}"
        assert 'data' in data, "响应缺少 data 字段"
        
        print(f"  策略列表获取成功")
        return True
    except requests.exceptions.ConnectionError:
        print(f"  ⚠ 服务未启动，跳过测试")
        return None


def run_all_tests():
    """运行所有API测试"""
    tests = [
        ("今日信号API", test_signals_api_today),
        ("历史信号API", test_signals_api_history),
        ("股票池API", test_stock_pool_api),
        ("监控状态API", test_monitor_status_api),
        ("策略列表API", test_strategy_list_api),
    ]
    
    print("\n" + "="*60)
    print("API接口测试")
    print("="*60)
    
    passed = 0
    failed = 0
    skipped = 0
    
    for name, test_func in tests:
        try:
            print(f"\n[测试] {name}")
            result = test_func()
            if result is None:
                skipped += 1
            elif result:
                print(f"  ✓ 通过")
                passed += 1
        except AssertionError as e:
            print(f"  ✗ 失败: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ 错误: {e}")
            failed += 1
    
    print("\n" + "-"*60)
    print(f"测试结果: 通过 {passed}, 失败 {failed}, 跳过 {skipped}")
    
    if skipped > 0:
        print("提示: 部分测试被跳过，请确保服务已启动 (python run.py)")
    
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
