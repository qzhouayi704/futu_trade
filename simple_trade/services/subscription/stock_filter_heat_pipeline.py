"""股票筛选-热度计算管道

将活跃度筛选和热度计算串联为统一的 Pipeline：
全部股票 → 活跃度筛选(不截断) → 热度计算 → 按热度排序 → 市场限制截断 → 订阅
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from simple_trade.services.analysis.heat.stock_heat_calculator import StockHeatCalculator
from simple_trade.services.market_data.activity_filter import ActivityFilterService

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """管道执行结果"""

    success: bool  # 是否执行成功
    stocks: List[Dict[str, Any]]  # 最终筛选后的股票列表
    total_count: int  # 输入总股票数
    active_count: int  # 活跃股票数
    heat_calculated_count: int  # 热度计算成功数
    final_count: int  # 最终订阅数
    market_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # 按市场统计
    errors: List[str] = field(default_factory=list)  # 错误信息


class StockFilterHeatPipeline:
    """股票筛选-热度计算管道协调器

    串联活跃度筛选 → 热度计算 → 热度排序截断，
    确保市场限制在热度排序之后再应用。
    """

    def __init__(
        self,
        activity_filter: ActivityFilterService,
        heat_calculator: StockHeatCalculator,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.activity_filter = activity_filter
        self.heat_calculator = heat_calculator
        self.config = config or {}

    def execute(
        self,
        stocks: List[Dict[str, Any]],
        market_limits: Dict[str, int],
        activity_config: Dict[str, Any],
        priority_stocks: Optional[List[str]] = None,
    ) -> PipelineResult:
        """执行完整的筛选管道

        流程：活跃度筛选 → 热度计算 → 按热度排序截断

        降级策略：
        - 活跃度筛选失败：跳过热度计算，直接按市场限制截断原始股票列表
        - 热度计算失败：使用 activity_score 替代 heat_score 进行排序截断
        """
        total_count = len(stocks)
        errors: List[str] = []
        heat_calculated_count = 0

        # === 阶段1：活跃度筛选（不截断） ===
        try:
            active_stocks = self.activity_filter.filter_active_stocks(
                stocks, activity_config, priority_stocks
            )
        except Exception as e:
            error_msg = f"活跃度筛选失败，降级为直接截断: {e}"
            logger.error(error_msg, exc_info=True)
            errors.append(error_msg)
            # 降级：跳过热度计算，直接按市场限制截断原始股票列表
            final_stocks = self._apply_market_limits_by_heat(
                stocks, market_limits, priority_stocks
            )
            market_stats = self._build_market_stats(
                stocks, [], final_stocks
            )
            logger.info(
                "Pipeline 执行完成(降级): 总计 %d → 最终 %d 只",
                total_count, len(final_stocks),
            )
            return PipelineResult(
                success=False,
                stocks=final_stocks,
                total_count=total_count,
                active_count=0,
                heat_calculated_count=0,
                final_count=len(final_stocks),
                market_stats=market_stats,
                errors=errors,
            )

        active_count = len(active_stocks)

        # === 阶段2：热度计算 ===
        try:
            heat_stocks = self._calculate_heat_for_active_stocks(active_stocks)
            heat_calculated_count = sum(
                1 for s in heat_stocks if s.get("heat_score", 0) > 0
            )
        except Exception as e:
            error_msg = f"热度计算失败，降级为 activity_score 排序: {e}"
            logger.error(error_msg, exc_info=True)
            errors.append(error_msg)
            # 降级：用 activity_score 替代 heat_score
            for stock in active_stocks:
                stock["heat_score"] = stock.get("activity_score", 0)
            heat_stocks = active_stocks

        # === 阶段3：按热度排序后应用市场限制截断 ===
        final_stocks = self._apply_market_limits_by_heat(
            heat_stocks, market_limits, priority_stocks
        )

        # === 构建统计信息 ===
        market_stats = self._build_market_stats(
            active_stocks, heat_stocks, final_stocks
        )

        logger.info(
            "Pipeline 执行完成: 总计 %d → 活跃 %d → 热度计算 %d → 最终 %d 只",
            total_count, active_count, heat_calculated_count, len(final_stocks),
        )

        return PipelineResult(
            success=len(errors) == 0,
            stocks=final_stocks,
            total_count=total_count,
            active_count=active_count,
            heat_calculated_count=heat_calculated_count,
            final_count=len(final_stocks),
            market_stats=market_stats,
            errors=errors,
        )


    def _build_market_stats(
        self,
        active_stocks: List[Dict[str, Any]],
        heat_stocks: List[Dict[str, Any]],
        final_stocks: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """按市场构建统计信息"""
        stats: Dict[str, Dict[str, Any]] = {}
        # 统计活跃数
        for s in active_stocks:
            m = s.get("market", "Unknown")
            stats.setdefault(m, {"active_count": 0, "heat_count": 0, "final_count": 0})
            stats[m]["active_count"] += 1
        # 统计热度计算成功数
        heat_codes = {s.get("code") for s in heat_stocks if s.get("heat_score", 0) > 0}
        for s in active_stocks:
            if s.get("code") in heat_codes and s.get("market", "Unknown") in stats:
                stats[s.get("market", "Unknown")]["heat_count"] += 1
        # 统计最终数
        for s in final_stocks:
            m = s.get("market", "Unknown")
            if m not in stats:
                stats[m] = {"active_count": 0, "heat_count": 0, "final_count": 0}
            stats[m]["final_count"] += 1
        return stats

    def _calculate_heat_for_active_stocks(
        self,
        active_stocks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """对活跃股票计算热度分数

        根据 heat_calculator.enhanced_enabled 选择增强模式或基础模式：
        - 增强模式：调用 calculate_enhanced_heat_scores()，使用 total_heat 作为 heat_score
        - 基础模式：调用 calculate_realtime_heat_scores()，使用 heat_score 字段
        无热度分数的股票设置 heat_score=0
        """
        if not active_stocks:
            return []

        # 提取活跃股票代码列表
        stock_codes = [stock["code"] for stock in active_stocks]

        try:
            if self.heat_calculator.enhanced_enabled:
                logger.info("使用增强模式计算 %d 只活跃股票的热度", len(stock_codes))
                heat_results = self.heat_calculator.calculate_enhanced_heat_scores(
                    stock_codes, use_cache=True
                )
                heat_key = "total_heat"
            else:
                logger.info("使用基础模式计算 %d 只活跃股票的热度", len(stock_codes))
                heat_results = self.heat_calculator.calculate_realtime_heat_scores(
                    stock_codes, use_cache=True
                )
                heat_key = "heat_score"

            # 统计热度计算结果
            success_count = len(heat_results)
            fail_count = len(stock_codes) - success_count
            logger.info(
                "热度计算完成: 成功 %d 只, 失败 %d 只 (共 %d 只)",
                success_count, fail_count, len(stock_codes),
            )

        except Exception as e:
            logger.error("热度计算异常: %s", e, exc_info=True)
            heat_results = {}
            heat_key = "heat_score"

        # 将 heat_score 附加到每只股票数据中
        for stock in active_stocks:
            code = stock["code"]
            heat_data = heat_results.get(code)
            if heat_data:
                stock["heat_score"] = heat_data.get(heat_key, 0)
            else:
                stock["heat_score"] = 0

        return active_stocks


    def _apply_market_limits_by_heat(
        self,
        stocks: List[Dict[str, Any]],
        market_limits: Dict[str, int],
        priority_stocks: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """按热度排序后应用市场限制截断

        - 按市场分组
        - 优先股票始终保留，不受截断影响
        - 非优先股票按 heat_score 从高到低排序
        - 按 market_limits 截断（默认每市场 50 只）
        - 记录每个市场截断前后的统计日志
        """
        if not stocks:
            return []

        default_limit = self.config.get("default_market_limit", 50)
        priority_codes = set(priority_stocks or [])

        # 按市场分组
        market_groups: Dict[str, List[Dict[str, Any]]] = {}
        for stock in stocks:
            market = stock.get("market", "Unknown")
            market_groups.setdefault(market, []).append(stock)

        result: List[Dict[str, Any]] = []

        for market, market_stocks in market_groups.items():
            limit = market_limits.get(market, default_limit)
            before_count = len(market_stocks)
            scores = [s.get("heat_score", 0) for s in market_stocks]
            before_min = min(scores) if scores else 0
            before_max = max(scores) if scores else 0

            # 分离优先股票和普通股票
            priority = []
            normal = []
            for s in market_stocks:
                if s.get("is_priority", False) or s.get("code", "") in priority_codes:
                    priority.append(s)
                else:
                    normal.append(s)

            # 普通股票按 heat_score 从高到低排序
            normal.sort(key=lambda s: s.get("heat_score", 0), reverse=True)

            # 截断：优先股票始终保留，剩余名额给普通股票
            remaining_slots = max(0, limit - len(priority))
            truncated_normal = normal[:remaining_slots]

            kept = priority + truncated_normal
            after_count = len(kept)
            after_scores = [s.get("heat_score", 0) for s in kept]
            after_min = min(after_scores) if after_scores else 0
            after_max = max(after_scores) if after_scores else 0

            logger.info(
                "市场 %s 截断: %d → %d 只 (优先 %d 只), "
                "热度范围: [%.1f, %.1f] → [%.1f, %.1f]",
                market,
                before_count,
                after_count,
                len(priority),
                before_min,
                before_max,
                after_min,
                after_max,
            )

            result.extend(kept)

        return result

