#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主力资金趋势检测器（CapitalTrendDetector）

把逐笔累加器(TickCapitalAccumulator)的实时快照，转成**辅助人工判断的信息型提醒**
(不自动交易)，展示于前端信号流(置 V1 之前)、可点开净额曲线图；强信号经治理器推企微。

两类提醒（用户原话）：
- **上升趋势中**：累计资金流入多少 / 力度多少 / 日内涨幅多少 / 第几次大单买入
- **回落中**：自峰值回落多少 / 力度多少 / 日内涨幅多少 / 第几次大单流出

口径(用户已拍板)：
- **大单门槛按每股自适应**(MINIMAX≈300万、翼菲≈15万)——由 CapitalThresholdCalibrator 标定，
  累加器据此分级，这里只读 snapshot 的累计/计数/峰谷。
- **力度 = 相对自身倍数**：strength_mult = |当前15min窗口主力净流入| ÷ 该股力度基准
  (window_net_scale)，表达"这波是平时的 X 倍"；分 强(≥2.0)/中(≥1.0)/弱。

设计取舍(与 push_governor/累加器一致)：
- 纯逻辑、无 I/O、注入时钟 → 便于单测；运行在单事件循环里串行调用(不丢线程池)，用普通 dict 无锁。
- master flag(`enabled`) 默认 False：evaluate 直接返回 None，零开销可逆。
- 防刷屏：每股每方向冷却 + 仅"档位升级/计数前进/回落加深"打破冷却 + 每日每股硬上限 + 跨日复位。

置 `CAPITAL_TREND_ALERT_ENABLED` 环境变量为 1/true 才启用。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, Optional, Tuple

