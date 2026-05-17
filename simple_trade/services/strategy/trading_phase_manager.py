#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日内交易阶段管理器

基于回测数据：
- 第一阶段(9:30-9:40) 胜率67%，最佳窗口 → 抢先手
- 第二阶段(9:40-10:00) 胜率29%，陷阱区 → 只卖不买
- 第三阶段(10:00+) 胜率逐降 → 资金流驱动换票

职责：
- 判断当前阶段和允许的操作
- 协调 StockScorer 和 TradeFrequencyGuard
- 输出阶段性操作建议
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class TradingPhase(Enum):
    """交易阶段"""
    PRE_MARKET = "pre_market"          # 盘前
    PHASE1_OPENING = "phase1_opening"  # 9:30-9:40 开盘抢先手
    PHASE2_OBSERVE = "phase2_observe"  # 9:40-10:00 观察期
    PHASE3_ROTATION = "phase3_rotate"  # 10:00+ 资金流换票
    LUNCH_BREAK = "lunch_break"        # 午休
    AFTER_HOURS = "after_hours"        # 收盘后


@dataclass
class PhaseAction:
    """阶段操作指令"""
    phase: TradingPhase
    can_buy: bool
    can_sell: bool
    buy_strategy: str     # 买入策略描述
    sell_strategy: str    # 卖出策略描述
    note: str = ""


# ── 各阶段操作规则 ──────────────────────────────────────

PHASE_RULES: Dict[TradingPhase, PhaseAction] = {
    TradingPhase.PRE_MARKET: PhaseAction(
        phase=TradingPhase.PRE_MARKET,
        can_buy=False, can_sell=False,
        buy_strategy="盘前不交易，运行评分选股",
        sell_strategy="盘前不交易",
    ),
    TradingPhase.PHASE1_OPENING: PhaseAction(
        phase=TradingPhase.PHASE1_OPENING,
        can_buy=True, can_sell=True,
        buy_strategy="评分≥60的标的，低吸不追高（日内位置≤40%），5min阳线确认",
        sell_strategy="正常止盈止损",
        note="黄金窗口，胜率67%",
    ),
    TradingPhase.PHASE2_OBSERVE: PhaseAction(
        phase=TradingPhase.PHASE2_OBSERVE,
        can_buy=False, can_sell=True,
        buy_strategy="原则禁买（评分≥80+回调≥5%+放量止跌除外，仓位减半）",
        sell_strategy="正常止盈止损",
        note="危险时段，胜率29%",
    ),
    TradingPhase.PHASE3_ROTATION: PhaseAction(
        phase=TradingPhase.PHASE3_ROTATION,
        can_buy=True, can_sell=True,
        buy_strategy="资金流驱动换票：卖弱买强，评分≥50+当日资金流入前3+价格<日内均价",
        sell_strategy="弱势持仓清理（资金流出/3根阴线/跌破ATR）",
        note="换票阶段，最多换2次，间隔≥15分钟",
    ),
    TradingPhase.LUNCH_BREAK: PhaseAction(
        phase=TradingPhase.LUNCH_BREAK,
        can_buy=False, can_sell=False,
        buy_strategy="午休不交易",
        sell_strategy="午休不交易",
    ),
    TradingPhase.AFTER_HOURS: PhaseAction(
        phase=TradingPhase.AFTER_HOURS,
        can_buy=False, can_sell=False,
        buy_strategy="收盘后不交易",
        sell_strategy="收盘后不交易",
    ),
}


class TradingPhaseManager:
    """
    日内交易阶段管理器

    使用方式：
    1. 调用 get_current_phase() 获取当前阶段
    2. 调用 get_action() 获取当前阶段允许的操作
    3. 调用 should_buy() 判断当前是否应该买入
    """

    def __init__(self):
        self._rotation_count: int = 0  # 今日换票次数
        self._max_rotations: int = 2
        self._date: str = ""

    def get_current_phase(self, current_time: Optional[datetime] = None) -> TradingPhase:
        """获取当前交易阶段"""
        now = current_time or datetime.now()
        t = now.strftime('%H:%M')

        if t < '09:30':
            return TradingPhase.PRE_MARKET
        elif t < '09:40':
            return TradingPhase.PHASE1_OPENING
        elif t < '10:00':
            return TradingPhase.PHASE2_OBSERVE
        elif t < '12:00':
            return TradingPhase.PHASE3_ROTATION
        elif t < '13:00':
            return TradingPhase.LUNCH_BREAK
        elif t < '16:00':
            return TradingPhase.PHASE3_ROTATION
        else:
            return TradingPhase.AFTER_HOURS

    def get_action(self, current_time: Optional[datetime] = None) -> PhaseAction:
        """获取当前阶段的操作规则"""
        phase = self.get_current_phase(current_time)
        return PHASE_RULES[phase]

    def should_buy(self, stock_score: int, current_time: Optional[datetime] = None,
                   is_rotation: bool = False) -> tuple[bool, str]:
        """
        判断当前是否应该买入

        Args:
            stock_score: 标的评分
            is_rotation: 是否为换票操作（第三阶段）
        """
        phase = self.get_current_phase(current_time)
        action = PHASE_RULES[phase]

        if not action.can_buy:
            # 第二阶段例外：评分≥80���买入
            if phase == TradingPhase.PHASE2_OBSERVE and stock_score >= 80:
                return True, "观察期例外（评分≥80），仓位需减半"
            return False, f"当前阶段{phase.value}禁止买入"

        if phase == TradingPhase.PHASE1_OPENING:
            if stock_score < 60:
                return False, f"开盘阶段需评分≥60(当前{stock_score})"
            return True, "开盘阶段买入"

        if phase == TradingPhase.PHASE3_ROTATION:
            if is_rotation:
                if self._rotation_count >= self._max_rotations:
                    return False, f"今日换票已达上限{self._max_rotations}次"
                if stock_score < 50:
                    return False, f"换票需评分≥50(当前{stock_score})"
                return True, "换票买入"
            else:
                if stock_score < 60:
                    return False, f"非换票买入需评分≥60(当前{stock_score})"
                return True, "第三阶段买入"

        return True, "允许买入"

    def record_rotation(self):
        """记录一次换票"""
        self._rotation_count += 1
        logger.info(f"[PhaseManager] 换票次数: {self._rotation_count}/{self._max_rotations}")

    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        phase = self.get_current_phase()
        action = PHASE_RULES[phase]
        return {
            'phase': phase.value,
            'can_buy': action.can_buy,
            'can_sell': action.can_sell,
            'buy_strategy': action.buy_strategy,
            'note': action.note,
            'rotation_count': self._rotation_count,
            'max_rotations': self._max_rotations,
        }

    def reset_daily(self):
        """每日开盘前重置"""
        self._rotation_count = 0
        self._date = datetime.now().strftime('%Y-%m-%d')
        logger.info("[PhaseManager] 日度数据已重置")
