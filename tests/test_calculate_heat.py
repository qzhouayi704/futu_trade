#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StockFilterHeatPipeline._calculate_heat_for_active_stocks() 单元测试

验证热度计算集成逻辑：
- 基础模式使用 heat_score 字段
- 增强模式使用 total_heat 字段
- 无热度分数的股票设置 heat_score=0
- 异常时所有股票 heat_score=0
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.subscription.stock_filter_heat_pipeline import (
    StockFilterHeatPipeline,
)


def _make_pipeline(enhanced_enabled=False):
    """创建 Pipeline 实例，mock heat_calculator"""
    heat_calculator = MagicMock()
    heat_calculator.enhanced_enabled = enhanced_enabled
    return StockFilterHeatPipeline(
        activity_filter=MagicMock(),
        heat_calculator=heat_calculator,
    )


def _make_stock(code, market="HK"):
    return {"code": code, "market": market, "activity_score": 0.8}


class TestBasicMode:
    """基础模式热度计算"""

    def test_basic_mode_attaches_heat_score(self):
        """基础模式下使用 heat_score 字段"""
        pipeline = _make_pipeline(enhanced_enabled=False)
        pipeline.heat_calculator.calculate_realtime_heat_scores.return_value = {
            "HK.00700": {"heat_score": 85.0, "volume_ratio": 1.5},
            "HK.09988": {"heat_score": 72.0, "volume_ratio": 1.2},
        }
        stocks = [_make_stock("HK.00700"), _make_stock("HK.09988")]
        result = pipeline._calculate_heat_for_active_stocks(stocks)

        assert len(result) == 2
        assert result[0]["heat_score"] == 85.0
        assert result[1]["heat_score"] == 72.0
        pipeline.heat_calculator.calculate_realtime_heat_scores.assert_called_once()

    def test_basic_mode_missing_stock_gets_zero(self):
        """基础模式下未返回热度的股票 heat_score=0"""
        pipeline = _make_pipeline(enhanced_enabled=False)
        pipeline.heat_calculator.calculate_realtime_heat_scores.return_value = {
            "HK.00700": {"heat_score": 85.0},
        }
        stocks = [_make_stock("HK.00700"), _make_stock("HK.09988")]
        result = pipeline._calculate_heat_for_active_stocks(stocks)

        assert result[0]["heat_score"] == 85.0
        assert result[1]["heat_score"] == 0


class TestEnhancedMode:
    """增强模式热度计算"""

    def test_enhanced_mode_uses_total_heat(self):
        """增强模式下使用 total_heat 字段"""
        pipeline = _make_pipeline(enhanced_enabled=True)
        pipeline.heat_calculator.calculate_enhanced_heat_scores.return_value = {
            "HK.00700": {"total_heat": 92.5, "base_heat": 60, "capital_heat": 20},
        }
        stocks = [_make_stock("HK.00700")]
        result = pipeline._calculate_heat_for_active_stocks(stocks)

        assert result[0]["heat_score"] == 92.5
        pipeline.heat_calculator.calculate_enhanced_heat_scores.assert_called_once()

    def test_enhanced_mode_not_call_basic(self):
        """增强模式下不调用基础模式"""
        pipeline = _make_pipeline(enhanced_enabled=True)
        pipeline.heat_calculator.calculate_enhanced_heat_scores.return_value = {}
        pipeline._calculate_heat_for_active_stocks([_make_stock("HK.00700")])

        pipeline.heat_calculator.calculate_realtime_heat_scores.assert_not_called()


class TestEdgeCases:
    """边界情况"""

    def test_empty_list(self):
        """空列表直接返回空"""
        pipeline = _make_pipeline()
        result = pipeline._calculate_heat_for_active_stocks([])
        assert result == []

    def test_exception_sets_all_zero(self):
        """热度计算异常时所有股票 heat_score=0"""
        pipeline = _make_pipeline(enhanced_enabled=False)
        pipeline.heat_calculator.calculate_realtime_heat_scores.side_effect = (
            RuntimeError("API 超时")
        )
        stocks = [_make_stock("HK.00700"), _make_stock("HK.09988")]
        result = pipeline._calculate_heat_for_active_stocks(stocks)

        assert all(s["heat_score"] == 0 for s in result)

    def test_passes_correct_stock_codes(self):
        """验证传递给热度计算器的股票代码列表正确"""
        pipeline = _make_pipeline(enhanced_enabled=False)
        pipeline.heat_calculator.calculate_realtime_heat_scores.return_value = {}
        stocks = [_make_stock("HK.00700"), _make_stock("US.AAPL", "US")]
        pipeline._calculate_heat_for_active_stocks(stocks)

        call_args = pipeline.heat_calculator.calculate_realtime_heat_scores.call_args
        assert call_args[0][0] == ["HK.00700", "US.AAPL"]
