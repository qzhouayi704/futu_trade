#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风控集成到交易链路的单元测试

验证 FutuTradeService.execute_trade() 中的风控检查逻辑：
- REJECT: 高紧急度风控信号阻止买入
- WARN: 中低紧急度风控信号记录警告并继续
- 无持仓数据时跳过风控检查
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.core.validation.risk_checker import RiskAction, RiskCheckResult
from simple_trade.core.models.stock_info import StockInfo

# 测试用股票信息
_TEST_STOCK = StockInfo(code='HK.00700', name='腾讯控股', id=1)


# ============================================================
# 辅助工厂
# ============================================================

def _make_risk_result(action: RiskAction, should_sell: bool,
                      urgency: int, reason: str = '测试原因') -> RiskCheckResult:
    return RiskCheckResult(
        stock_code='HK.00700',
        action=action,
        reason=reason,
        should_sell=should_sell,
        urgency=urgency,
    )


def _make_service():
    """构造一个可测试的 FutuTradeService（mock 掉外部依赖）"""
    os.environ['FUTU_TRADE_PASSWORD'] = 'test_password'
    try:
        with patch('simple_trade.services.trading.futu_trade_service.OrderManager'), \
             patch('simple_trade.services.trading.futu_trade_service.PositionManager'), \
             patch('simple_trade.services.trading.futu_trade_service.AccountManager'):
            from simple_trade.services.trading import FutuTradeService
            db = MagicMock()
            cfg = MagicMock()
            svc = FutuTradeService(db, cfg)
            # mock 交易准备状态
            svc.is_trade_ready = MagicMock(return_value=True)
            return svc
    finally:
        pass  # 保留环境变量供后续测试使用


# ============================================================
# 风控拒绝测试
# ============================================================

class TestRiskReject:
    """高紧急度风控信号应阻止买入交易"""

    def test_stop_loss_rejects_buy(self):
        """止损信号（urgency=10）应拒绝买入"""
        svc = _make_service()
        risk_result = _make_risk_result(
            RiskAction.STOP_LOSS, should_sell=True, urgency=10,
            reason='固定止损: 亏损 -6.00% <= -5.0%'
        )
        svc._check_trade_risk = MagicMock(return_value=risk_result)

        result = svc.execute_trade(_TEST_STOCK, 'BUY', 100.0, 100)

        assert result['success'] is False
        assert '风控拒绝' in result['message']
        assert '固定止损' in result['message']

    def test_take_profit_rejects_buy(self):
        """目标止盈信号（urgency=8）应拒绝买入"""
        svc = _make_service()
        risk_result = _make_risk_result(
            RiskAction.TAKE_PROFIT, should_sell=True, urgency=8,
            reason='目标止盈: 盈利 9.00% >= 8.0%'
        )
        svc._check_trade_risk = MagicMock(return_value=risk_result)

        result = svc.execute_trade(_TEST_STOCK, 'BUY', 100.0, 100)

        assert result['success'] is False
        assert '风控拒绝' in result['message']

    def test_quick_stop_rejects_buy(self):
        """快速止损信号（urgency=9）应拒绝买入"""
        svc = _make_service()
        risk_result = _make_risk_result(
            RiskAction.QUICK_STOP, should_sell=True, urgency=9
        )
        svc._check_trade_risk = MagicMock(return_value=risk_result)

        result = svc.execute_trade(_TEST_STOCK, 'BUY', 100.0, 100)

        assert result['success'] is False
        assert '风控拒绝' in result['message']


# ============================================================
# 风控警告测试
# ============================================================

class TestRiskWarn:
    """中低紧急度风控信号应记录警告但不阻止交易"""

    def test_plate_stop_warns_but_continues(self):
        """板块止损（urgency=6）应警告但继续"""
        svc = _make_service()
        risk_result = _make_risk_result(
            RiskAction.PLATE_STOP, should_sell=True, urgency=6,
            reason='板块止损: 板块跌出前5名'
        )
        svc._check_trade_risk = MagicMock(return_value=risk_result)
        svc.order_manager.create_trade_record = MagicMock(return_value=1)
        svc.order_manager.place_order = MagicMock(return_value={
            'success': True, 'futu_order_id': 'ORD001'
        })
        svc.order_manager.update_trade_record = MagicMock()

        result = svc.execute_trade(_TEST_STOCK, 'BUY', 100.0, 100)

        assert result['success'] is True

    def test_time_stop_warns_but_continues(self):
        """时间止损（urgency=5）应警告但继续"""
        svc = _make_service()
        risk_result = _make_risk_result(
            RiskAction.TIME_STOP, should_sell=True, urgency=5
        )
        svc._check_trade_risk = MagicMock(return_value=risk_result)
        svc.order_manager.create_trade_record = MagicMock(return_value=1)
        svc.order_manager.place_order = MagicMock(return_value={
            'success': True, 'futu_order_id': 'ORD002'
        })
        svc.order_manager.update_trade_record = MagicMock()

        result = svc.execute_trade(_TEST_STOCK, 'BUY', 100.0, 100)

        assert result['success'] is True


