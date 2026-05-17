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
    liquidity_level: str = 'B'          # 流动性等级 A/B/C/D
    liquidity_score: float = 50.0       # 流动性评分 (0-100)
    stock_tag_label: str = '正常'       # 股票行为标签（控盘检测）


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

    # 极限值（安全边界）—— 按交易类型区分（B级默认值）
    min_stop_loss_pct: float = -8.0         # 短线最大止损不超过 -8%
    max_stop_loss_pct: float = -2.0         # 最小止损不低于 -2%
    min_target_profit_pct: float = 5.0      # 最低止盈目标
    max_target_profit_pct: float = 12.0     # 最高止盈目标

    # 日内交易安全边界（更严格）
    intraday_min_stop_loss_pct: float = -3.0   # 日内最大止损 3%
    intraday_max_stop_loss_pct: float = -1.0   # 日内最小止损 1%

    # 交易类型: "intraday" | "swing"
    trade_type: str = "swing"


# 流动性等级对应的安全边界调整
LIQUIDITY_BOUNDS = {
    'A': {  # 高流动性：滑点小，止损更紧，止盈更低
        'base_stop_loss_pct': -4.0,
        'base_target_profit_pct': 6.0,
        'min_stop_loss_pct': -6.0, 'max_stop_loss_pct': -2.0,
        'min_target_profit_pct': 4.0, 'max_target_profit_pct': 10.0,
    },
    'B': {  # 中等流动性：默认值
        'base_stop_loss_pct': -5.0,
        'base_target_profit_pct': 8.0,
        'min_stop_loss_pct': -8.0, 'max_stop_loss_pct': -2.0,
        'min_target_profit_pct': 5.0, 'max_target_profit_pct': 12.0,
    },
    'C': {  # 低流动性：波动大，止损更宽，止盈更高
        'base_stop_loss_pct': -7.0,
        'base_target_profit_pct': 10.0,
        'min_stop_loss_pct': -10.0, 'max_stop_loss_pct': -3.0,
        'min_target_profit_pct': 6.0, 'max_target_profit_pct': 15.0,
    },
    'D': {  # 极低流动性：等同C级
        'base_stop_loss_pct': -7.0,
        'base_target_profit_pct': 10.0,
        'min_stop_loss_pct': -10.0, 'max_stop_loss_pct': -3.0,
        'min_target_profit_pct': 6.0, 'max_target_profit_pct': 15.0,
    },
}


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
        quote_cache=None,
        config: DynamicStopLossConfig = None
    ):
        self.market_heat_monitor = market_heat_monitor
        self.capital_analyzer = capital_analyzer
        self.big_order_tracker = big_order_tracker
        self.realtime_query = realtime_query
        self.quote_cache = quote_cache
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
            f"均值{context.avg_turnover_rate:.2f}%, "
            f"流动性={context.liquidity_level}/{context.liquidity_score:.0f})"
        )

        return self._apply_adjustment(adjustment_factor, context.liquidity_level)

    def _calculate_adjustment_factor(self, context: MarketContext) -> float:
        """
        计算综合调整因子

        五个维度：热度 30% + 资金 25% + 大单 20% + 换手率 10% + 流动性 15%

        Returns:
            -1 ~ 1 的调整因子
        """
        # 1. 市场热度因子 (权重 30%)
        heat_factor = (context.market_heat - 50) / 50
        heat_factor = max(-1.0, min(1.0, heat_factor))

        # 2. 资金流向因子 (权重 25%)
        capital_factor = 0.0
        if context.capital_continuity and context.net_inflow_ratio > 0:
            capital_factor = min(context.net_inflow_ratio * 2, 1.0)
        elif context.net_inflow_ratio < -0.1:
            capital_factor = max(context.net_inflow_ratio * 2, -1.0)

        # 3. 大单强度因子 (权重 20%)
        big_order_factor = max(-1.0, min(1.0, context.big_order_strength))

        # 4. 换手率因子 (权重 10%)
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

        # 5. 流动性因子 (权重 15%)
        # A级高流动性 → 收紧止损(+0.4)，C级低流动性 → 放宽止损(-0.5)
        liquidity_factor = {
            'A': 0.4, 'B': 0.0, 'C': -0.5, 'D': -0.5,
        }.get(context.liquidity_level, 0.0)

        # 6. 股票标签因子 — 控盘/仙股收紧，正常不调整
        tag_factor = {
            '锁仓控盘': -0.6,   # 少量资金操控，收紧
            '暴量拉升': -0.4,   # 暴力拉升后可能砸盘，收紧
            '仙股炒作': -0.8,   # 极高风险，强收紧
            '明星高波动': 0.0,  # 正常高波动，不调整
            '正常': 0.0,
        }.get(context.stock_tag_label, 0.0)

        # 加权综合（新增标签因子 10%，其他权重微调）
        factor = (
            heat_factor * 0.25 +
            capital_factor * 0.25 +
            big_order_factor * 0.15 +
            turnover_factor * 0.10 +
            liquidity_factor * 0.15 +
            tag_factor * 0.10
        )

        return max(-1.0, min(1.0, factor))

    def _apply_adjustment(self, factor: float,
                          liquidity_level: str = 'B') -> RiskConfig:
        """
        将调整因子应用到风险配置

        factor > 0: 放宽（止损更宽，止盈更高）
        factor < 0: 收紧（止损更紧，止盈更低）

        安全边界根据流动性等级自适应：
        - A级：止损-2%~-6%，止盈4%~10%
        - B级：止损-2%~-8%，止盈5%~12%（默认）
        - C级：止损-3%~-10%，止盈6%~15%
        """
        cfg = self.config
        liq_bounds = LIQUIDITY_BOUNDS.get(liquidity_level, LIQUIDITY_BOUNDS['B'])

        # 根据流动性等级选择基础参数
        base_sl = liq_bounds['base_stop_loss_pct']
        base_tp = liq_bounds['base_target_profit_pct']

        # 根据交易类型选择安全边界
        if cfg.trade_type == "intraday":
            min_sl = cfg.intraday_min_stop_loss_pct
            max_sl = cfg.intraday_max_stop_loss_pct
        else:
            min_sl = liq_bounds['min_stop_loss_pct']
            max_sl = liq_bounds['max_stop_loss_pct']

        min_tp = liq_bounds['min_target_profit_pct']
        max_tp = liq_bounds['max_target_profit_pct']

        # 止损调整：factor > 0 → 止损更宽（更负），factor < 0 → 止损更紧（更接近0）
        stop_loss = base_sl - (factor * cfg.heat_adjust_range)
        stop_loss = max(min_sl, min(max_sl, stop_loss))

        # 止盈调整：factor > 0 → 止盈更高，factor < 0 → 止盈更低
        target_profit = base_tp + (factor * cfg.heat_adjust_range)
        target_profit = max(min_tp, min(max_tp, target_profit))

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
                quotes = self.quote_cache.get_cached_quotes() if self.quote_cache else None
                context.market_heat = self.market_heat_monitor.calculate_market_heat(quotes)
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
