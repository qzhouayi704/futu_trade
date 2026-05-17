#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金流向信号规则定义

每条规则实现为独立的 BaseFlowRule 子类：
- R1: 资金净流入大 + 低位建仓
- R2: 资金净流出 + 高位卖出
- R3: 资金流入不大 + 逢高卖出
- R4: 资金由负转正判断
- R5: 前日大升 + 次日平开
- R7: 均价线(VWAP)多空分水岭
- R10: 量价背离
- R11: 资金持续性
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional

from .flow_signal_models import FlowSignal, RuleContext

logger = logging.getLogger("capital_flow.rules")


class BaseFlowRule(ABC):
    """规则基类"""

    rule_id: str = ""
    rule_name: str = ""
    cooldown: int = 300  # 同一股票同一规则的冷却期(秒)

    def __init__(self):
        self._last_triggered: Dict[str, float] = {}  # {stock_code: timestamp}

    def check(self, ctx: RuleContext) -> Optional[FlowSignal]:
        """带冷却期的规则检查入口"""
        cache_key = ctx.stock_code
        now = time.time()
        last = self._last_triggered.get(cache_key, 0)
        if now - last < self.cooldown:
            return None
        signal = self.evaluate(ctx)
        if signal:
            self._last_triggered[cache_key] = now
            logger.info(
                f"[{self.rule_id}] {self.rule_name} 触发: "
                f"{ctx.stock_name}({ctx.stock_code}) {signal.signal_type} "
                f"@ {ctx.current_price:.3f} — {signal.reason}"
            )
        return signal

    @abstractmethod
    def evaluate(self, ctx: RuleContext) -> Optional[FlowSignal]:
        """评估规则，返回信号或 None"""

    def _make_signal(self, ctx: RuleContext, signal_type: str,
                     reason: str, suggestion: str,
                     confidence: float = 0.6,
                     priority: str = "medium") -> FlowSignal:
        """便捷创建信号"""
        return FlowSignal(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            stock_code=ctx.stock_code,
            stock_name=ctx.stock_name,
            signal_type=signal_type,
            price=ctx.current_price,
            reason=reason,
            confidence=confidence,
            priority=priority,
            action_suggestion=suggestion,
        )


# ============================================================
# R1: 资金净流入大，低点建仓
# ============================================================
class NetInflowBuyRule(BaseFlowRule):
    """R1: 主力资金净流入大 + 股价处于日内低位 → 建仓信号"""

    rule_id = "R1"
    rule_name = "资金净流入建仓"
    cooldown = 600  # 10分钟冷却

    # 可调阈值
    MIN_INFLOW_RATIO = 0.03    # 净流入占日均成交额 ≥ 3%
    MAX_CHANGE_PCT = -1.0      # 股价跌幅 > 1% 视为低位

    def evaluate(self, ctx: RuleContext) -> Optional[FlowSignal]:
        if not ctx.capital_flow or ctx.avg_daily_turnover <= 0:
            return None

        inflow_ratio = abs(ctx.main_net_inflow) / ctx.avg_daily_turnover
        is_net_inflow = ctx.main_net_inflow > 0

        if not is_net_inflow or inflow_ratio < self.MIN_INFLOW_RATIO:
            return None

        # 股价处于低位（跌幅 ≥ 1% 或接近日低）
        near_low = (ctx.low_price > 0 and
                    ctx.current_price <= ctx.low_price * 1.02)
        is_low = ctx.change_pct <= self.MAX_CHANGE_PCT or near_low

        if not is_low:
            return None

        return self._make_signal(
            ctx, "BUY",
            reason=(
                f"主力净流入{ctx.main_net_inflow/10000:.0f}万"
                f"(占日均{inflow_ratio*100:.1f}%)，"
                f"股价跌{ctx.change_pct:.1f}%处于低位"
            ),
            suggestion="分批建仓，散户获利出让中",
            confidence=min(0.5 + inflow_ratio * 5, 0.9),
            priority="high",
        )


