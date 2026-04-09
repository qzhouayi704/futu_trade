#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StockFilterHeatPipeline._apply_market_limits_by_heat() 单元测试

验证按热度排序后应用市场限制截断的核心逻辑：
- 按市场分组并截断
- 优先股票始终保留
- 按 heat_score 从高到低排序截断
- 空列表和边界情况
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.subscription.stock_filter_heat_pipeline import (
    StockFilterHeatPipeline,
)


# ============================================================
# 测试辅助
# ============================================================


def _make_pipeline(config=None):
    """创建 Pipeline 实例（仅需测试 _apply_market_limits_by_heat，依赖可 mock）"""
    return StockFilterHeatPipeline(
        activity_filter=MagicMock(),
        heat_calculator=MagicMock(),
        config=config or {},
    )


def _make_stock(code, market, heat_score, is_priority=False):
    """构造测试用股票数据"""
    return {
        "code": code,
        "market": market,
        "heat_score": heat_score,
        "is_priority": is_priority,
    }


# ============================================================
# 基本截断逻辑
# ============================================================


class TestBasicTruncation:

    def test_empty_list(self):
        """空列表返回空"""
        pipeline = _make_pipeline()
        result = pipeline._apply_market_limits_by_heat([], {"HK": 5})
        assert result == []

    def test_within_limit_no_truncation(self):
        """股票数量未超限时不截断"""
        pipeline = _make_pipeline()
        stocks = [
            _make_stock("HK.00700", "HK", 80),
            _make_stock("HK.09988", "HK", 60),
        ]
        result = pipeline._apply_market_limits_by_heat(stocks, {"HK": 5})
        assert len(result) == 2

    def test_truncation_keeps_highest_heat(self):
        """截断后保留热度最高的股票"""
        pipeline = _make_pipeline()
        stocks = [
            _make_stock("HK.00700", "HK", 90),
            _make_stock("HK.09988", "HK", 30),
            _make_stock("HK.01810", "HK", 70),
            _make_stock("HK.02318", "HK", 50),
        ]
        result = pipeline._apply_market_limits_by_heat(stocks, {"HK": 2})
        codes = {s["code"] for s in result}
        assert codes == {"HK.00700", "HK.01810"}

    def test_multiple_markets(self):
        """多市场分别截断"""
        pipeline = _make_pipeline()
        stocks = [
            _make_stock("HK.00700", "HK", 90),
            _make_stock("HK.09988", "HK", 80),
            _make_stock("HK.01810", "HK", 70),
            _make_stock("US.AAPL", "US", 95),
            _make_stock("US.GOOG", "US", 85),
            _make_stock("US.MSFT", "US", 75),
        ]
        result = pipeline._apply_market_limits_by_heat(stocks, {"HK": 2, "US": 1})
        hk_stocks = [s for s in result if s["market"] == "HK"]
        us_stocks = [s for s in result if s["market"] == "US"]
        assert len(hk_stocks) == 2
        assert len(us_stocks) == 1
        assert us_stocks[0]["code"] == "US.AAPL"


# ============================================================
# 优先股票保留
# ============================================================


class TestPriorityStocks:

    def test_priority_by_is_priority_flag(self):
        """is_priority=True 的股票始终保留"""
        pipeline = _make_pipeline()
        stocks = [
            _make_stock("HK.00700", "HK", 10, is_priority=True),
            _make_stock("HK.09988", "HK", 90),
            _make_stock("HK.01810", "HK", 80),
        ]
        result = pipeline._apply_market_limits_by_heat(stocks, {"HK": 2})
        codes = {s["code"] for s in result}
        # 优先股 HK.00700 保留 + 热度最高的 HK.09988
        assert "HK.00700" in codes
        assert len(result) == 2

    def test_priority_by_code_list(self):
        """通过 priority_stocks 参数指定的股票始终保留"""
        pipeline = _make_pipeline()
        stocks = [
            _make_stock("HK.00700", "HK", 10),
            _make_stock("HK.09988", "HK", 90),
            _make_stock("HK.01810", "HK", 80),
        ]
        result = pipeline._apply_market_limits_by_heat(
            stocks, {"HK": 2}, priority_stocks=["HK.00700"]
        )
        codes = {s["code"] for s in result}
        assert "HK.00700" in codes
        assert len(result) == 2

    def test_priority_exceeds_limit(self):
        """优先股票数量超过限制时，全部保留（不截断优先股）"""
        pipeline = _make_pipeline()
        stocks = [
            _make_stock("HK.00700", "HK", 50, is_priority=True),
            _make_stock("HK.09988", "HK", 40, is_priority=True),
            _make_stock("HK.01810", "HK", 30, is_priority=True),
            _make_stock("HK.02318", "HK", 90),
        ]
        result = pipeline._apply_market_limits_by_heat(stocks, {"HK": 2})
        # 3 只优先股全部保留，普通股无名额
        assert len(result) == 3
        codes = {s["code"] for s in result}
        assert "HK.02318" not in codes


