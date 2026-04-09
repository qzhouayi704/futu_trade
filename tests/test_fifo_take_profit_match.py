#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIFO 止盈匹配回归测试

验证 _restore_lots_fifo 方法在止盈映射下的精确匹配行为。
核心场景来自用户报告的 bug：止盈卖出应抵消到对应买入仓位，而非 FIFO 最早仓位。

Requirements: 1.1, 3.3, 3.4
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.trading import LotTakeProfitService, PositionLot
from simple_trade.services.trading.profit.lot_task_manager import LotTaskManager


def _make_deal(deal_id: str, order_id: str, trd_side: str,
               qty: int, price: float, stock_code: str = 'HK.03690',
               create_time: str = '') -> dict:
    """构造一条成交记录"""
    return {
        'deal_id': deal_id,
        'order_id': order_id,
        'trd_side': trd_side,
        'qty': qty,
        'price': price,
        'stock_code': stock_code,
        'create_time': create_time,
    }


def _create_service(tp_map: dict = None) -> LotTakeProfitService:
    """创建 mock 过的 LotTakeProfitService 实例，跳过数据库初始化"""
    mock_db = MagicMock()
    mock_db.trade_queries.get_tp_order_to_deal_map.return_value = tp_map or {}
    mock_db.execute_query.return_value = []

    with patch.object(LotTaskManager, '_init_tables'), \
         patch.object(LotTaskManager, 'load_active_tasks', return_value={}):
        svc = LotTakeProfitService(db_manager=mock_db)

    return svc


# ============================================================
# 测试 1：用户报告的具体 bug 场景（美团案例）
# Requirements: 1.1, 3.3, 3.4
# ============================================================

class TestUserReportedBugScenario:
    """
    场景：美团 13 号买入 3 次，卖出 1 次。
    卖出是 deal_003 的止盈，但旧 FIFO 错误地抵消了 12 号的 deal_old。

    成交序列：
      12号 BUY 100股 @ 130  (deal_old, order_old)
      13号 BUY 100股 @ 132  (deal_001, order_001)
      13号 BUY 200股 @ 133  (deal_002, order_002)
      13号 BUY 100股 @ 131  (deal_003, order_003)
      13号 SELL 100股 @ 138  (deal_sell_001, order_sell_001) ← deal_003 的止盈

    止盈映射：{order_sell_001: deal_003}

    正确结果：deal_old=100, deal_001=100, deal_002=200, deal_003=0（被移除）
    """

    def _build_deals(self):
        """构造美团案例的成交序列"""
        return [
            _make_deal('deal_old', 'order_old', 'BUY', 100, 130.0,
                       create_time='2024-01-12 10:00:00'),
            _make_deal('deal_001', 'order_001', 'BUY', 100, 132.0,
                       create_time='2024-01-13 10:00:00'),
            _make_deal('deal_002', 'order_002', 'BUY', 200, 133.0,
                       create_time='2024-01-13 11:00:00'),
            _make_deal('deal_003', 'order_003', 'BUY', 100, 131.0,
                       create_time='2024-01-13 14:00:00'),
            _make_deal('deal_sell_001', 'order_sell_001', 'SELL', 100, 138.0,
                       create_time='2024-01-13 15:00:00'),
        ]

    def test_take_profit_matches_correct_lot(self):
        """止盈卖出应精确抵消 deal_003，而非 FIFO 最早的 deal_old"""
        tp_map = {'order_sell_001': 'deal_003'}
        svc = _create_service(tp_map)
        deals = self._build_deals()

        lots = svc.task_manager._restore_lots_fifo(deals, 'HK.03690')

        # deal_003 被完全抵消，不应出现在结果中
        lot_ids = {lot.deal_id for lot in lots}
        assert 'deal_003' not in lot_ids, "deal_003 应被止盈卖出完全抵消"

        # 其他仓位不受影响
        lot_map = {lot.deal_id: lot for lot in lots}
        assert lot_map['deal_old'].remaining_qty == 100, "旧仓位不应被抵消"
        assert lot_map['deal_001'].remaining_qty == 100
        assert lot_map['deal_002'].remaining_qty == 200

    def test_total_remaining_equals_buy_minus_sell(self):
        """数量守恒：总买入 - 总卖出 = 总剩余 (Requirements: 3.3)"""
        tp_map = {'order_sell_001': 'deal_003'}
        svc = _create_service(tp_map)
        deals = self._build_deals()

        lots = svc.task_manager._restore_lots_fifo(deals, 'HK.03690')

        total_buy = 100 + 100 + 200 + 100  # 500
        total_sell = 100
        total_remaining = sum(lot.remaining_qty for lot in lots)
        assert total_remaining == total_buy - total_sell

    def test_old_fifo_would_produce_wrong_result(self):
        """对比：无映射时纯 FIFO 会错误地抵消 deal_old"""
        svc = _create_service(tp_map={})  # 空映射 = 纯 FIFO
        deals = self._build_deals()

        lots = svc.task_manager._restore_lots_fifo(deals, 'HK.03690')

        # 纯 FIFO 下 deal_old 被抵消，deal_003 保留 — 这是旧的错误行为
        lot_map = {lot.deal_id: lot for lot in lots}
        assert 'deal_old' not in lot_map, "纯 FIFO 下 deal_old 应被抵消"
        assert lot_map['deal_003'].remaining_qty == 100, "纯 FIFO 下 deal_003 不会被抵消"



# ============================================================
# 测试 2：无映射时回退到纯 FIFO
# Requirements: 1.2
# ============================================================