# ============================================================
# R2: 资金净流出，逢高卖出
# ============================================================
class NetOutflowSellRule(BaseFlowRule):
    """R2: 主力资金净流出 + 股价高位 → 卖出信号"""

    rule_id = "R2"
    rule_name = "资金净流出卖出"
    cooldown = 600

    MIN_OUTFLOW_RATIO = 0.02   # 净流出占日均 ≥ 2%
    MIN_CHANGE_PCT = 3.0       # 涨幅 ≥ 3% 视为高位

    def evaluate(self, ctx: RuleContext) -> Optional[FlowSignal]:
        if not ctx.capital_flow or ctx.avg_daily_turnover <= 0:
            return None

        is_net_outflow = ctx.main_net_inflow < 0
        outflow_ratio = abs(ctx.main_net_inflow) / ctx.avg_daily_turnover

        if not is_net_outflow or outflow_ratio < self.MIN_OUTFLOW_RATIO:
            return None

        if ctx.change_pct < self.MIN_CHANGE_PCT:
            return None

        return self._make_signal(
            ctx, "SELL",
            reason=(
                f"主力净流出{abs(ctx.main_net_inflow)/10000:.0f}万"
                f"(占日均{outflow_ratio*100:.1f}%)，"
                f"股价涨{ctx.change_pct:.1f}%处于高位"
            ),
            suggestion="逢高减仓，主力拉高出货中",
            confidence=min(0.5 + outflow_ratio * 5, 0.9),
            priority="high",
        )


# ============================================================
# R3: 资金流入不大，逢高卖出
# ============================================================
class WeakInflowSellRule(BaseFlowRule):
    """R3: 净流入金额不大 + 股价上涨 → 上涨动力不足，逢高卖出"""

    rule_id = "R3"
    rule_name = "流入不足逢高卖"
    cooldown = 600

    MAX_INFLOW_RATIO = 0.03   # 净流入 < 日均3% = "不大"
    MIN_CHANGE_PCT = 2.0      # 涨幅 ≥ 2%

    def evaluate(self, ctx: RuleContext) -> Optional[FlowSignal]:
        if not ctx.capital_flow or ctx.avg_daily_turnover <= 0:
            return None

        is_net_inflow = ctx.main_net_inflow > 0
        inflow_ratio = abs(ctx.main_net_inflow) / ctx.avg_daily_turnover

        if not is_net_inflow:
            return None
        if inflow_ratio >= self.MAX_INFLOW_RATIO:
            return None  # 流入充足，不触发
        if ctx.change_pct < self.MIN_CHANGE_PCT:
            return None

        return self._make_signal(
            ctx, "SELL",
            reason=(
                f"净流入仅{ctx.main_net_inflow/10000:.0f}万"
                f"(占日均{inflow_ratio*100:.1f}%<3%)，"
                f"涨{ctx.change_pct:.1f}%但上涨动力不足"
            ),
            suggestion="逢高减仓，上涨动力不足",
            confidence=0.55,
            priority="medium",
        )


# ============================================================
# R4: 资金由负转正判断
# ============================================================
class FlowReversalRule(BaseFlowRule):
    """R4: 资金净流入由負转正 + 流入不大 → 次日高抛提示"""

    rule_id = "R4"
    rule_name = "资金转正高抛"
    cooldown = 1800  # 30分钟冷却（低频规则）

    MAX_INFLOW_RATIO = 0.03

    def evaluate(self, ctx: RuleContext) -> Optional[FlowSignal]:
        if not ctx.capital_flow or not ctx.capital_flow_history:
            return None
        if ctx.avg_daily_turnover <= 0:
            return None

        # 检查前日是否净流出
        prev_days = ctx.capital_flow_history
        if not prev_days:
            return None

        prev_net = prev_days[0].get('net_inflow', 0)
        if prev_net >= 0:
            return None  # 前日不是净流出，无"转正"

        # 今日净流入
        if ctx.main_net_inflow <= 0:
            return None  # 不是转正

        inflow_ratio = ctx.main_net_inflow / ctx.avg_daily_turnover

        if inflow_ratio >= self.MAX_INFLOW_RATIO:
            # 转正且流入充足 → 不触发卖出提示
            return None

        return self._make_signal(
            ctx, "ALERT",
            reason=(
                f"资金由负转正但流入不大"
                f"(仅{ctx.main_net_inflow/10000:.0f}万，"
                f"占日均{inflow_ratio*100:.1f}%)，"
                f"前日净流出{abs(prev_net)/10000:.0f}万"
            ),
            suggestion="次日开盘考虑高抛，转正力度不足",
            confidence=0.5,
            priority="medium",
        )


