#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MarketTimeHelper.is_market_trading 与 QuotePipeline._filter_trading_quotes 单元测试

回归保护：2026-06-22 修复"美股时段(北京 21:30~04:00)拿港股昨收快照空跑，
凌晨广播出'防守触发'假信号"。核心是严格的 per-market 交易判断 + 喂引擎前按
市场过滤报价。

覆盖：
- 港股：盘中 / 夜间 / 午休 / 周末 / 节假日(交易日历)
- 美股：夏令晚段 / 夏令凌晨 / 周一凌晨(应闭市) / 周六凌晨(周五延续) / 周末夜
- 冬令时切换
- _filter_trading_quotes：剔除非交易市场、保留交易市场、全闭市返回空、空 code 跳过
"""

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.utils.market_helper import MarketTimeHelper
from simple_trade.core.pipeline.quote_pipeline import QuotePipeline


# ============================================================
# is_market_trading — 港股
# ============================================================

class TestIsMarketTradingHK:
    """港股交易判断（交易日历统一 patch 为 True，隔离时段/工作日逻辑）"""

    @patch.object(MarketTimeHelper, 'is_trading_day', return_value=True)
    def test_hk_session_morning(self, _cal):
        # 2026-06-24 周三 10:30 盘中
        assert MarketTimeHelper.is_market_trading('HK', datetime(2026, 6, 24, 10, 30)) is True

    @patch.object(MarketTimeHelper, 'is_trading_day', return_value=True)
    def test_hk_session_afternoon(self, _cal):
        # 周三 14:00 盘中
        assert MarketTimeHelper.is_market_trading('HK', datetime(2026, 6, 24, 14, 0)) is True

    @patch.object(MarketTimeHelper, 'is_trading_day', return_value=True)
    def test_hk_night_is_closed(self, _cal):
        # 周三 03:57 夜间 —— 正是 bug 场景，必须为 False
        assert MarketTimeHelper.is_market_trading('HK', datetime(2026, 6, 24, 3, 57)) is False

    @patch.object(MarketTimeHelper, 'is_trading_day', return_value=True)
    def test_hk_lunch_break(self, _cal):
        # 周三 12:30 午休
        assert MarketTimeHelper.is_market_trading('HK', datetime(2026, 6, 24, 12, 30)) is False

    @patch.object(MarketTimeHelper, 'is_trading_day', return_value=True)
    def test_hk_weekend(self, _cal):
        # 2026-06-27 周六 10:30
        assert MarketTimeHelper.is_market_trading('HK', datetime(2026, 6, 27, 10, 30)) is False

    @patch.object(MarketTimeHelper, 'is_trading_day', return_value=False)
    def test_hk_holiday_blocked(self, _cal):
        # 交易日历判定为节假日 —— 即便在盘中时段也不算交易
        assert MarketTimeHelper.is_market_trading('HK', datetime(2026, 6, 24, 10, 30)) is False

    @patch.object(MarketTimeHelper, 'is_trading_day', return_value=True)
    def test_hk_open_close_edges(self, _cal):
        # 09:30 开盘、16:00 收盘（含端点）
        assert MarketTimeHelper.is_market_trading('HK', datetime(2026, 6, 24, 9, 30)) is True
        assert MarketTimeHelper.is_market_trading('HK', datetime(2026, 6, 24, 16, 0)) is True


# ============================================================
# is_market_trading — 美股
# ============================================================

class TestIsMarketTradingUS:
    """美股交易判断（按北京时间跨午夜 + 周末边界）"""

    def test_us_summer_evening(self):
        # 2026-06-25 周四 22:00 夏令晚段
        assert MarketTimeHelper.is_market_trading('US', datetime(2026, 6, 25, 22, 0)) is True

    def test_us_summer_morning(self):
        # 周三 03:57 夏令凌晨（美东周二延续）
        assert MarketTimeHelper.is_market_trading('US', datetime(2026, 6, 24, 3, 57)) is True

    def test_us_monday_predawn_closed(self):
        # 2026-06-22 周一 03:57 —— 美东周日，无交易
        assert MarketTimeHelper.is_market_trading('US', datetime(2026, 6, 22, 3, 57)) is False

    def test_us_saturday_predawn_friday_cont(self):
        # 2026-06-27 周六 03:57 —— 美东周五延续，交易中
        assert MarketTimeHelper.is_market_trading('US', datetime(2026, 6, 27, 3, 57)) is True

    def test_us_saturday_night_closed(self):
        # 周六 22:00 —— 周末夜，无交易
        assert MarketTimeHelper.is_market_trading('US', datetime(2026, 6, 27, 22, 0)) is False

    def test_us_daytime_closed(self):
        # 周三 14:00 北京白天 —— 美股闭市
        assert MarketTimeHelper.is_market_trading('US', datetime(2026, 6, 24, 14, 0)) is False

    def test_us_winter_evening(self):
        # 2026-01-07 周三 22:45 冬令晚段（22:30 开）
        assert MarketTimeHelper.is_market_trading('US', datetime(2026, 1, 7, 22, 45)) is True
        # 冬令时 22:00 尚未开盘
        assert MarketTimeHelper.is_market_trading('US', datetime(2026, 1, 7, 22, 0)) is False


# ============================================================
# is_market_trading — 其它
# ============================================================

class TestIsMarketTradingMisc:

    def test_unknown_market(self):
        assert MarketTimeHelper.is_market_trading('XX', datetime(2026, 6, 24, 10, 30)) is False

    def test_force_market_override(self):
        MarketTimeHelper.set_force_market('US')
        try:
            assert MarketTimeHelper.is_market_trading('US') is True
            assert MarketTimeHelper.is_market_trading('HK') is False
        finally:
            MarketTimeHelper.clear_force_market()


# ============================================================
# QuotePipeline._filter_trading_quotes
# ============================================================

def _make_pipeline():
    return QuotePipeline(MagicMock(), MagicMock(), MagicMock())


class TestFilterTradingQuotes:
    """喂引擎前按"所属市场此刻是否交易"过滤报价"""

    def _patch_trading(self, trading_markets):
        """side_effect: 仅 trading_markets 中的市场返回 True"""
        return patch.object(
            MarketTimeHelper, 'is_market_trading',
            side_effect=lambda market, *a, **k: market in trading_markets,
        )

    def test_drops_non_trading_market(self):
        """美股时段：港股报价被剔除，美股报价保留"""
        pipeline = _make_pipeline()
        quotes = [
            {'code': 'HK.01888', 'last_price': 1.0},
            {'code': 'HK.06078', 'last_price': 2.0},
            {'code': 'US.AAPL', 'last_price': 3.0},
        ]
        with self._patch_trading({'US'}):
            result = pipeline._filter_trading_quotes(quotes)
        assert [q['code'] for q in result] == ['US.AAPL']

    def test_keeps_trading_market(self):
        """港股盘中：全部港股报价保留"""
        pipeline = _make_pipeline()
        quotes = [
            {'code': 'HK.01888', 'last_price': 1.0},
            {'code': 'HK.06078', 'last_price': 2.0},
        ]
        with self._patch_trading({'HK'}):
            result = pipeline._filter_trading_quotes(quotes)
        assert len(result) == 2

    def test_empty_when_nothing_trading(self):
        """全市场闭市：返回空，整块信号检测被跳过"""
        pipeline = _make_pipeline()
        quotes = [{'code': 'HK.01888', 'last_price': 1.0}]
        with self._patch_trading(set()):
            result = pipeline._filter_trading_quotes(quotes)
        assert result == []

    def test_skips_blank_code(self):
        """无 code 的报价直接跳过，不误判市场"""
        pipeline = _make_pipeline()
        quotes = [
            {'code': '', 'last_price': 1.0},
            {'last_price': 2.0},
            {'code': 'HK.01888', 'last_price': 3.0},
        ]
        with self._patch_trading({'HK'}):
            result = pipeline._filter_trading_quotes(quotes)
        assert [q['code'] for q in result] == ['HK.01888']

    def test_market_judged_once_per_market(self):
        """同一市场每轮只判断一次（逐市场缓存）"""
        pipeline = _make_pipeline()
        quotes = [{'code': f'HK.{i:05d}', 'last_price': 1.0} for i in range(5)]
        with self._patch_trading({'HK'}) as mock_trading:
            pipeline._filter_trading_quotes(quotes)
        assert mock_trading.call_count == 1
