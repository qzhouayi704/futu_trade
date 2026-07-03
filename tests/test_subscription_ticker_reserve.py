#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订阅额度 TICKER 保底配额测试

验证 2026-07 架构审查修复：total_quota 全类型共享时，非 TICKER 类型
不得占用为 TICKER 预留的剩余席位（防 QUOTE 先到先得饿死逐笔链路）；
TICKER 已订满时预留余量为 0，不影响存量行为。
"""

import sys
from pathlib import Path
from unittest.mock import Mock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from simple_trade.api import subscription_manager as sm


def _make_manager():
    mock_client = Mock()
    mock_client.is_available.return_value = True
    mock_client.subscribe_stocks.return_value = (sm.RET_OK, None)
    # 无 config → 默认额度: total=300, QUOTE=300, TICKER=100, reserve=100
    return sm.SubscriptionManager(futu_client=mock_client)


def _codes(prefix: str, n: int, start: int = 0):
    return [f'HK.{prefix}{i:04d}' for i in range(start, start + n)]


def test_quote_cannot_eat_ticker_reserve():
    """QUOTE 只能用到 total - 未占用的 TICKER 预留，之后额度耗尽"""
    manager = _make_manager()
    manager._quote_subscribed.update(_codes('Q', 190))  # 已用 190，TICKER 空

    # total_available=110，扣 TICKER 预留 100 → QUOTE 实际可用 10
    result = manager._subscribe_by_type(_codes('N', 10), 'QUOTE')
    assert len(result['success']) == 10, '预留线内的 10 只应订阅成功'
    assert len(manager._quote_subscribed) == 200

    # 到达 200 = total(300) - reserve(100)，再订 QUOTE 应全失败
    result2 = manager._subscribe_by_type(_codes('X', 1), 'QUOTE')
    assert result2['success'] == [], 'QUOTE 不得侵入 TICKER 保底席位'
    assert len(result2['failed']) == 1


def test_ticker_can_use_reserved_seats():
    """QUOTE 用满 200 后，TICKER 仍能订上预留的席位"""
    manager = _make_manager()
    manager._quote_subscribed.update(_codes('Q', 200))

    result = manager._subscribe_by_type(_codes('T', 10), 'TICKER')
    assert len(result['success']) == 10, 'TICKER 应能使用为其预留的席位'
    assert len(manager._ticker_subscribed) == 10


def test_reserve_zero_when_ticker_full_keeps_legacy_behavior():
    """TICKER 已订满时预留余量为 0，QUOTE 可用余下全部总额度（存量行为不变）"""
    manager = _make_manager()
    manager._ticker_subscribed.update(_codes('T', 100))  # TICKER 满
    manager._quote_subscribed.update(_codes('Q', 150))   # total_used=250

    result = manager._subscribe_by_type(_codes('N', 10), 'QUOTE')
    assert len(result['success']) == 10, 'TICKER 满员后 QUOTE 不应再被预留挡住'


if __name__ == '__main__':
    test_quote_cannot_eat_ticker_reserve()
    test_ticker_can_use_reserved_seats()
    test_reserve_zero_when_ticker_full_keeps_legacy_behavior()
    print('[SUCCESS] TICKER 保底配额测试通过')