# ============================================================
# 风控通过 / 跳过测试
# ============================================================

class TestRiskPassOrSkip:
    """HOLD 结果或无持仓数据时应正常继续交易"""

    def test_hold_allows_buy(self):
        """HOLD 信号不阻止买入"""
        svc = _make_service()
        risk_result = _make_risk_result(
            RiskAction.HOLD, should_sell=False, urgency=0
        )
        svc._check_trade_risk = MagicMock(return_value=risk_result)
        svc.order_manager.create_trade_record = MagicMock(return_value=1)
        svc.order_manager.place_order = MagicMock(return_value={
            'success': True, 'futu_order_id': 'ORD003'
        })
        svc.order_manager.update_trade_record = MagicMock()

        result = svc.execute_trade(_TEST_STOCK, 'BUY', 100.0, 100)

        assert result['success'] is True

    def test_no_position_skips_risk_check(self):
        """无持仓数据时 _check_trade_risk 返回 None，交易正常继续"""
        svc = _make_service()
        svc._check_trade_risk = MagicMock(return_value=None)
        svc.order_manager.create_trade_record = MagicMock(return_value=1)
        svc.order_manager.place_order = MagicMock(return_value={
            'success': True, 'futu_order_id': 'ORD004'
        })
        svc.order_manager.update_trade_record = MagicMock()

        result = svc.execute_trade(_TEST_STOCK, 'BUY', 100.0, 100)

        assert result['success'] is True

    def test_sell_not_blocked_by_risk(self):
        """卖出交易不受风控拒绝影响（即使 should_sell=True）"""
        svc = _make_service()
        risk_result = _make_risk_result(
            RiskAction.STOP_LOSS, should_sell=True, urgency=10
        )
        svc._check_trade_risk = MagicMock(return_value=risk_result)
        svc.order_manager.create_trade_record = MagicMock(return_value=1)
        svc.order_manager.place_order = MagicMock(return_value={
            'success': True, 'futu_order_id': 'ORD005'
        })
        svc.order_manager.update_trade_record = MagicMock()

        result = svc.execute_trade(_TEST_STOCK, 'SELL', 100.0, 100)

        assert result['success'] is True


# ============================================================
# 辅助方法测试
# ============================================================

class TestHelperMethods:
    """测试 _get_entry_price 和 _get_entry_date"""

    def test_get_entry_price_found(self):
        svc = _make_service()
        svc.db_manager.execute_query = MagicMock(return_value=[(50.5,)])

        price = svc._get_entry_price('HK.00700')

        assert price == 50.5

    def test_get_entry_price_not_found(self):
        svc = _make_service()
        svc.db_manager.execute_query = MagicMock(return_value=[])

        price = svc._get_entry_price('HK.00700')

        assert price == 0.0

    def test_get_entry_date_found(self):
        svc = _make_service()
        svc.db_manager.execute_query = MagicMock(
            return_value=[('2025-01-15 10:30:00',)]
        )

        d = svc._get_entry_date('HK.00700')

        assert d == date(2025, 1, 15)

    def test_get_entry_date_not_found(self):
        svc = _make_service()
        svc.db_manager.execute_query = MagicMock(return_value=[])

        d = svc._get_entry_date('HK.00700')

        assert d is None

    def test_check_trade_risk_no_position(self):
        """无持仓时 _check_trade_risk 返回 None"""
        svc = _make_service()
        svc._get_entry_price = MagicMock(return_value=0.0)
        svc._get_entry_date = MagicMock(return_value=None)

        result = svc._check_trade_risk('HK.00700', 'BUY', 100.0)

        assert result is None

    def test_check_trade_risk_with_position(self):
        """有持仓时 _check_trade_risk 调用 risk_checker"""
        svc = _make_service()
        svc._get_entry_price = MagicMock(return_value=50.0)
        svc._get_entry_date = MagicMock(return_value=date(2025, 1, 10))
        mock_result = _make_risk_result(RiskAction.HOLD, False, 0)
        svc.risk_checker.check_risk = MagicMock(return_value=mock_result)

        result = svc._check_trade_risk('HK.00700', 'BUY', 55.0)

        assert result is not None
        assert result.action == RiskAction.HOLD
        svc.risk_checker.check_risk.assert_called_once_with(
            stock_code='HK.00700',
            entry_price=50.0,
            current_price=55.0,
            entry_date=date(2025, 1, 10),
        )
