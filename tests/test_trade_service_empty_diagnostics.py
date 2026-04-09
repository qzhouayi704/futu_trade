#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeService._get_enhanced_stock_data 空结果诊断日志单元测试

验证三种空结果场景下的 warning 日志输出：
1. 股票池为空
2. 实时报价返回空数据
3. 报价匹配为零

Validates: Requirements 4.1
"""

import logging
from unittest.mock import MagicMock

import pytest

from simple_trade.services.trading.trade_service import TradeService


@pytest.fixture
def trade_service():
    """创建带 mock 依赖的 TradeService 实例"""
    db_manager = MagicMock()
    config = MagicMock()
    realtime_service = MagicMock()
    return TradeService(
        db_manager=db_manager,
        config=config,
        realtime_service=realtime_service,
    )


class TestGetEnhancedStockDataDiagnostics:
    """_get_enhanced_stock_data 三种空结果场景的诊断日志"""

    def test_empty_stock_pool_logs_warning(self, trade_service, caplog):
        """场景1: 股票池为空 → warning 日志包含原因"""
        with caplog.at_level(logging.WARNING):
            result = trade_service._get_enhanced_stock_data([])

        assert result == []
        assert any("股票池为空" in r.message for r in caplog.records)
        # 确认是 WARNING 级别
        warning_records = [r for r in caplog.records if "股票池为空" in r.message]
        assert warning_records[0].levelno == logging.WARNING

    def test_realtime_quotes_empty_data_logs_warning(self, trade_service, caplog):
        """场景2: 实时报价返回空数据 → warning 日志包含请求股票数"""
        stock_pool = [
            {'id': 1, 'code': 'HK.00700', 'name': '腾讯控股'},
            {'id': 2, 'code': 'HK.09988', 'name': '阿里巴巴'},
        ]
        trade_service.realtime_service.get_realtime_quotes.return_value = {
            'success': True,
            'quotes': [],  # 返回空报价列表
        }

        with caplog.at_level(logging.WARNING):
            result = trade_service._get_enhanced_stock_data(stock_pool)

        assert result == []
        assert any("实时报价返回空数据" in r.message for r in caplog.records)
        # 验证日志包含请求的股票数量
        warning_records = [r for r in caplog.records if "实时报价返回空数据" in r.message]
        assert "2" in warning_records[0].message

    def test_zero_match_logs_warning(self, trade_service, caplog):
        """场景3: 报价匹配为零 → warning 日志包含请求数和返回数"""
        stock_pool = [
            {'id': 1, 'code': 'HK.00700', 'name': '腾讯控股'},
        ]
        # 报价返回了数据，但股票代码不匹配
        trade_service.realtime_service.get_realtime_quotes.return_value = {
            'success': True,
            'quotes': [
                {
                    'code': 'HK.09999',  # 与请求的代码不同
                    'last_price': 100.0,
                    'change_percent': 1.5,
                    'volume': 1000000,
                    'high_price': 105.0,
                    'low_price': 95.0,
                    'open_price': 98.0,
                },
            ],
        }

        with caplog.at_level(logging.WARNING):
            result = trade_service._get_enhanced_stock_data(stock_pool)

        assert result == []
        assert any("报价匹配为零" in r.message for r in caplog.records)
        warning_records = [r for r in caplog.records if "报价匹配为零" in r.message]
        msg = warning_records[0].message
        # 验证日志包含请求数和返回数
        assert "1" in msg  # 请求 1 只
        assert "无交集" in msg
