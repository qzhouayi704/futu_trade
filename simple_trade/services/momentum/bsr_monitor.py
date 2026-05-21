#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BSR 动量监控器

跟踪每只股票的BSR变化趋势，检测:
- 买方强势 / 卖方强势
- 动量衰竭（BSR从高位急跌）
- 动量爆发（BSR从低位急升）
"""

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .ticker_aggregator import AggregatedBar

logger = logging.getLogger(__name__)


class MomentumState(str, Enum):
    BULLISH = "BULLISH"          # 买方强势
    BEARISH = "BEARISH"          # 卖方强势
    NEUTRAL = "NEUTRAL"          # 均衡
    EXHAUSTION = "EXHAUSTION"    # 动量衰竭
    RECOVERY = "RECOVERY"        # 动量恢复


@dataclass
class MomentumSignal:
    """动量信号"""
    stock_code: str
    signal_type: str          # BUY_MOMENTUM / SELL_MOMENTUM / EXHAUSTION / RECOVERY
    state: MomentumState
    bsr: float
    bsr_trend: str            # "↑" / "↓" / "→"
    delta: int
    cum_delta: int
    vwap: float
    price: float
    description: str
    confidence: float         # 0.0~1.0
    timestamp: float


class BSRMonitor:
    """BSR动量监控器"""

    # 阈值配置
    BSR_BULLISH = 1.25         # BSR > 此值 = 买方强势
    BSR_BEARISH = 0.75         # BSR < 此值 = 卖方强势
    BSR_NEUTRAL_LOW = 0.9      # 中性区间下限
    BSR_NEUTRAL_HIGH = 1.1     # 中性区间上限

    # 衰竭检测：BSR从高位下降幅度
    EXHAUSTION_DROP = 0.35     # BSR下降超过此值触发衰竭
    # 连续确认bar数
    CONFIRM_BARS = 2           # 需要连续N个bar确认

    def __init__(self, history_size: int = 30):
        self._bsr_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._state: dict[str, MomentumState] = defaultdict(
            lambda: MomentumState.NEUTRAL
        )
        self._peak_bsr: dict[str, float] = defaultdict(lambda: 1.0)
        self._trough_bsr: dict[str, float] = defaultdict(lambda: 1.0)
        self._consecutive_bearish: dict[str, int] = defaultdict(int)
        self._consecutive_bullish: dict[str, int] = defaultdict(int)

    def reset_daily(self):
        """每日重置"""
        self._bsr_history.clear()
        self._state.clear()
        self._peak_bsr.clear()
        self._trough_bsr.clear()
        self._consecutive_bearish.clear()
        self._consecutive_bullish.clear()
        logger.info("[BSRMonitor] 每日重置完成")

    def update(self, bar: AggregatedBar) -> Optional[MomentumSignal]:
        """
        更新一个新bar的BSR，检测信号

        Returns:
            MomentumSignal 如果触发了信号，否则 None
        """
        code = bar.stock_code
        bsr = bar.bsr

        history = self._bsr_history[code]
        history.append(bsr)

        if len(history) < 3:
            return None

        prev_state = self._state[code]

        # 更新峰值/谷值
        if bsr > self._peak_bsr[code]:
            self._peak_bsr[code] = bsr
        if bsr < self._trough_bsr[code]:
            self._trough_bsr[code] = bsr

        # 连续计数
        if bsr < self.BSR_BEARISH:
            self._consecutive_bearish[code] += 1
            self._consecutive_bullish[code] = 0
        elif bsr > self.BSR_BULLISH:
            self._consecutive_bullish[code] += 1
            self._consecutive_bearish[code] = 0
        else:
            self._consecutive_bearish[code] = 0
            self._consecutive_bullish[code] = 0

        # BSR趋势
        recent = list(history)[-5:]
        if len(recent) >= 3:
            trend_val = recent[-1] - recent[0]
            bsr_trend = "↑" if trend_val > 0.1 else ("↓" if trend_val < -0.1 else "→")
        else:
            bsr_trend = "→"

        signal = None

        # ===== 信号检测 =====

        # 1. 动量衰竭：BSR从高位急跌
        peak = self._peak_bsr[code]
        if (prev_state in (MomentumState.BULLISH, MomentumState.NEUTRAL)
                and peak > self.BSR_BULLISH
                and bsr < peak - self.EXHAUSTION_DROP
                and bsr < self.BSR_NEUTRAL_LOW):
            self._state[code] = MomentumState.EXHAUSTION
            signal = MomentumSignal(
                stock_code=code,
                signal_type="EXHAUSTION",
                state=MomentumState.EXHAUSTION,
                bsr=bsr, bsr_trend="↓",
                delta=bar.delta, cum_delta=bar.cum_delta,
                vwap=bar.vwap, price=bar.close_price,
                description=f"动量衰竭: BSR从{peak:.2f}→{bsr:.2f}，买方撤退",
                confidence=min(1.0, (peak - bsr) / peak),
                timestamp=bar.timestamp,
            )

        # 2. 买方强势确认
        elif (self._consecutive_bullish[code] >= self.CONFIRM_BARS
              and prev_state != MomentumState.BULLISH):
            self._state[code] = MomentumState.BULLISH
            # 重置谷值
            self._trough_bsr[code] = bsr
            signal = MomentumSignal(
                stock_code=code,
                signal_type="BUY_MOMENTUM",
                state=MomentumState.BULLISH,
                bsr=bsr, bsr_trend="↑",
                delta=bar.delta, cum_delta=bar.cum_delta,
                vwap=bar.vwap, price=bar.close_price,
                description=f"买方强势: BSR={bsr:.2f}，连续{self._consecutive_bullish[code]}bar确认",
                confidence=min(1.0, (bsr - 1.0) / 0.5),
                timestamp=bar.timestamp,
            )

        # 3. 卖方碾压确认
        elif (self._consecutive_bearish[code] >= self.CONFIRM_BARS
              and prev_state != MomentumState.BEARISH):
            self._state[code] = MomentumState.BEARISH
            signal = MomentumSignal(
                stock_code=code,
                signal_type="SELL_MOMENTUM",
                state=MomentumState.BEARISH,
                bsr=bsr, bsr_trend="↓",
                delta=bar.delta, cum_delta=bar.cum_delta,
                vwap=bar.vwap, price=bar.close_price,
                description=f"卖方碾压: BSR={bsr:.2f}，连续{self._consecutive_bearish[code]}bar确认",
                confidence=min(1.0, (1.0 - bsr) / 0.5),
                timestamp=bar.timestamp,
            )

        # 4. 动量恢复：从衰竭/看空转为买入
        elif (prev_state in (MomentumState.EXHAUSTION, MomentumState.BEARISH)
              and bsr > self.BSR_BULLISH):
            trough = self._trough_bsr[code]
            self._state[code] = MomentumState.RECOVERY
            # 重置峰值
            self._peak_bsr[code] = bsr
            signal = MomentumSignal(
                stock_code=code,
                signal_type="RECOVERY",
                state=MomentumState.RECOVERY,
                bsr=bsr, bsr_trend="↑",
                delta=bar.delta, cum_delta=bar.cum_delta,
                vwap=bar.vwap, price=bar.close_price,
                description=f"动量恢复: BSR从{trough:.2f}→{bsr:.2f}，买方回归",
                confidence=min(1.0, (bsr - trough) / 0.5),
                timestamp=bar.timestamp,
            )

        # 状态维护：如果BSR回到中性且不是衰竭/恢复
        elif (self.BSR_NEUTRAL_LOW <= bsr <= self.BSR_NEUTRAL_HIGH
              and prev_state not in (MomentumState.EXHAUSTION, MomentumState.RECOVERY)):
            self._state[code] = MomentumState.NEUTRAL

        return signal

    def get_state(self, stock_code: str) -> dict:
        """获取某只股票的当前动量状态"""
        history = list(self._bsr_history.get(stock_code, []))
        return {
            "state": self._state.get(stock_code, MomentumState.NEUTRAL).value,
            "current_bsr": history[-1] if history else None,
            "peak_bsr": self._peak_bsr.get(stock_code, 1.0),
            "trough_bsr": self._trough_bsr.get(stock_code, 1.0),
            "history_len": len(history),
            "consecutive_bullish": self._consecutive_bullish.get(stock_code, 0),
            "consecutive_bearish": self._consecutive_bearish.get(stock_code, 0),
        }
