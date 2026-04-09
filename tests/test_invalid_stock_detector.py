#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
InvalidStockDetector 单元测试

验证无效股票检测器的三个核心方法：
- is_invalid_stock_error: 错误消息分类
- detect_invalid_stocks: 批量检测
- remove_invalid_stocks: 数据库清理
"""

import unittest
from unittest.mock import MagicMock, patch, call

from simple_trade.services.market_data.invalid_stock_detector import (
    InvalidStockDetector,
)


class TestIsInvalidStockError(unittest.TestCase):
    """测试 is_invalid_stock_error 方法"""

    def setUp(self):
        self.detector = InvalidStockDetector(futu_client=MagicMock())

    def test_otc_keyword_detected(self):
        """OTC 关键词应被识别为无效股票错误"""
        self.assertTrue(self.detector.is_invalid_stock_error("暂不提供美股 OTC 市场行情"))
        self.assertTrue(self.detector.is_invalid_stock_error("这是OTC股票"))
        self.assertTrue(self.detector.is_invalid_stock_error("OTC市场不支持"))

    def test_unknown_stock_keyword_detected(self):
        """未知股票关键词应被识别为无效股票错误"""
        self.assertTrue(self.detector.is_invalid_stock_error("未知股票代码"))
        self.assertTrue(self.detector.is_invalid_stock_error("unknown stock code"))
        self.assertTrue(self.detector.is_invalid_stock_error("无效股票"))
        self.assertTrue(self.detector.is_invalid_stock_error("invalid stock"))

    def test_case_insensitive(self):
        """关键词匹配应不区分大小写"""
        self.assertTrue(self.detector.is_invalid_stock_error("UNKNOWN STOCK"))
        self.assertTrue(self.detector.is_invalid_stock_error("Invalid Stock Code"))
        self.assertTrue(self.detector.is_invalid_stock_error("otc"))

    def test_normal_error_not_detected(self):
        """普通错误消息不应被识别为无效股票错误"""
        self.assertFalse(self.detector.is_invalid_stock_error("网络超时"))
        self.assertFalse(self.detector.is_invalid_stock_error("订阅额度不足"))
        self.assertFalse(self.detector.is_invalid_stock_error("服务器内部错误"))

    def test_empty_and_none(self):
        """空字符串和 None 应返回 False"""
        self.assertFalse(self.detector.is_invalid_stock_error(""))
        self.assertFalse(self.detector.is_invalid_stock_error(None))


class TestDetectInvalidStocks(unittest.TestCase):
    """测试 detect_invalid_stocks 方法"""

    def setUp(self):
        self.futu_client = MagicMock()
        self.detector = InvalidStockDetector(futu_client=self.futu_client)

    @patch('simple_trade.services.market_data.invalid_stock_detector.RET_OK', 0)
    @patch('simple_trade.services.market_data.invalid_stock_detector.time')
    def test_all_valid_stocks(self, mock_time):
        """所有股票都有效时，invalid 列表为空"""
        self.futu_client.client.get_market_snapshot.return_value = (0, "ok")

        invalid, valid = self.detector.detect_invalid_stocks(["HK.00700", "HK.09988"])

        self.assertEqual(invalid, [])
        self.assertEqual(valid, ["HK.00700", "HK.09988"])

    @patch('simple_trade.services.market_data.invalid_stock_detector.RET_OK', 0)
    @patch('simple_trade.services.market_data.invalid_stock_detector.time')
    def test_mixed_stocks(self, mock_time):
        """混合有效和无效股票时，正确分区"""
        def side_effect(codes):
            code = codes[0]
            if code == "US.BADOTC":
                return (-1, "暂不提供美股 OTC 市场行情")
            return (0, "ok")

        self.futu_client.client.get_market_snapshot.side_effect = side_effect

        invalid, valid = self.detector.detect_invalid_stocks(
            ["HK.00700", "US.BADOTC", "HK.09988"]
        )

        self.assertEqual(invalid, ["US.BADOTC"])
        self.assertEqual(valid, ["HK.00700", "HK.09988"])

    @patch('simple_trade.services.market_data.invalid_stock_detector.RET_OK', 0)
    @patch('simple_trade.services.market_data.invalid_stock_detector.time')
    def test_exception_treated_as_valid(self, mock_time):
        """检测异常时，股票归入有效列表（保守策略）"""
        self.futu_client.client.get_market_snapshot.side_effect = Exception("网络错误")

        invalid, valid = self.detector.detect_invalid_stocks(["HK.00700"])

        self.assertEqual(invalid, [])
        self.assertEqual(valid, ["HK.00700"])

    @patch('simple_trade.services.market_data.invalid_stock_detector.RET_OK', 0)
    @patch('simple_trade.services.market_data.invalid_stock_detector.time')
    def test_non_invalid_error_treated_as_valid(self, mock_time):
        """非无效股票的 API 错误，股票归入有效列表"""
        self.futu_client.client.get_market_snapshot.return_value = (-1, "网络超时")

        invalid, valid = self.detector.detect_invalid_stocks(["HK.00700"])

        self.assertEqual(invalid, [])
        self.assertEqual(valid, ["HK.00700"])

    def test_empty_list(self):
        """空列表输入应返回两个空列表"""
        invalid, valid = self.detector.detect_invalid_stocks([])
        self.assertEqual(invalid, [])
        self.assertEqual(valid, [])


class TestRemoveInvalidStocks(unittest.TestCase):
    """测试 remove_invalid_stocks 方法"""

    def test_removes_stocks_from_db(self):
        """应调用数据库删除无效股票"""
        db_manager = MagicMock()
        detector = InvalidStockDetector(futu_client=MagicMock(), db_manager=db_manager)

        detector.remove_invalid_stocks(["US.BADOTC", "US.DELISTED"])

        db_manager.execute_update.assert_called_once()
        call_args = db_manager.execute_update.call_args
        self.assertIn("DELETE FROM stocks", call_args[0][0])
        self.assertEqual(call_args[0][1], ["US.BADOTC", "US.DELISTED"])

    def test_no_db_manager_does_nothing(self):
        """没有 db_manager 时不报错"""
        detector = InvalidStockDetector(futu_client=MagicMock(), db_manager=None)
        detector.remove_invalid_stocks(["US.BADOTC"])  # 不应抛异常

    def test_empty_list_does_nothing(self):
        """空列表时不调用数据库"""
        db_manager = MagicMock()
        detector = InvalidStockDetector(futu_client=MagicMock(), db_manager=db_manager)

        detector.remove_invalid_stocks([])

        db_manager.execute_update.assert_not_called()

    def test_db_exception_handled(self):
        """数据库异常应被捕获，不向外抛出"""
        db_manager = MagicMock()
        db_manager.execute_update.side_effect = Exception("DB连接失败")
        detector = InvalidStockDetector(futu_client=MagicMock(), db_manager=db_manager)

        detector.remove_invalid_stocks(["US.BADOTC"])  # 不应抛异常


if __name__ == '__main__':
    unittest.main()