_TIER_LABEL = {2: "强", 1: "中", 0: "弱"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class CapitalTrendConfig:
    enabled: bool = False
    strong_mult: float = 2.0       # 力度倍数 ≥ 此值 = 强
    mid_mult: float = 1.0          # ≥ 此值 = 中（触发下限）
    cooldown_sec: int = 300        # 同股同方向冷却（升档/计数前进可打破）
    pullback_pct: float = 0.15     # 回落判定：自峰值回落 ≥ peak×此比例（或 ≥ 一个大单门槛）
    max_rising_per_day: int = 6    # 每股每日上升提醒硬上限
    max_falling_per_day: int = 4   # 每股每日回落提醒硬上限

    @classmethod
    def from_env(cls) -> "CapitalTrendConfig":
        raw = os.environ.get("CAPITAL_TREND_ALERT_ENABLED", "")
        enabled = str(raw).strip().lower() in ("1", "true", "yes", "on")
        cfg = cls(enabled=enabled)
        cfg.strong_mult = _env_float("CAPITAL_TREND_STRONG_MULT", cfg.strong_mult)
        cfg.mid_mult = _env_float("CAPITAL_TREND_MID_MULT", cfg.mid_mult)
        cfg.cooldown_sec = _env_int("CAPITAL_TREND_COOLDOWN_SEC", cfg.cooldown_sec)
        cfg.pullback_pct = _env_float("CAPITAL_TREND_PULLBACK_PCT", cfg.pullback_pct)
        cfg.max_rising_per_day = _env_int("CAPITAL_TREND_MAX_RISING", cfg.max_rising_per_day)
        cfg.max_falling_per_day = _env_int("CAPITAL_TREND_MAX_FALLING", cfg.max_falling_per_day)
        return cfg


@dataclass
class CapitalTrendAlert:
    stock_code: str
    stock_name: str
    trade_date: str
    timestamp: float
    direction: str               # "RISING" | "FALLING"
    strength_tier: str           # "强" | "中" | "弱"
    strength_mult: float         # 力度倍数（相对自身）
    cum_main_net: float          # 当日累计主力净流入（元）
    window_main_net: float       # 当前 15min 窗口主力净流入（元）
    pullback_amount: float       # 自峰值回落额（元，FALLING 用；RISING=0）
    intraday_change_pct: float   # 日内涨幅 %
    big_buy_count: int           # 当日第几次大单买入
    big_sell_count: int          # 当日第几次大单流出
    big_order_threshold: float   # 该股大单门槛（元）
    last_price: float
    reason: str
    is_strong_push: bool         # 是否路由企微（强信号/回落）

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _TrendState:
    day: str
    rising_count: int = 0
    falling_count: int = 0
    last_rising_ts: Optional[float] = None
    last_rising_tier: int = -1
    last_rising_buy_count: int = 0
    last_falling_ts: Optional[float] = None
    last_falling_tier: int = -1
    last_pullback: float = 0.0


class CapitalTrendDetector:
    """主力资金趋势检测器。线程假设：单事件循环串行调用（与 push_governor 同）。"""

    def __init__(
        self,
        config: Optional[CapitalTrendConfig] = None,
        clock: Callable[[], float] = time.time,
    ):
        self.cfg = config or CapitalTrendConfig()
        self._clock = clock
        self._state: Dict[str, _TrendState] = {}

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

    def _tier(self, mult: float) -> int:
        if mult >= self.cfg.strong_mult:
            return 2
        if mult >= self.cfg.mid_mult:
            return 1
        return 0

    def evaluate(
        self,
        snapshot: dict,
        last_price: Optional[float],
        prev_close: Optional[float],
        tiers: Tuple[float, float, float],
        stock_name: Optional[str] = None,
        now: Optional[float] = None,
    ) -> Optional[CapitalTrendAlert]:
        """对一只股票的当前快照判断是否产出一条趋势提醒；不产出返回 None。

        tiers = (大单门槛, 超大单门槛, 力度基准 window_net_scale)。
        """
        if not self.cfg.enabled or not snapshot:
            return None
        now = self._clock() if now is None else now
        code = snapshot.get("stock_code")
        day = snapshot.get("trade_date")
        if not code or not day:
            return None

        st = self._state.get(code)
        if st is None or st.day != day:      # 跨日/首见 → 复位该股状态
            st = _TrendState(day=day)
            self._state[code] = st

        large_thr = float(tiers[0]) if tiers and tiers[0] else 0.0
        scale = float(tiers[2]) if tiers and len(tiers) > 2 and tiers[2] else large_thr
        if scale <= 0:
            return None

        cum = float(snapshot.get("cum_main_net") or 0.0)
        peak = float(snapshot.get("cum_peak") or 0.0)
        window_net = float(snapshot.get("window_main_net") or 0.0)
        big_buy_count = int(snapshot.get("big_buy_count") or 0)
        big_sell_count = int(snapshot.get("big_sell_count") or 0)
        strength_mult = abs(window_net) / scale
        tier = self._tier(strength_mult)
        chg = 0.0
        if last_price and prev_close and prev_close > 0:
            chg = (float(last_price) - float(prev_close)) / float(prev_close) * 100.0
        name = stock_name or code
        lp = float(last_price or 0.0)

        # ── 回落 / 拉高出货（优先判断；两类都属 FALLING，一律推企微）──
        #   ① retreat：主力资金从当日净流入峰值回落（先涨后撤）。
        #   ② distribution：无净流入峰值，但**股价在涨而主力大单净流出**——典型"拉高出货"
        #      (治用户 06-24 痛点：日内拉高、最终净流出，该在拉高时及时卖)。
        pullback = peak - cum
        had_peak = peak >= large_thr
        retreat = had_peak and pullback >= max(large_thr, peak * self.cfg.pullback_pct)
        distribution = (not had_peak) and chg > 0 and cum <= -large_thr
        if window_net < 0 and tier >= 1 and (retreat or distribution):
            if (st.falling_count < self.cfg.max_falling_per_day
                    and self._falling_rearm(st, now, tier, pullback, large_thr)):
                st.falling_count += 1
                st.last_falling_ts = now
                st.last_falling_tier = tier
                st.last_pullback = pullback
                tier_label = _TIER_LABEL[tier]
                if retreat:
                    reason = ("主力资金回落·%s｜自峰值回落%.0f万 力度%.1f× 日内%+.2f%% 第%d次大单流出"
                              % (tier_label, pullback / 1e4, strength_mult, chg, big_sell_count))
                else:
                    reason = ("主力净流出·%s｜净流出%.0f万 股价逆势%+.2f%%(疑似拉高出货) 力度%.1f× 第%d次大单流出"
                              % (tier_label, (-cum) / 1e4, chg, strength_mult, big_sell_count))
                return CapitalTrendAlert(
                    stock_code=code, stock_name=name, trade_date=day, timestamp=now,
                    direction="FALLING", strength_tier=tier_label, strength_mult=round(strength_mult, 2),
                    cum_main_net=round(cum, 2), window_main_net=round(window_net, 2),
                    pullback_amount=round(pullback, 2), intraday_change_pct=round(chg, 2),
                    big_buy_count=big_buy_count, big_sell_count=big_sell_count,
                    big_order_threshold=round(large_thr, 2), last_price=lp, reason=reason,
                    is_strong_push=True,   # 回落/出货一律推企微（止盈/离场判断更要紧）
                )
            return None

        # ── 上升（早盘建仓拉升）──
        at_new_high = cum > 0 and cum >= peak - 1.0    # 创当日累计净流入新高（容 1 元浮点）
        if at_new_high and window_net > 0 and tier >= 1:
            if (st.rising_count < self.cfg.max_rising_per_day
                    and self._rising_rearm(st, now, tier, big_buy_count)):
                st.rising_count += 1
                st.last_rising_ts = now
                st.last_rising_tier = tier
                st.last_rising_buy_count = big_buy_count
                tier_label = _TIER_LABEL[tier]
                reason = ("主力资金上升·%s｜累计净流入+%.0f万 力度%.1f× 日内%+.2f%% 第%d次大单买入"
                          % (tier_label, cum / 1e4, strength_mult, chg, big_buy_count))
                return CapitalTrendAlert(
                    stock_code=code, stock_name=name, trade_date=day, timestamp=now,
                    direction="RISING", strength_tier=tier_label, strength_mult=round(strength_mult, 2),
                    cum_main_net=round(cum, 2), window_main_net=round(window_net, 2),
                    pullback_amount=0.0, intraday_change_pct=round(chg, 2),
                    big_buy_count=big_buy_count, big_sell_count=big_sell_count,
                    big_order_threshold=round(large_thr, 2), last_price=lp, reason=reason,
                    is_strong_push=(tier >= 2),   # 仅强档上升推企微
                )
        return None

    # ── re-arm 规则 ────────────────────────────────────
    def _rising_rearm(self, st: _TrendState, now: float, tier: int, big_buy_count: int) -> bool:
        """首条 → 放行；冷却内仅档位升级可再报；冷却后须有新大单买入(计数前进)。"""
        if st.last_rising_ts is None:
            return True
        if tier > st.last_rising_tier:
            return True
        if (now - st.last_rising_ts >= self.cfg.cooldown_sec
                and big_buy_count > st.last_rising_buy_count):
            return True
        return False

    def _falling_rearm(self, st: _TrendState, now: float, tier: int,
                       pullback: float, large_thr: float) -> bool:
        """首条 → 放行；冷却内仅档位升级可再报；冷却后须回落进一步扩大(≥一个门槛)。"""
        if st.last_falling_ts is None:
            return True
        if tier > st.last_falling_tier:
            return True
        if (now - st.last_falling_ts >= self.cfg.cooldown_sec
                and pullback >= st.last_pullback + max(large_thr, 0.0)):
            return True
        return False
