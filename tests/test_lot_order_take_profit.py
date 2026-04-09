#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单笔订单止盈服务单元测试"""

import os
import sys
import sqlite3
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.services.trading import LotOrderTakeProfitService


def _create_test_db() -> DatabaseManager:
    """创建内存数据库并初始化表结构"""
    db = DatabaseManager(':memory:')
    db.execute_update('''
        CREATE TABLE IF NOT EXISTS take_profit_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL, stock_name TEXT,
            take_profit_pct REAL NOT NULL, status TEXT DEFAULT 'ACTIVE',
            total_lots INTEGER DEFAULT 0, sold_lots INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    db.execute_update('''
        CREATE TABLE IF NOT EXISTS take_profit_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL, stock_code TEXT NOT NULL,
            lot_buy_price REAL NOT NULL, lot_quantity INTEGER NOT NULL,
            trigger_price REAL NOT NULL, sell_price REAL,
            profit_amount REAL, status TEXT DEFAULT 'PENDING',
            triggered_at TIMESTAMP, executed_at TIMESTAMP,
            error_msg TEXT, deal_id TEXT, order_id TEXT,
            FOREIGN KEY (task_id) REFERENCES take_profit_tasks(id)
        )
    ''')
    db.execute_update('''
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL, name TEXT, market TEXT
        )
    ''')
    db.execute_insert(
        "INSERT INTO stocks (code, name, market) VALUES (?, ?, ?)",
        ('HK.00700', '腾讯控股', 'HK'),
    )
    return db


class TestCreateLotTakeProfit(unittest.TestCase):
    """测试 create_lot_take_profit"""

    def setUp(self):
        self.db = _create_test_db()
        self.svc = LotOrderTakeProfitService(self.db)

    def test_create_success(self):
        result = self.svc.create_lot_take_profit(
            'HK.00700', 'deal_001', 350.0, 200, 10.0,
        )
        self.assertTrue(result['success'])
        self.assertEqual(result['data']['status'], 'PENDING')
        self.assertAlmostEqual(result['data']['trigger_price'], 385.0, places=2)

    def test_reject_negative_pct(self):
        result = self.svc.create_lot_take_profit(
            'HK.00700', 'deal_001', 350.0, 200, -5.0,
        )
        self.assertFalse(result['success'])
        self.assertIn('大于 0', result['message'])

    def test_reject_zero_pct(self):
        result = self.svc.create_lot_take_profit(
            'HK.00700', 'deal_001', 350.0, 200, 0,
        )
        self.assertFalse(result['success'])

    def test_reject_duplicate_active_deal(self):
        self.svc.create_lot_take_profit('HK.00700', 'deal_001', 350.0, 200, 10.0)
        result = self.svc.create_lot_take_profit('HK.00700', 'deal_001', 350.0, 200, 15.0)
        self.assertFalse(result['success'])
        self.assertIn('已有活跃', result['message'])

    def test_allow_after_cancel(self):
        r1 = self.svc.create_lot_take_profit('HK.00700', 'deal_001', 350.0, 200, 10.0)
        self.svc.cancel_lot_take_profit(r1['data']['id'])
        r2 = self.svc.create_lot_take_profit('HK.00700', 'deal_001', 350.0, 200, 15.0)
        self.assertTrue(r2['success'])

    def test_trigger_price_calculation(self):
        result = self.svc.create_lot_take_profit(
            'HK.00700', 'deal_002', 100.0, 100, 5.0,
        )
        self.assertAlmostEqual(result['data']['trigger_price'], 105.0, places=2)


class TestCancelLotTakeProfit(unittest.TestCase):
    """测试 cancel_lot_take_profit"""

    def setUp(self):
        self.db = _create_test_db()
        self.svc = LotOrderTakeProfitService(self.db)

    def test_cancel_success(self):
        r = self.svc.create_lot_take_profit('HK.00700', 'deal_001', 350.0, 200, 10.0)
        result = self.svc.cancel_lot_take_profit(r['data']['id'])
        self.assertTrue(result['success'])

    def test_cancel_nonexistent(self):
        result = self.svc.cancel_lot_take_profit(9999)
        self.assertFalse(result['success'])
        self.assertIn('不存在', result['message'])

    def test_cancel_already_cancelled(self):
        r = self.svc.create_lot_take_profit('HK.00700', 'deal_001', 350.0, 200, 10.0)
        self.svc.cancel_lot_take_profit(r['data']['id'])
        result = self.svc.cancel_lot_take_profit(r['data']['id'])
        self.assertFalse(result['success'])
        self.assertIn('不可取消', result['message'])


class TestGetConfigs(unittest.TestCase):
    """测试查询方法"""

    def setUp(self):
        self.db = _create_test_db()
        self.svc = LotOrderTakeProfitService(self.db)

    def test_get_configs_empty(self):
        configs = self.svc.get_lot_take_profit_configs('HK.00700')
        self.assertEqual(configs, [])

    def test_get_configs_after_create(self):
        self.svc.create_lot_take_profit('HK.00700', 'deal_001', 350.0, 200, 10.0)
        self.svc.create_lot_take_profit('HK.00700', 'deal_002', 360.0, 100, 8.0)
        configs = self.svc.get_lot_take_profit_configs('HK.00700')
        self.assertEqual(len(configs), 2)
        self.assertEqual(configs[0]['deal_id'], 'deal_002')  # 按 id DESC 排序

    def test_get_lots_with_status(self):
        self.svc.create_lot_take_profit('HK.00700', 'deal_001', 350.0, 200, 10.0)
        lots = [
            {'deal_id': 'deal_001', 'buy_price': 350.0, 'quantity': 200},
            {'deal_id': 'deal_002', 'buy_price': 360.0, 'quantity': 100},
        ]
        result = self.svc.get_lots_with_take_profit_status('HK.00700', lots)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['take_profit_status'], 'PENDING')
        self.assertIsNotNone(result[0]['execution_id'])
        self.assertIsNone(result[1]['take_profit_status'])


class TestExecuteMarketSell(unittest.TestCase):
    """测试 execute_market_sell（无交易服务时）"""

    def setUp(self):
        self.db = _create_test_db()
        self.svc = LotOrderTakeProfitService(self.db)

    def test_no_trade_service(self):
        r = self.svc.create_lot_take_profit('HK.00700', 'deal_001', 350.0, 200, 10.0)
        result = self.svc.execute_market_sell(r['data']['id'], 'HK.00700', 200)
        self.assertFalse(result['success'])
        self.assertIn('未就绪', result['message'])


if __name__ == '__main__':
    unittest.main()
