#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库查询测试

测试关键的数据库查询方法，确保返回 TradeSignal 实例且格式一致
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_db():
    """获取数据库管理器实例"""
    from simple_trade.database.core.db_manager import DatabaseManager
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'simple_trade', 'data', 'trade.db')
    return DatabaseManager(db_path)


def _validate_trade_signal(signal, label="signal"):
    """验证 TradeSignal 实例的字段完整性"""
    from simple_trade.core.models import TradeSignal
    assert isinstance(signal, TradeSignal), \
        f"{label} 应该是 TradeSignal 实例, 实际是 {type(signal)}"

    # 验证必需字段类型
    assert isinstance(signal.id, int), "id 应该是整数"
    assert isinstance(signal.stock_id, int), "stock_id 应该是整数"
    assert signal.signal_type in ['BUY', 'SELL', None], \
        f"signal_type 值异常: {signal.signal_type}"
    assert signal.stock_code is None or isinstance(signal.stock_code, str), \
        "stock_code 应该是字符串"
    assert signal.stock_name is None or isinstance(signal.stock_name, str), \
        "stock_name 应该是字符串"
    assert signal.strategy_id is None or isinstance(signal.strategy_id, str), \
        "strategy_id 应该是字符串"
    assert signal.strategy_name is None or isinstance(signal.strategy_name, str), \
        "strategy_name 应该是字符串"

    # 验证 to_dict() 包含 API 必需字段
    d = signal.to_dict()
    required_keys = ['id', 'stock_id', 'signal_type', 'price',
                     'stock_code', 'stock_name', 'strategy_id', 'strategy_name']
    for key in required_keys:
        assert key in d, f"to_dict() 缺少必需字段: {key}"


def test_get_today_signals_format():
    """测试 get_today_signals() 返回 TradeSignal 实例"""
    db = _get_db()
    signals = db.trade_queries.get_today_signals(limit=5)

    print(f"  get_today_signals() 返回 {len(signals)} 条记录")

    if signals:
        _validate_trade_signal(signals[0], "today_signal")
        print(f"  字段格式验证通过")

    return True


def test_get_recent_trade_signals_format():
    """测试 get_recent_trade_signals() 返回 TradeSignal 实例"""
    db = _get_db()
    signals = db.trade_history_queries.get_recent_trade_signals(hours=24*7, limit=5)

    print(f"  get_recent_trade_signals() 返回 {len(signals)} 条记录")

    if signals:
        _validate_trade_signal(signals[0], "recent_signal")
        print(f"  字段格式验证通过")

    return True


def test_signals_format_consistency():
    """测试两个信号查询方法的返回格式一致性（都是 TradeSignal 实例）"""
    from simple_trade.core.models import TradeSignal
    db = _get_db()

    today = db.trade_queries.get_today_signals(limit=1)
    recent = db.trade_history_queries.get_recent_trade_signals(hours=24*30, limit=1)

    if today and recent:
        assert type(today[0]) == type(recent[0]) == TradeSignal, \
            "两个方法应返回相同的 TradeSignal 类型"
        # 验证 to_dict() 键集合一致
        today_keys = set(today[0].to_dict().keys())
        recent_keys = set(recent[0].to_dict().keys())
        assert today_keys == recent_keys, \
            f"to_dict() 键不一致: {today_keys.symmetric_difference(recent_keys)}"
        print(f"  两个方法返回格式一致: TradeSignal 实例, {len(today_keys)} 个字段")
    else:
        print(f"  数据不足以进行一致性验证 (today={len(today)}, recent={len(recent)})")

    return True


def test_stocks_query():
    """测试股票池查询"""
    db = _get_db()
    stocks = db.stock_queries.get_stocks(limit=10)
    print(f"  get_stocks() 返回 {len(stocks)} 条记录")

    if stocks:
        row = stocks[0]
        assert len(row) >= 4, f"股票字段数量不足: {len(row)}"
        print(f"  股票数据格式正确")

    return True


def run_all_tests():
    """运行所有数据库测试"""
    tests = [
        ("get_today_signals 格式测试", test_get_today_signals_format),
        ("get_recent_trade_signals 格式测试", test_get_recent_trade_signals_format),
        ("信号格式一致性测试", test_signals_format_consistency),
        ("股票池查询测试", test_stocks_query),
    ]

    print("\n" + "="*60)
    print("数据库查询测试")
    print("="*60)

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            print(f"\n[测试] {name}")
            test_func()
            print(f"  [通过]")
            passed += 1
        except AssertionError as e:
            print(f"  [失败]: {e}")
            failed += 1
        except Exception as e:
            print(f"  [错误]: {e}")
            failed += 1

    print("\n" + "-"*60)
    print(f"测试结果: 通过 {passed}/{passed+failed}")

    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