class TestFallbackToFifo:
    """无止盈映射时，卖出应按 FIFO 顺序抵消最早的买入仓位"""

    def test_no_mapping_uses_fifo_order(self):
        """无映射时按时间顺序从最早仓位开始抵消"""
        svc = _create_service(tp_map={})
        deals = [
            _make_deal('d1', 'o1', 'BUY', 100, 10.0, create_time='2024-01-01'),
            _make_deal('d2', 'o2', 'BUY', 200, 11.0, create_time='2024-01-02'),
            _make_deal('d3', 'o3', 'SELL', 150, 12.0, create_time='2024-01-03'),
        ]

        lots = svc.task_manager._restore_lots_fifo(deals, 'HK.03690')

        # d1 被完全抵消（100），d2 被部分抵消（扣 50，剩 150）
        lot_map = {lot.deal_id: lot for lot in lots}
        assert 'd1' not in lot_map, "d1 应被完全抵消并移除"
        assert lot_map['d2'].remaining_qty == 150, "d2 原 200 股，FIFO 扣 50 后剩 150"


# ============================================================
# 测试 3：映射中 deal_id 找不到对应仓位时的降级
# Requirements: 1.2（降级到 FIFO）
# ============================================================

class TestMappingDealIdNotFound:
    """映射指向不存在的 deal_id 时，应降级到 FIFO"""

    def test_invalid_deal_id_falls_back_to_fifo(self):
        """映射中的 deal_id 在仓位列表中不存在，降级到 FIFO"""
        tp_map = {'order_sell': 'deal_nonexistent'}
        svc = _create_service(tp_map)
        deals = [
            _make_deal('d1', 'o1', 'BUY', 100, 10.0),
            _make_deal('d2', 'o2', 'BUY', 200, 11.0),
            _make_deal('ds', 'order_sell', 'SELL', 100, 12.0),
        ]

        lots = svc.task_manager._restore_lots_fifo(deals, 'HK.03690')

        # 映射找不到目标仓位，回退到 FIFO，d1 被抵消
        lot_map = {lot.deal_id: lot for lot in lots}
        assert 'd1' not in lot_map, "降级到 FIFO 后 d1 应被抵消"
        assert lot_map['d2'].remaining_qty == 200


# ============================================================
# 测试 4：匹配仓位 remaining_qty 不足时的混合抵消
# Requirements: 1.1, 1.3
# ============================================================

class TestPartialMatchWithFifoSpillover:
    """匹配仓位数量不足时，不足部分应按 FIFO 继续抵消"""

    def test_partial_match_spills_to_fifo(self):
        """卖出 150 股，匹配仓位只有 100 股，剩余 50 股按 FIFO 抵消"""
        tp_map = {'order_sell': 'deal_target'}
        svc = _create_service(tp_map)
        deals = [
            _make_deal('d_early', 'o1', 'BUY', 200, 10.0,
                       create_time='2024-01-01'),
            _make_deal('deal_target', 'o2', 'BUY', 100, 11.0,
                       create_time='2024-01-02'),
            _make_deal('ds', 'order_sell', 'SELL', 150, 12.0,
                       create_time='2024-01-03'),
        ]

        lots = svc.task_manager._restore_lots_fifo(deals, 'HK.03690')

        lot_map = {lot.deal_id: lot for lot in lots}
        # deal_target 被完全抵消（100），剩余 50 按 FIFO 从 d_early 扣
        assert 'deal_target' not in lot_map, "deal_target 应被完全抵消"
        assert lot_map['d_early'].remaining_qty == 150, \
            "d_early 应被 FIFO 扣减 50，剩余 150"

    def test_quantity_conservation_with_partial_match(self):
        """混合抵消场景下数量守恒 (Requirements: 3.3)"""
        tp_map = {'order_sell': 'deal_target'}
        svc = _create_service(tp_map)
        deals = [
            _make_deal('d1', 'o1', 'BUY', 200, 10.0),
            _make_deal('deal_target', 'o2', 'BUY', 100, 11.0),
            _make_deal('ds', 'order_sell', 'SELL', 150, 12.0),
        ]

        lots = svc.task_manager._restore_lots_fifo(deals, 'HK.03690')

        total_remaining = sum(lot.remaining_qty for lot in lots)
        assert total_remaining == (200 + 100) - 150  # = 150


# ============================================================
# 测试 5：多笔止盈卖出独立匹配
# Requirements: 3.4
# ============================================================

class TestMultipleTakeProfitSells:
    """多笔止盈卖出应各自独立匹配，互不干扰"""

    def test_two_take_profit_sells_match_independently(self):
        """两笔止盈卖出分别精确匹配到各自的买入仓位"""
        tp_map = {
            'order_sell_1': 'deal_b',
            'order_sell_2': 'deal_c',
        }
        svc = _create_service(tp_map)
        deals = [
            _make_deal('deal_a', 'o1', 'BUY', 100, 10.0,
                       create_time='2024-01-01'),
            _make_deal('deal_b', 'o2', 'BUY', 100, 11.0,
                       create_time='2024-01-02'),
            _make_deal('deal_c', 'o3', 'BUY', 200, 12.0,
                       create_time='2024-01-03'),
            _make_deal('ds1', 'order_sell_1', 'SELL', 100, 13.0,
                       create_time='2024-01-04'),
            _make_deal('ds2', 'order_sell_2', 'SELL', 200, 14.0,
                       create_time='2024-01-05'),
        ]

        lots = svc.task_manager._restore_lots_fifo(deals, 'HK.03690')

        # deal_b 和 deal_c 被各自的止盈卖出完全抵消
        lot_ids = {lot.deal_id for lot in lots}
        assert lot_ids == {'deal_a'}, "只有 deal_a 应保留"
        assert lots[0].remaining_qty == 100