# ============================================================
# R5: 前日大升 + 次日平开
# ============================================================
class PrevDayRallyRule(BaseFlowRule):
    """R5: 前日涨幅>5% + 今日平开(变化<1%) → 可买入，有高抛位"""

    rule_id = "R5"
    rule_name = "大升后平开买入"
    cooldown = 3600  # 1小时冷却（一天最多触发几次）

    PREV_DAY_MIN_RISE = 5.0   # 前日涨幅 ≥ 5%
    MAX_OPEN_CHANGE = 1.0     # 今日开盘变化 < 1%

    def evaluate(self, ctx: RuleContext) -> Optional[FlowSignal]:
        if ctx.prev_day_change_pct is None:
            return None

        if ctx.prev_day_change_pct < self.PREV_DAY_MIN_RISE:
            return None

        # 检查今日是否平开
        if ctx.prev_close <= 0:
            return None
        open_change = abs((ctx.open_price - ctx.prev_close) / ctx.prev_close * 100)
        if open_change > self.MAX_OPEN_CHANGE:
            return None

        return self._make_signal(
            ctx, "BUY",
            reason=(
                f"前日大涨{ctx.prev_day_change_pct:.1f}%，"
                f"今日平开(开盘变化{open_change:.1f}%)，"
                f"获利盘抛压不大"
            ),
            suggestion="可轻仓买入，日内会有高抛位出手",
            confidence=0.6,
            priority="medium",
        )


# ============================================================
# R7: 均价线(VWAP)多空分水岭
# ============================================================
class VwapCrossRule(BaseFlowRule):
    """R7: 价格跌破VWAP且持续 → 弱势卖出信号"""

    rule_id = "R7"
    rule_name = "跌破均价线"
    cooldown = 900  # 15分钟冷却

    BREAK_MINUTES = 6  # 跌破VWAP持续 ≥ 6个周期(约30分钟，5秒/周期*6≈30s，但pipeline是60s检查一次)

    def evaluate(self, ctx: RuleContext) -> Optional[FlowSignal]:
        if ctx.vwap is None or ctx.vwap <= 0:
            return None

        price_below_vwap = ctx.current_price < ctx.vwap
        if not price_below_vwap:
            return None

        # 需要跌破持续一段时间
        if ctx.vwap_break_minutes < self.BREAK_MINUTES:
            return None

        deviation = (ctx.current_price - ctx.vwap) / ctx.vwap * 100

        return self._make_signal(
            ctx, "SELL",
            reason=(
                f"价格跌破均价线(VWAP={ctx.vwap:.3f})，"
                f"偏离{deviation:.2f}%，"
                f"持续{ctx.vwap_break_minutes}个周期未收回"
            ),
            suggestion="持仓减半或清仓，日内弱势",
            confidence=0.65,
            priority="high",
        )


# ============================================================
# R10: 量价背离
# ============================================================
class VolumePriceDivergenceRule(BaseFlowRule):
    """R10: 价格创日高但成交量萎缩 → 最可靠的离场信号"""

    rule_id = "R10"
    rule_name = "量价背离"
    cooldown = 900

    PRICE_NEAR_HIGH_PCT = 0.98  # 价格 ≥ 日高的98%
    VOLUME_SHRINK_RATIO = 0.7   # 当前量能 < 日均的70%

    def evaluate(self, ctx: RuleContext) -> Optional[FlowSignal]:
        if ctx.high_price <= 0 or ctx.avg_daily_turnover <= 0:
            return None

        # 价格接近日高
        near_high = ctx.current_price >= ctx.high_price * self.PRICE_NEAR_HIGH_PCT
        if not near_high:
            return None

        # 涨幅必须为正
        if ctx.change_pct < 1.0:
            return None

        # 成交量/额萎缩（用成交额比较）
        if ctx.turnover <= 0:
            return None

        # 简化判断：当日成交额 < 日均的70%
        volume_ratio = ctx.turnover / ctx.avg_daily_turnover
        if volume_ratio >= self.VOLUME_SHRINK_RATIO:
            return None  # 量能未萎缩

        return self._make_signal(
            ctx, "SELL",
            reason=(
                f"价格接近日高({ctx.current_price:.3f}≈{ctx.high_price:.3f})，"
                f"但成交额仅为日均{volume_ratio*100:.0f}%，量价背离"
            ),
            suggestion="最可靠的阶段性顶部信号，即时减仓",
            confidence=0.75,
            priority="high",
        )


