#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态止损策略

根据市场热度、资金流向持续性和大单强度，动态调整止盈止损参数。
核心思路：
- 市场热度高 + 资金持续流入 → 放宽止损，让利润奔跑
- 市场热度低 + 资金流出 → 收紧止损，快速保护本金
"""

import logging
from dataclasses import dataclass
from typing import Optional

from ....core.validation.risk_checker import RiskConfig


@dataclass
class MarketContext:
    """市场环境上下文"""
    market_heat: float = 50.0           # 市场热度 (0-100)
    capital_continuity: bool = False     # 资金是否持续流入
    net_inflow_ratio: float = 0.0       # 主力净流入占比 (-1 ~ 1)
    big_order_strength: float = 0.0     # 大单强度 (-1 ~ 1)
    plate_strength: float = 50.0        # 板块强势度 (0-100)
    turnover_rate: float = 0.0          # 当日换手率 (%)
    avg_turnover_rate: float = 0.0      # 近 5 日平均换手率 (%)


@dataclass
class DynamicStopLossConfig:
    """动态止损配置"""
    # 基础参数（默认值，会被动态调整）
    base_stop_loss_pct: float = -5.0        # 基础止损 (%)
    base_target_profit_pct: float = 8.0     # 基础止盈 (%)
    base_trailing_trigger_pct: float = 6.0  # 基础移动止盈触发 (%)
    base_trailing_callback_pct: float = 2.0 # 基础移动止盈回撤 (%)

    # 调整幅度
    heat_adjust_range: float = 2.0          # 热度调整幅度 (%)
    capital_adjust_range: float = 1.5       # 资金调整幅度 (%)
    big_order_adjust_range: float = 1.0     # 大单调整幅度 (%)

    # 极限值（安全边界）—— 按交易类型区分
    min_stop_loss_pct: float = -8.0         # 短线最大止损不超过 -8%
    max_stop_loss_pct: float = -2.0         # 最小止损不低于 -2%
    min_target_profit_pct: float = 5.0      # 最低止盈目标
    max_target_profit_pct: float = 12.0     # 最高止盈目标

    # 日内交易安全边界（更严格）
    intraday_min_stop_loss_pct: float = -3.0   # 日内最大止损 3%
    intraday_max_stop_loss_pct: float = -1.0   # 日内最小止损 1%

    # 交易类型: "intraday" | "swing"
    trade_type: str = "swing"


class DynamicStopLossStrategy:
    """
    动态止损策略

    根据三个维度动态调整止盈止损参数：
    1. 市场热度（权重 40%）：热度高放宽，热度低收紧
    2. 资金流向（权重 35%）：资金流入放宽，资金流出收紧
    3. 大单强度（权重 25%）：大单买入放宽，大单卖出收紧
    """

    def __init__(
        self,
        market_heat_monitor=None,
        capital_analyzer=None,
        big_order_tracker=None,
        realtime_query=None,
        config: DynamicStopLossConfig = None
    ):
        self.market_heat_monitor = market_heat_monitor
        self.capital_analyzer = capital_analyzer
        self.big_order_tracker = big_order_tracker
        self.realtime_query = realtime_query
        self.config = config or DynamicStopLossConfig()
        self.logger = logging.getLogger(__name__)

    def calculate_dynamic_risk_config(
        self,
        stock_code: str,
        context: MarketContext = None
    ) -> RiskConfig:
        """
        计算动态风险配置

        Args:
            stock_code: 股票代码
            context: 市场环境上下文（如果为None则自动获取）

        Returns:
            动态调整后的 RiskConfig
        """
        if context is None:
            context = self._build_market_context(stock_code)

        # 计算调整因子 (-1 ~ 1)，正值=放宽，负值=收紧
        adjustment_factor = self._calculate_adjustment_factor(context)

        self.logger.debug(
            f"{stock_code} 动态止损调整因子: {adjustment_factor:.3f} "
            f"(热度={context.market_heat:.1f}, "
            f"资金={context.net_inflow_ratio:.3f}, "
            f"大单={context.big_order_strength:.3f}, "
            f"换手率={context.turnover_rate:.2f}%/"
            f"均值{context.avg_turnover_rate:.2f}%)"
        )

        return self._apply_adjustment(adjustment_factor)

    def _calculate_adjustment_factor(self, context: MarketContext) -> float:
        """
        计算综合调整因子

        四个维度：热度 35% + 资金 30% + 大单 20% + 换手率 15%

        Returns:
            -1 ~ 1 的调整因子
        """
        # 1. 市场热度因子 (权重 35%)
        heat_factor = (context.market_heat - 50) / 50
        heat_factor = max(-1.0, min(1.0, heat_factor))

        # 2. 资金流向因子 (权重 30%)
        capital_factor = 0.0
        if context.capital_continuity and context.net_inflow_ratio > 0:
            capital_factor = min(context.net_inflow_ratio * 2, 1.0)
        elif context.net_inflow_ratio < -0.1:
            capital_factor = max(context.net_inflow_ratio * 2, -1.0)

        # 3. 大单强度因子 (权重 20%)
        big_order_factor = max(-1.0, min(1.0, context.big_order_strength))

        # 4. 换手率因子 (权重 15%)
        # 高换手率 + 下跌 → 收紧（出货信号）
        # 低换手率 + 下跌 → 放宽（洗盘信号）
        turnover_factor = 0.0
        if context.avg_turnover_rate > 0:
            relative_turnover = context.turnover_rate / context.avg_turnover_rate
            if relative_turnover > 2.0:
                turnover_factor = -0.5   # 异常高换手，收紧
            elif relative_turnover > 1.5:
                turnover_factor = -0.3
            elif relative_turnover < 0.3:
                turnover_factor = 0.5    # 极度缩量，可能洗盘，放宽
            elif relative_turnover < 0.5:
                turnover_factor = 0.3

        # 加权综合
        factor = (
            heat_factor * 0.35 +
            capital_factor * 0.30 +
            big_order_factor * 0.20 +
            turnover_factor * 0.15
        )

        return max(-1.0, min(1.0, factor))

    def _apply_adjustment(self, factor: float) -> RiskConfig:
        """
        将调整因子应用到风险配置

        factor > 0: 放宽（止损更宽，止盈更高）
        factor < 0: 收紧（止损更紧，止盈更低）
        """
        cfg = self.config

        # 根据交易类型选择安全边界
        if cfg.trade_type == "intraday":
            min_sl = cfg.intraday_min_stop_loss_pct
            max_sl = cfg.intraday_max_stop_loss_pct
        else:
            min_sl = cfg.min_stop_loss_pct
            max_sl = cfg.max_stop_loss_pct

        # 止损调整：factor > 0 → 止损更宽（更负），factor < 0 → 止损更紧（更接近0）
        stop_loss = cfg.base_stop_loss_pct - (factor * cfg.heat_adjust_range)
        stop_loss = max(min_sl, min(max_sl, stop_loss))

        # 止盈调整：factor > 0 → 止盈更高，factor < 0 → 止盈更低
        target_profit = cfg.base_target_profit_pct + (factor * cfg.heat_adjust_range)
        target_profit = max(cfg.min_target_profit_pct, min(cfg.max_target_profit_pct, target_profit))

        # 移动止盈触发调整
        trailing_trigger = cfg.base_trailing_trigger_pct + (factor * cfg.capital_adjust_range)
        trailing_trigger = max(4.0, min(10.0, trailing_trigger))

        # 移动止盈回撤调整：factor > 0 → 回撤容忍更大
        trailing_callback = cfg.base_trailing_callback_pct + (factor * cfg.big_order_adjust_range * 0.5)
        trailing_callback = max(1.0, min(4.0, trailing_callback))

        return RiskConfig(
            target_profit_pct=round(target_profit, 2),
            trailing_trigger_pct=round(trailing_trigger, 2),
            trailing_callback_pct=round(trailing_callback, 2),
            fixed_stop_loss_pct=round(stop_loss, 2),
            quick_stop_loss_pct=round(stop_loss + 2.0, 2),
            plate_rank_threshold=5,
            max_holding_days=1,
            min_profit_after_days=2.0
        )

    def _build_market_context(self, stock_code: str) -> MarketContext:
        """
        自动构建市场环境上下文

        Args:
            stock_code: 股票代码

        Returns:
            MarketContext
        """
        context = MarketContext()

        # 获取市场热度
        if self.market_heat_monitor:
            try:
                context.market_heat = self.market_heat_monitor.calculate_market_heat()
            except Exception as e:
                self.logger.warning(f"获取市场热度失败: {e}")

        # 获取资金流向
        if self.capital_analyzer:
            try:
                capital_data = self.capital_analyzer.fetch_capital_flow_data(
                    [stock_code], use_cache=True
                )
                if stock_code in capital_data:
                    data = capital_data[stock_code]
                    context.net_inflow_ratio = data.get('net_inflow_ratio', 0)
                    context.capital_continuity = self.capital_analyzer.detect_capital_continuity(
                        stock_code, periods=2
                    )
            except Exception as e:
                self.logger.warning(f"获取资金流向失败: {e}")

        # 获取大单强度
        if self.big_order_tracker:
            try:
                big_order_data = self.big_order_tracker.track_rt_tickers(
                    [stock_code], top_n=1
                )
                if stock_code in big_order_data:
                    context.big_order_strength = big_order_data[stock_code].get(
                        'order_strength', 0
                    )
            except Exception as e:
                self.logger.warning(f"获取大单数据失败: {e}")

        # 获取换手率（从 realtime_query 的报价数据中获取）
        if self.realtime_query:
            try:
                result = self.realtime_query.get_realtime_quotes([stock_code])
                if result.get('success') and result.get('quotes'):
                    quote = result['quotes'][0]
                    context.turnover_rate = quote.get('turnover_rate', 0.0)
            except Exception as e:
                self.logger.warning(f"获取换手率失败: {e}")

        return context