# ============================================================
# 默认限制与缺失市场
# ============================================================


class TestDefaultLimit:

    def test_default_market_limit_from_config(self):
        """未在 market_limits 中指定的市场使用 config 中的默认值"""
        pipeline = _make_pipeline(config={"default_market_limit": 1})
        stocks = [
            _make_stock("HK.00700", "HK", 90),
            _make_stock("HK.09988", "HK", 80),
        ]
        result = pipeline._apply_market_limits_by_heat(stocks, {})
        assert len(result) == 1
        assert result[0]["code"] == "HK.00700"

    def test_default_limit_50_when_no_config(self):
        """无 config 时默认每市场 50 只"""
        pipeline = _make_pipeline()
        stocks = [_make_stock(f"HK.{i:05d}", "HK", i) for i in range(60)]
        result = pipeline._apply_market_limits_by_heat(stocks, {})
        assert len(result) == 50

    def test_unknown_market(self):
        """无 market 字段的股票归入 Unknown 市场"""
        pipeline = _make_pipeline()
        stocks = [{"code": "X.001", "heat_score": 50}]
        result = pipeline._apply_market_limits_by_heat(stocks, {"Unknown": 1})
        assert len(result) == 1


# ============================================================
# execute() 方法测试
# ============================================================


class TestExecute:
    """测试 Pipeline.execute() 的完整流程和降级策略"""

    def _make_pipeline_with_mocks(self):
        """创建带 mock 依赖的 Pipeline"""
        activity_filter = MagicMock()
        heat_calculator = MagicMock()
        heat_calculator.enhanced_enabled = False
        pipeline = StockFilterHeatPipeline(
            activity_filter=activity_filter,
            heat_calculator=heat_calculator,
        )
        return pipeline, activity_filter, heat_calculator

    def test_normal_flow(self):
        """正常流程：活跃度筛选 → 热度计算 → 截断"""
        pipeline, activity_filter, heat_calc = self._make_pipeline_with_mocks()

        active = [
            _make_stock("HK.00700", "HK", 0),
            _make_stock("HK.09988", "HK", 0),
            _make_stock("US.AAPL", "US", 0),
        ]
        # 活跃度筛选返回活跃股票
        activity_filter.filter_active_stocks.return_value = active
        # 热度计算返回分数
        heat_calc.calculate_realtime_heat_scores.return_value = {
            "HK.00700": {"heat_score": 90},
            "HK.09988": {"heat_score": 70},
            "US.AAPL": {"heat_score": 85},
        }

        all_stocks = active + [_make_stock("HK.01810", "HK", 0)]
        result = pipeline.execute(
            stocks=all_stocks,
            market_limits={"HK": 1, "US": 1},
            activity_config={"min_turnover_rate": 0.5},
        )

        assert result.success is True
        assert result.total_count == 4
        assert result.active_count == 3
        assert result.final_count == len(result.stocks)
        assert len(result.errors) == 0
        # HK 市场只保留 1 只（热度最高的 HK.00700）
        hk = [s for s in result.stocks if s["market"] == "HK"]
        assert len(hk) == 1
        assert hk[0]["code"] == "HK.00700"

    def test_activity_filter_failure_degrades(self):
        """活跃度筛选失败时降级：直接截断原始列表"""
        pipeline, activity_filter, _ = self._make_pipeline_with_mocks()
        activity_filter.filter_active_stocks.side_effect = RuntimeError("连接超时")

        stocks = [
            _make_stock("HK.00700", "HK", 0),
            _make_stock("HK.09988", "HK", 0),
        ]
        result = pipeline.execute(
            stocks=stocks,
            market_limits={"HK": 10},
            activity_config={},
        )

        assert result.success is False
        assert result.active_count == 0
        assert result.heat_calculated_count == 0
        assert len(result.errors) == 1
        assert "活跃度筛选失败" in result.errors[0]
        # 降级后仍返回股票（直接截断原始列表）
        assert result.final_count == len(result.stocks)

    def test_heat_calculation_failure_uses_activity_score(self):
        """热度计算异常时，_calculate_heat_for_active_stocks 内部降级为 heat_score=0"""
        pipeline, activity_filter, heat_calc = self._make_pipeline_with_mocks()

        active = [
            _make_stock("HK.00700", "HK", 0),
            _make_stock("HK.09988", "HK", 0),
        ]
        active[0]["activity_score"] = 0.8
        active[1]["activity_score"] = 0.3
        activity_filter.filter_active_stocks.return_value = active
        heat_calc.calculate_realtime_heat_scores.side_effect = RuntimeError("API 异常")

        result = pipeline.execute(
            stocks=active,
            market_limits={"HK": 1},
            activity_config={},
        )

        # _calculate_heat_for_active_stocks 内部已 catch 异常，heat_score 全部为 0
        # execute 层面不会报错，但 heat_calculated_count 为 0
        assert result.success is True
        assert result.active_count == 2
        assert result.heat_calculated_count == 0
        assert result.final_count == 1

    def test_heat_method_unexpected_error_degrades_to_activity_score(self):
        """_calculate_heat_for_active_stocks 抛出未预期异常时，execute 降级用 activity_score"""
        pipeline, activity_filter, _ = self._make_pipeline_with_mocks()

        active = [
            _make_stock("HK.00700", "HK", 0),
            _make_stock("HK.09988", "HK", 0),
        ]
        active[0]["activity_score"] = 0.9
        active[1]["activity_score"] = 0.1
        activity_filter.filter_active_stocks.return_value = active
        # mock _calculate_heat_for_active_stocks 本身抛出异常
        pipeline._calculate_heat_for_active_stocks = MagicMock(
            side_effect=RuntimeError("未预期错误")
        )

        result = pipeline.execute(
            stocks=active, market_limits={"HK": 1}, activity_config={}
        )

        assert result.success is False
        assert len(result.errors) == 1
        assert "热度计算失败" in result.errors[0]
        # 降级后用 activity_score 排序，保留分数最高的
        assert len(result.stocks) == 1
        assert result.stocks[0]["code"] == "HK.00700"

    def test_empty_stocks_input(self):
        """空输入返回空结果"""
        pipeline, activity_filter, _ = self._make_pipeline_with_mocks()
        activity_filter.filter_active_stocks.return_value = []

        result = pipeline.execute(
            stocks=[], market_limits={"HK": 50}, activity_config={}
        )

        assert result.success is True
        assert result.total_count == 0
        assert result.final_count == 0
        assert result.stocks == []

    def test_pipeline_result_stats_consistency(self):
        """验证 PipelineResult 统计一致性：total >= active >= final"""
        pipeline, activity_filter, heat_calc = self._make_pipeline_with_mocks()

        all_stocks = [_make_stock(f"HK.{i:05d}", "HK", 0) for i in range(20)]
        active = all_stocks[:15]
        activity_filter.filter_active_stocks.return_value = active
        heat_calc.calculate_realtime_heat_scores.return_value = {
            s["code"]: {"heat_score": i * 5} for i, s in enumerate(active)
        }

        result = pipeline.execute(
            stocks=all_stocks, market_limits={"HK": 5}, activity_config={}
        )

        assert result.total_count >= result.active_count >= result.final_count
        assert result.final_count == len(result.stocks)

    def test_market_stats_structure(self):
        """验证 market_stats 包含正确的市场统计"""
        pipeline, activity_filter, heat_calc = self._make_pipeline_with_mocks()

        active = [
            _make_stock("HK.00700", "HK", 0),
            _make_stock("US.AAPL", "US", 0),
        ]
        activity_filter.filter_active_stocks.return_value = active
        heat_calc.calculate_realtime_heat_scores.return_value = {
            "HK.00700": {"heat_score": 80},
            "US.AAPL": {"heat_score": 90},
        }

        result = pipeline.execute(
            stocks=active, market_limits={"HK": 50, "US": 50}, activity_config={}
        )

        assert "HK" in result.market_stats
        assert "US" in result.market_stats
        for market, stats in result.market_stats.items():
            assert "active_count" in stats
            assert "heat_count" in stats
            assert "final_count" in stats