# ============================================================
# R11: 资金持续性
# ============================================================
class FlowContinuityRule(BaseFlowRule):
    """R11: 连续3日以上资金净流入 → 趋势性吸筹，中线持有信号

    增强：结合K线位置调整优先级和置信度
    - 低位(≤0.3): priority=high, confidence+0.1
    - 高位(≥0.8): confidence-0.1, 提示追高风险
    """

    rule_id = "R11"
    rule_name = "资金持续流入"
    cooldown = 3600  # 1小时（低频提示）

    MIN_CONTINUOUS_DAYS = 3

    def evaluate(self, ctx: RuleContext) -> Optional[FlowSignal]:
        if not ctx.capital_flow_history:
            return None

        # 统计连续净流入天数
        consecutive = 0
        for day in ctx.capital_flow_history:
            net = day.get('net_inflow', 0)
            if net > 0:
                consecutive += 1
            else:
                break

        if consecutive < self.MIN_CONTINUOUS_DAYS:
            return None

        # 今日也需要是净流入
        if ctx.main_net_inflow <= 0:
            return None

        total_inflow = sum(
            d.get('net_inflow', 0) for d in ctx.capital_flow_history[:consecutive]
        )

        # 基础置信度和优先级
        confidence = min(0.5 + consecutive * 0.1, 0.85)
        priority = "medium"
        suggestion = "可中线持有，资金持续性比绝对值更重要"

        # 结合K线位置调整
        position_note = ""
        if ctx.kline_position is not None:
            if ctx.kline_position <= 0.3:
                # 低位吸筹 → 提升信号
                confidence = min(confidence + 0.1, 0.9)
                priority = "high"
                suggestion = "低位持续吸筹，可中线建仓"
                position_note = f"，K线低位({ctx.kline_position:.0%})"
            elif ctx.kline_position >= 0.8:
                # 高位持续流入 → 降低置信度，警示追高
                confidence = max(confidence - 0.1, 0.4)
                suggestion = "高位资金流入，注意追高风险"
                position_note = f"，K线高位({ctx.kline_position:.0%})"

        return self._make_signal(
            ctx, "BUY",
            reason=(
                f"连续{consecutive}日资金净流入，"
                f"累计流入{total_inflow/10000:.0f}万，"
                f"趋势性吸筹特征明显{position_note}"
            ),
            suggestion=suggestion,
            confidence=confidence,
            priority=priority,
        )


# ============================================================
# R12: 资金趋势共振（联合规则）
# ============================================================
class FlowTrendReversalRule(BaseFlowRule):
    """R12: 连续资金流入 + K线低位 + 阳线反转 → 高置信买入信号

    三个条件同时满足才触发：
    1. 连续≥2日资金净流入
    2. K线处于低位（kline_position ≤ 0.4）
    3. 今日阳线（当前价 > 开盘价）
    """

    rule_id = "R12"
    rule_name = "资金趋势共振"
    cooldown = 1800  # 30分钟冷却（低频高置信规则）

    MIN_CONTINUOUS_DAYS = 2
    MAX_KLINE_POSITION = 0.4

    def evaluate(self, ctx: RuleContext) -> Optional[FlowSignal]:
        # 条件1: 连续≥2日资金净流入
        if not ctx.capital_flow_history:
            return None

        consecutive = 0
        for day in ctx.capital_flow_history:
            net = day.get('net_inflow', 0)
            if net > 0:
                consecutive += 1
            else:
                break

        if consecutive < self.MIN_CONTINUOUS_DAYS:
            return None

        # 今日也需要是净流入
        if ctx.main_net_inflow <= 0:
            return None

        # 条件2: K线处于低位
        if ctx.kline_position is None or ctx.kline_position > self.MAX_KLINE_POSITION:
            return None

        # 条件3: 今日阳线（当前价 > 开盘价）
        if ctx.open_price <= 0 or ctx.current_price <= ctx.open_price:
            return None

        total_inflow = sum(
            d.get('net_inflow', 0) for d in ctx.capital_flow_history[:consecutive]
        )

        # 置信度: 基础0.75，连续天数越多越高
        confidence = min(0.75 + (consecutive - 2) * 0.05, 0.9)

        return self._make_signal(
            ctx, "BUY",
            reason=(
                f"连续{consecutive}日资金净流入"
                f"(累计{total_inflow/10000:.0f}万)，"
                f"K线处于低位(20日位置{ctx.kline_position:.0%})，"
                f"今日阳线反转确认"
            ),
            suggestion="资金持续建仓+底部反转确认，可分批建仓",
            confidence=confidence,
            priority="high",
        )


# ============================================================
# 规则注册表
# ============================================================
ALL_RULES = [
    NetInflowBuyRule,
    NetOutflowSellRule,
    WeakInflowSellRule,
    FlowReversalRule,
    PrevDayRallyRule,
    VwapCrossRule,
    VolumePriceDivergenceRule,
    FlowContinuityRule,
    FlowTrendReversalRule,
]
