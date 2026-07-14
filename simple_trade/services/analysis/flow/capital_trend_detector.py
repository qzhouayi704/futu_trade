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
- **力度 = 相对自身倍数**：strength_mult = |当前10min窗口主力净流入| ÷ 该股力度基准
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
    # 持仓专用主力净流出：首次即时；后续仅在净流出扩大或价格继续破位时重复提醒。
    # 不看当日涨跌、不要求先建峰，避免持仓被开盘直接砸大单却没有风险提示。
    held_immediate: bool = True
    held_cooldown_sec: int = 60      # 重复提醒最小间隔；首次仍即时提醒
    held_min_outflow: float = 1.0    # 窗口净流出需 ≥ 此倍数×该股大单门槛才推（滤掉小额净流出）
    held_min_sell_ratio: float = 2.0  # 大卖/大买至少2倍，避免买卖对敲误报
    held_min_sell_share: float = 0.70  # 或大卖占大单成交至少70%
    held_strengthen_ratio: float = 1.50  # 净流出较上次扩大50%才重复提醒
    held_price_break_pct: float = 0.015  # 或股价较上次提醒再跌1.5%
    max_held_sell_per_day: int = 4   # 每股每日持仓风险提醒硬上限
    # 大额主力资金流入状态机（由调用方先做热门度和市场宽度过滤）。
    # 不设 must-see——经治理器 INFO 预算/每股上限/折叠摘要限流，防全市场刷屏 45009。
    #
    # 【2026-07-13 收紧】原口径"窗口净流入≥1个大单门槛 + 有新大单买入"过松：只看净额、不看
    # 卖方在不在抛，也不看力度——生产当日 123 条流入提醒里大量是"大单买 55 笔 / 卖 58 笔"
    # 这种多空对砸、净额碰巧为正的噪音。用户口径：要的是**买方压倒性**那种（截图样本：
    # 大买 1334 万 / 大卖 135 万、净 +1200 万），而非"一有流入就报"。故加三道闸：
    #   ① 卖方强度：窗口大买额 ≥ inflow_min_buy_ratio × 窗口大卖额（对砸行情直接出局）
    #   ② 绝对资金量：窗口净流入 ≥ inflow_min_inflow × 该股大单门槛（默认4倍）
    #   ③ 力度：strength_mult ≥ inflow_min_mult（≥中档，原分支完全没接力度闸）
    inflow_immediate: bool = True
    inflow_cooldown_sec: int = 300     # 两次独立强流入确认至少间隔5分钟
    inflow_confirm_window_sec: int = 900  # 首次后15分钟内出现第二次才确认
    inflow_sequence_window_sec: int = 3600  # 第三次趋势加强仅统计首次后60分钟
    inflow_reentry_block_sec: int = 3600  # 本轮退出后60分钟不重新提示买入
    inflow_trail_pullback_pct: float = 0.015  # 确认后较峰值回撤1.5%提示止盈
    inflow_confirm_max_pullback_pct: float = 0.010  # 二/三次确认时距观察峰值最多回撤1%
    inflow_watch_activation_pct: float = 0.015  # 首次观察后浮盈达到1.5%启用试仓保护
    inflow_watch_trail_pct: float = 0.010  # 试仓峰值回撤1%提示退出
    inflow_min_inflow: float = 4.0     # 正常市场也需 ≥4倍大单门槛
    inflow_min_buy_ratio: float = 4.0  # 正常市场大买/大卖≥4（买占比≥80%）
    inflow_min_mult: float = 1.5       # 正常市场力度至少1.5倍
    inflow_weak_min_inflow: float = 4.0
    inflow_weak_min_buy_ratio: float = 4.0
    inflow_weak_min_mult: float = 1.5
    inflow_extreme_min_inflow: float = 5.0
    inflow_extreme_min_buy_ratio: float = 5.0
    inflow_extreme_min_mult: float = 2.0
    max_inflow_per_day: int = 6        # 最多容纳两轮首次/确认/加强；推送治理器另做每类限流

    @classmethod
    def from_env(cls) -> "CapitalTrendConfig":
        from ....utils import env_flag
        enabled = env_flag("CAPITAL_TREND_ALERT_ENABLED")
        cfg = cls(enabled=enabled)
        cfg.strong_mult = _env_float("CAPITAL_TREND_STRONG_MULT", cfg.strong_mult)
        cfg.mid_mult = _env_float("CAPITAL_TREND_MID_MULT", cfg.mid_mult)
        cfg.cooldown_sec = _env_int("CAPITAL_TREND_COOLDOWN_SEC", cfg.cooldown_sec)
        cfg.pullback_pct = _env_float("CAPITAL_TREND_PULLBACK_PCT", cfg.pullback_pct)
        cfg.max_rising_per_day = _env_int("CAPITAL_TREND_MAX_RISING", cfg.max_rising_per_day)
        cfg.max_falling_per_day = _env_int("CAPITAL_TREND_MAX_FALLING", cfg.max_falling_per_day)
        cfg.held_immediate = env_flag("CAPITAL_TREND_HELD_IMMEDIATE", True)
        cfg.held_cooldown_sec = _env_int("CAPITAL_TREND_HELD_COOLDOWN_SEC", cfg.held_cooldown_sec)
        cfg.held_min_outflow = _env_float("CAPITAL_TREND_HELD_MIN_OUTFLOW", cfg.held_min_outflow)
        cfg.held_min_sell_ratio = _env_float(
            "CAPITAL_TREND_HELD_MIN_SELL_RATIO", cfg.held_min_sell_ratio
        )
        cfg.held_min_sell_share = _env_float(
            "CAPITAL_TREND_HELD_MIN_SELL_SHARE", cfg.held_min_sell_share
        )
        cfg.held_strengthen_ratio = _env_float(
            "CAPITAL_TREND_HELD_STRENGTHEN_RATIO", cfg.held_strengthen_ratio
        )
        cfg.held_price_break_pct = _env_float(
            "CAPITAL_TREND_HELD_PRICE_BREAK_PCT", cfg.held_price_break_pct
        )
        cfg.max_held_sell_per_day = _env_int("CAPITAL_TREND_MAX_HELD_SELL", cfg.max_held_sell_per_day)
        cfg.inflow_immediate = env_flag("CAPITAL_TREND_INFLOW_IMMEDIATE", True)
        cfg.inflow_cooldown_sec = _env_int("CAPITAL_TREND_INFLOW_COOLDOWN_SEC", cfg.inflow_cooldown_sec)
        cfg.inflow_confirm_window_sec = _env_int(
            "CAPITAL_TREND_INFLOW_CONFIRM_SEC", cfg.inflow_confirm_window_sec
        )
        cfg.inflow_sequence_window_sec = _env_int(
            "CAPITAL_TREND_INFLOW_SEQUENCE_SEC", cfg.inflow_sequence_window_sec
        )
        cfg.inflow_reentry_block_sec = _env_int(
            "CAPITAL_TREND_INFLOW_REENTRY_BLOCK_SEC", cfg.inflow_reentry_block_sec
        )
        cfg.inflow_trail_pullback_pct = _env_float(
            "CAPITAL_TREND_INFLOW_TRAIL_PCT", cfg.inflow_trail_pullback_pct
        )
        cfg.inflow_confirm_max_pullback_pct = _env_float(
            "CAPITAL_TREND_INFLOW_CONFIRM_MAX_PULLBACK_PCT",
            cfg.inflow_confirm_max_pullback_pct,
        )
        cfg.inflow_watch_activation_pct = _env_float(
            "CAPITAL_TREND_INFLOW_WATCH_ACTIVATION_PCT",
            cfg.inflow_watch_activation_pct,
        )
        cfg.inflow_watch_trail_pct = _env_float(
            "CAPITAL_TREND_INFLOW_WATCH_TRAIL_PCT", cfg.inflow_watch_trail_pct
        )
        cfg.inflow_min_inflow = _env_float("CAPITAL_TREND_INFLOW_MIN", cfg.inflow_min_inflow)
        cfg.inflow_min_buy_ratio = _env_float("CAPITAL_TREND_INFLOW_BUY_RATIO", cfg.inflow_min_buy_ratio)
        cfg.inflow_min_mult = _env_float("CAPITAL_TREND_INFLOW_MIN_MULT", cfg.inflow_min_mult)
        cfg.inflow_weak_min_inflow = _env_float(
            "CAPITAL_TREND_INFLOW_WEAK_MIN", cfg.inflow_weak_min_inflow
        )
        cfg.inflow_weak_min_buy_ratio = _env_float(
            "CAPITAL_TREND_INFLOW_WEAK_BUY_RATIO", cfg.inflow_weak_min_buy_ratio
        )
        cfg.inflow_weak_min_mult = _env_float(
            "CAPITAL_TREND_INFLOW_WEAK_MIN_MULT", cfg.inflow_weak_min_mult
        )
        cfg.inflow_extreme_min_inflow = _env_float(
            "CAPITAL_TREND_INFLOW_EXTREME_MIN", cfg.inflow_extreme_min_inflow
        )
        cfg.inflow_extreme_min_buy_ratio = _env_float(
            "CAPITAL_TREND_INFLOW_EXTREME_BUY_RATIO",
            cfg.inflow_extreme_min_buy_ratio,
        )
        cfg.inflow_extreme_min_mult = _env_float(
            "CAPITAL_TREND_INFLOW_EXTREME_MIN_MULT", cfg.inflow_extreme_min_mult
        )
        cfg.max_inflow_per_day = _env_int("CAPITAL_TREND_MAX_INFLOW", cfg.max_inflow_per_day)
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
    window_main_net: float       # 当前 10min 窗口主力净流入（元）
    pullback_amount: float       # 自峰值回落额（元，FALLING 用；RISING=0）
    intraday_change_pct: float   # 日内涨幅 %
    big_buy_count: int           # 当日第几次大单买入
    big_sell_count: int          # 当日第几次大单流出
    big_order_threshold: float   # 该股大单门槛（元）
    last_price: float
    reason: str
    is_strong_push: bool         # 是否路由企微（强信号/回落）
    is_held_outflow: bool = False  # 持仓专用·主力净流出即时提醒（每笔大单卖出即报）→ 独立类别/优先级
    is_large_inflow: bool = False  # 热门股大额主力资金流入候选 → 独立类别/INFO 走预算
    window_big_buy: float = 0.0    # 窗口内大单买入额（元）——买方强度
    window_big_sell: float = 0.0   # 窗口内大单卖出额（元）——卖方强度
    window_buy_ratio: float = 0.0  # 窗口买占比 = 大买 / (大买+大卖)
    is_hot_candidate: bool = False  # 是否通过热门度+市场宽度门控
    market_breadth: float = 0.0     # 同市场上涨股占比
    market_universe_size: int = 0   # 宽度统计使用的报价数
    turnover_rank_percentile: float = 0.0  # 成交额横截面排名分位，越接近1越热门
    inflow_gate_reason: str = ""    # 门控判定说明
    inflow_stage: str = ""          # FIRST / CONFIRMED / STRENGTHENED / EXPIRED / TRAIL_EXIT
    inflow_sequence_no: int = 0      # 本轮第几次独立强流入
    inflow_first_price: float = 0.0
    inflow_peak_price: float = 0.0
    price_pullback_pct: float = 0.0
    is_inflow_expired: bool = False
    is_inflow_trailing_exit: bool = False
    is_watch_trailing_exit: bool = False
    is_profit_exit: bool = False
    inflow_confirm_price: float = 0.0
    inflow_risk_mode: str = "NORMAL"
    plate_name: str = ""
    plate_breadth: float = 0.0
    plate_universe_size: int = 0
    plate_median_change_pct: float = 0.0
    relative_strength_pct: float = 0.0
    required_confirmations: int = 2
    wechat_suppressed: bool = False
    is_held_outflow_recovery: bool = False
    held_outflow_level: str = ""

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
    last_held_sell_ts: Optional[float] = None
    last_held_sell_count: int = 0
    held_sell_alerts: int = 0
    held_outflow_active: bool = False
    last_held_outflow_amount: float = 0.0
    last_held_alert_price: float = 0.0
    last_inflow_ts: Optional[float] = None
    last_inflow_buy_count: int = 0
    last_seen_buy_count: int = 0
    inflow_alerts: int = 0
    inflow_stage: str = ""
    inflow_first_ts: Optional[float] = None
    inflow_first_price: float = 0.0
    inflow_confirmed_ts: Optional[float] = None
    inflow_confirm_price: float = 0.0
    inflow_peak_price: float = 0.0
    inflow_sequence_no: int = 0
    inflow_risk_mode: str = "NORMAL"
    inflow_required_confirmations: int = 2
    inflow_block_until: Optional[float] = None


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
        is_held: bool = False,
        inflow_context: Optional[dict] = None,
    ) -> Optional[CapitalTrendAlert]:
        """对一只股票的当前快照判断是否产出一条趋势提醒；不产出返回 None。

        tiers = (大单门槛, 超大单门槛, 力度基准 window_net_scale)。
        is_held=True 时额外启用"持仓主力净流出即时提醒"（每笔大单卖出即报，见下）。
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

        cum = float(snapshot.get("cum_main_net") or 0.0)
        peak = float(snapshot.get("cum_peak") or 0.0)
        window_net = float(snapshot.get("window_main_net") or 0.0)
        big_buy_count = int(snapshot.get("big_buy_count") or 0)
        big_sell_count = int(snapshot.get("big_sell_count") or 0)
        # 窗口内买卖强度分解（累加器 snapshot 提供）。老快照/持久化回填可能没有这两个字段 →
        # 视为"卖方强度未知"，此时买卖比闸放行（量闸/力度闸仍在），不静默拦截。
        has_bs = ("window_big_buy" in snapshot) or ("window_big_sell" in snapshot)
        win_buy = float(snapshot.get("window_big_buy") or 0.0)
        win_sell = float(snapshot.get("window_big_sell") or 0.0)
        win_ratio = win_buy / (win_buy + win_sell) if (win_buy + win_sell) > 0 else 0.0

        def _buy_side_dominant(min_ratio: float) -> bool:
            """卖方在不在抛：窗口大买额须压倒大卖额（无卖方=直接通过）。"""
            if not has_bs:
                return True
            if win_sell <= 0:
                return win_buy > 0
            return win_buy >= min_ratio * win_sell

        chg = 0.0
        if last_price and prev_close and prev_close > 0:
            chg = (float(last_price) - float(prev_close)) / float(prev_close) * 100.0
        name = stock_name or code
        lp = float(last_price or 0.0)
        inflow_allowed = (bool(inflow_context.get("eligible"))
                          if inflow_context is not None else True)
        is_hot_candidate = (bool(inflow_context.get("is_hot"))
                            if inflow_context is not None else False)
        market_breadth = float((inflow_context or {}).get("market_breadth") or 0.0)
        market_universe_size = int((inflow_context or {}).get("market_universe_size") or 0)
        turnover_rank = float((inflow_context or {}).get("turnover_rank_percentile") or 0.0)
        gate_reason = str((inflow_context or {}).get("reason") or "")
        risk_mode = str((inflow_context or {}).get("risk_mode") or "NORMAL")
        plate_name = str((inflow_context or {}).get("plate_name") or "")
        plate_breadth = float((inflow_context or {}).get("plate_breadth") or 0.0)
        plate_universe_size = int((inflow_context or {}).get("plate_universe_size") or 0)
        plate_median_change = float(
            (inflow_context or {}).get("plate_median_change_pct") or 0.0
        )
        relative_strength = float(
            (inflow_context or {}).get("relative_strength_pct") or 0.0
        )
        required_confirmations = int(
            (inflow_context or {}).get("required_confirmations") or 2
        )
        alert_context = {
            "is_hot_candidate": is_hot_candidate,
            "market_breadth": round(market_breadth, 4),
            "market_universe_size": market_universe_size,
            "turnover_rank_percentile": round(turnover_rank, 4),
            "inflow_gate_reason": gate_reason,
            "inflow_risk_mode": risk_mode,
            "plate_name": plate_name,
            "plate_breadth": round(plate_breadth, 4),
            "plate_universe_size": plate_universe_size,
            "plate_median_change_pct": round(plate_median_change, 4),
            "relative_strength_pct": round(relative_strength, 4),
            "required_confirmations": required_confirmations,
        }

        def _state_alert_context() -> dict:
            context = dict(alert_context)
            context["inflow_risk_mode"] = st.inflow_risk_mode
            context["required_confirmations"] = st.inflow_required_confirmations
            return context
        new_big_buy = big_buy_count > st.last_seen_buy_count
        st.last_seen_buy_count = max(st.last_seen_buy_count, big_buy_count)

        if st.inflow_stage in {"WATCH", "SECOND_WATCH", "CONFIRMED"} and lp > 0:
            st.inflow_peak_price = max(st.inflow_peak_price, lp)

        # 持仓流出先判断买卖结构，首次即时；后续仅在流出扩大或价格继续破位时提醒。
        thr_eff = large_thr if large_thr > 0 else 100_000.0
        sell_share = win_sell / (win_buy + win_sell) if (win_buy + win_sell) > 0 else 0.0
        sell_ratio = win_sell / win_buy if win_buy > 0 else (float("inf") if win_sell > 0 else 0.0)
        sell_structure = (
            not has_bs
            or sell_ratio >= self.cfg.held_min_sell_ratio
            or sell_share >= self.cfg.held_min_sell_share
        )

        if (is_held and st.held_outflow_active and window_net >= 0 and new_big_buy):
            st.held_outflow_active = False
            st.last_held_outflow_amount = 0.0
            reason = (
                "持仓流出被承接·风险降级｜窗口净流入%+.0f万 大买%.0f万/大卖%.0f万 "
                "日内%+.2f%%"
                % (window_net / 1e4, win_buy / 1e4, win_sell / 1e4, chg)
            )
            return CapitalTrendAlert(
                stock_code=code, stock_name=name, trade_date=day, timestamp=now,
                direction="RISING", strength_tier="中", strength_mult=0.0,
                cum_main_net=round(cum, 2), window_main_net=round(window_net, 2),
                pullback_amount=0.0, intraday_change_pct=round(chg, 2),
                big_buy_count=big_buy_count, big_sell_count=big_sell_count,
                big_order_threshold=round(large_thr, 2), last_price=lp, reason=reason,
                is_strong_push=True, is_held_outflow_recovery=True,
                held_outflow_level="RECOVERED",
                window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                window_buy_ratio=round(win_ratio, 4), **alert_context,
            )

        outflow_amount = abs(window_net)
        first_outflow = not st.held_outflow_active
        strengthened_outflow = (
            st.held_outflow_active
            and outflow_amount >= st.last_held_outflow_amount * self.cfg.held_strengthen_ratio
        )
        price_break = (
            st.held_outflow_active and st.last_held_alert_price > 0 and lp > 0
            and lp <= st.last_held_alert_price * (1.0 - self.cfg.held_price_break_pct)
        )
        held_cooldown_ok = (
            st.last_held_sell_ts is None
            or now - st.last_held_sell_ts >= self.cfg.held_cooldown_sec
        )
        held_outflow_condition = (
            is_held and self.cfg.held_immediate and window_net < 0
            and outflow_amount >= self.cfg.held_min_outflow * thr_eff
            and sell_structure
        )
        if (held_outflow_condition
                and st.held_sell_alerts < self.cfg.max_held_sell_per_day
                and held_cooldown_ok
                and ((first_outflow and big_sell_count > st.last_held_sell_count)
                     or strengthened_outflow or price_break)):
            new_sells = big_sell_count - st.last_held_sell_count
            scale_eff = scale if scale > 0 else thr_eff
            mult = outflow_amount / scale_eff if scale_eff > 0 else 0.0
            tier_lbl = _TIER_LABEL[self._tier(mult)]
            level = "FIRST" if first_outflow else ("STRENGTHENED" if strengthened_outflow else "PRICE_BREAK")
            st.held_sell_alerts += 1
            st.last_held_sell_ts = now
            st.last_held_sell_count = big_sell_count
            st.held_outflow_active = True
            st.last_held_outflow_amount = outflow_amount
            st.last_held_alert_price = lp
            if st.inflow_stage in {"WATCH", "SECOND_WATCH", "CONFIRMED"}:
                st.inflow_stage = "TRAIL_EXIT"
                st.inflow_block_until = now + self.cfg.inflow_reentry_block_sec
            extra = f"（新增{new_sells}笔）" if new_sells > 1 else ""
            level_text = {"FIRST": "首次风险", "STRENGTHENED": "流出扩大", "PRICE_BREAK": "价格破位"}[level]
            reason = (
                "持仓大单净流出·%s｜窗口净流出%.0f万 大卖占比%.0f%% 力度%.1f× "
                "日内%+.2f%% 第%d次大单流出%s"
                % (level_text, outflow_amount / 1e4, sell_share * 100, mult, chg,
                   big_sell_count, extra)
            )
            return CapitalTrendAlert(
                stock_code=code, stock_name=name, trade_date=day, timestamp=now,
                direction="FALLING", strength_tier=tier_lbl, strength_mult=round(mult, 2),
                cum_main_net=round(cum, 2), window_main_net=round(window_net, 2),
                pullback_amount=0.0, intraday_change_pct=round(chg, 2),
                big_buy_count=big_buy_count, big_sell_count=big_sell_count,
                big_order_threshold=round(large_thr, 2), last_price=lp, reason=reason,
                is_strong_push=True, is_held_outflow=True,
                held_outflow_level=level,
                window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                window_buy_ratio=round(win_ratio, 4), **alert_context,
            )

        # 持仓风险统一由上面的恶化条件重发，避免绕入通用回落分支造成重复推送。
        if held_outflow_condition:
            return None

        # 观察期间出现一个门槛以上净流出，直接使本轮确认失效。
        if (st.inflow_stage in {"WATCH", "SECOND_WATCH"}
                and window_net <= -thr_eff):
            first_price = st.inflow_first_price
            first_peak = st.inflow_peak_price
            sequence_no = st.inflow_sequence_no
            st.inflow_stage = ""
            st.inflow_first_ts = None
            st.inflow_sequence_no = 0
            st.inflow_block_until = now + self.cfg.inflow_confirm_window_sec
            reason = (
                "观察期间出现大单净流出·确认失效｜窗口净流出%.0f万 首次价%.3f "
                "现价%.3f"
                % (outflow_amount / 1e4, first_price, lp)
            )
            return CapitalTrendAlert(
                stock_code=code, stock_name=name, trade_date=day, timestamp=now,
                direction="FALLING", strength_tier="中", strength_mult=round(outflow_amount / thr_eff, 2),
                cum_main_net=round(cum, 2), window_main_net=round(window_net, 2),
                pullback_amount=0.0, intraday_change_pct=round(chg, 2),
                big_buy_count=big_buy_count, big_sell_count=big_sell_count,
                big_order_threshold=round(large_thr, 2), last_price=lp, reason=reason,
                is_strong_push=False, is_large_inflow=True,
                window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                window_buy_ratio=round(win_ratio, 4), inflow_stage="INVALIDATED",
                inflow_sequence_no=sequence_no, inflow_first_price=round(first_price, 4),
                inflow_peak_price=round(first_peak, 4), wechat_suppressed=True,
                **_state_alert_context(),
            )

        # 首次观察后先保护试仓；达到1.5%浮盈后，从峰值回撤1%提示退出。
        if (st.inflow_stage in {"WATCH", "SECOND_WATCH"}
                and st.inflow_first_price > 0 and st.inflow_peak_price > 0 and lp > 0):
            peak_gain = (st.inflow_peak_price - st.inflow_first_price) / st.inflow_first_price
            price_pullback = (st.inflow_peak_price - lp) / st.inflow_peak_price
            if (peak_gain >= self.cfg.inflow_watch_activation_pct
                    and price_pullback >= self.cfg.inflow_watch_trail_pct):
                sequence_no = st.inflow_sequence_no
                st.inflow_stage = "TRAIL_EXIT"
                st.inflow_block_until = now + self.cfg.inflow_reentry_block_sec
                reason = (
                    "试仓浮盈保护·回撤退出｜首次价%.3f 峰值%.3f 现价%.3f "
                    "峰值回撤%.1f%%"
                    % (st.inflow_first_price, st.inflow_peak_price, lp,
                       price_pullback * 100)
                )
                return CapitalTrendAlert(
                    stock_code=code, stock_name=name, trade_date=day, timestamp=now,
                    direction="FALLING", strength_tier="强",
                    strength_mult=round(price_pullback * 100, 2),
                    cum_main_net=round(cum, 2), window_main_net=round(window_net, 2),
                    pullback_amount=0.0, intraday_change_pct=round(chg, 2),
                    big_buy_count=big_buy_count, big_sell_count=big_sell_count,
                    big_order_threshold=round(large_thr, 2), last_price=lp, reason=reason,
                    is_strong_push=True,
                    window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                    window_buy_ratio=round(win_ratio, 4),
                    inflow_stage="WATCH_TRAIL_EXIT", inflow_sequence_no=sequence_no,
                    inflow_first_price=round(st.inflow_first_price, 4),
                    inflow_peak_price=round(st.inflow_peak_price, 4),
                    price_pullback_pct=round(price_pullback, 4),
                    is_inflow_trailing_exit=True, is_watch_trailing_exit=True,
                    **_state_alert_context(),
                )

        # 已确认后的价格峰值回撤退出；仅高于确认价时标为止盈。
        if (st.inflow_stage == "CONFIRMED" and st.inflow_peak_price > 0 and lp > 0):
            price_pullback = (st.inflow_peak_price - lp) / st.inflow_peak_price
            if price_pullback >= self.cfg.inflow_trail_pullback_pct:
                st.inflow_stage = "TRAIL_EXIT"
                st.inflow_block_until = now + self.cfg.inflow_reentry_block_sec
                is_profit_exit = lp > st.inflow_confirm_price > 0
                exit_text = "止盈提醒" if is_profit_exit else "确认失败/回撤退出"
                reason = (
                    "资金流买点确认后峰值回撤%.1f%%·%s｜首次价%.3f "
                    "峰值%.3f 现价%.3f 日内%+.2f%%"
                    % (price_pullback * 100, exit_text, st.inflow_first_price,
                       st.inflow_peak_price, lp, chg)
                )
                return CapitalTrendAlert(
                    stock_code=code, stock_name=name, trade_date=day, timestamp=now,
                    direction="FALLING", strength_tier="强", strength_mult=round(price_pullback * 100, 2),
                    cum_main_net=round(cum, 2), window_main_net=round(window_net, 2),
                    pullback_amount=0.0, intraday_change_pct=round(chg, 2),
                    big_buy_count=big_buy_count, big_sell_count=big_sell_count,
                    big_order_threshold=round(large_thr, 2), last_price=lp, reason=reason,
                    is_strong_push=True,
                    window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                    window_buy_ratio=round(win_ratio, 4),
                    inflow_stage="TRAIL_EXIT", inflow_sequence_no=st.inflow_sequence_no,
                    inflow_first_price=round(st.inflow_first_price, 4),
                    inflow_peak_price=round(st.inflow_peak_price, 4),
                    price_pullback_pct=round(price_pullback, 4),
                    is_inflow_trailing_exit=True, is_profit_exit=is_profit_exit,
                    inflow_confirm_price=round(st.inflow_confirm_price, 4),
                    **_state_alert_context(),
                )

        # 强流入状态机：正常/弱市二次确认，极弱市三次确认。
        inflow_scale_eff = scale if scale > 0 else thr_eff
        inflow_mult = window_net / inflow_scale_eff if inflow_scale_eff > 0 else 0.0
        if risk_mode == "EXTREME":
            min_inflow = self.cfg.inflow_extreme_min_inflow
            min_buy_ratio = self.cfg.inflow_extreme_min_buy_ratio
            min_mult = self.cfg.inflow_extreme_min_mult
        elif risk_mode == "WEAK":
            min_inflow = self.cfg.inflow_weak_min_inflow
            min_buy_ratio = self.cfg.inflow_weak_min_buy_ratio
            min_mult = self.cfg.inflow_weak_min_mult
        else:
            min_inflow = self.cfg.inflow_min_inflow
            min_buy_ratio = self.cfg.inflow_min_buy_ratio
            min_mult = self.cfg.inflow_min_mult
        strong_inflow = (
            self.cfg.inflow_immediate
            and inflow_allowed
            and window_net >= min_inflow * thr_eff
            and _buy_side_dominant(min_buy_ratio)
            and inflow_mult >= min_mult
            and new_big_buy
        )

        state_context = _state_alert_context()
        active_watch = st.inflow_stage in {"WATCH", "SECOND_WATCH"}
        watch_timeout = (
            self.cfg.inflow_sequence_window_sec
            if st.inflow_required_confirmations >= 3
            else self.cfg.inflow_confirm_window_sec
        )
        if (active_watch and st.inflow_first_ts is not None
                and now - st.inflow_first_ts > watch_timeout):
            if not strong_inflow:
                first_price = st.inflow_first_price
                first_peak = st.inflow_peak_price
                sequence_no = st.inflow_sequence_no
                st.inflow_stage = ""
                st.inflow_first_ts = None
                st.inflow_sequence_no = 0
                reason = (
                    "%d次确认窗口内未满足·观察失效｜首次价%.3f 现价%.3f 日内%+.2f%%"
                    % (st.inflow_required_confirmations, first_price, lp, chg)
                )
                return CapitalTrendAlert(
                    stock_code=code, stock_name=name, trade_date=day, timestamp=now,
                    direction="RISING", strength_tier="弱", strength_mult=round(max(inflow_mult, 0.0), 2),
                    cum_main_net=round(cum, 2), window_main_net=round(window_net, 2),
                    pullback_amount=0.0, intraday_change_pct=round(chg, 2),
                    big_buy_count=big_buy_count, big_sell_count=big_sell_count,
                    big_order_threshold=round(large_thr, 2), last_price=lp, reason=reason,
                    is_strong_push=False,
                    window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                    window_buy_ratio=round(win_ratio, 4),
                    inflow_stage="EXPIRED", inflow_sequence_no=sequence_no,
                    inflow_first_price=round(first_price, 4),
                    inflow_peak_price=round(first_peak, 4),
                    is_inflow_expired=True, wechat_suppressed=True,
                    **state_context,
                )
            st.inflow_stage = ""
            st.inflow_first_ts = None
            st.inflow_sequence_no = 0

        reentry_blocked = st.inflow_block_until is not None and now < st.inflow_block_until
        independent = st.last_inflow_ts is None or now - st.last_inflow_ts >= self.cfg.inflow_cooldown_sec
        sequence_saturated = (
            st.inflow_stage == "CONFIRMED"
            and (
                st.inflow_sequence_no >= 3
                or st.inflow_first_ts is None
                or now - st.inflow_first_ts > self.cfg.inflow_sequence_window_sec
            )
        )
        if (strong_inflow and independent and not reentry_blocked
                and not sequence_saturated
                and st.inflow_alerts < self.cfg.max_inflow_per_day):
            new_buys = big_buy_count - st.last_inflow_buy_count
            tier_lbl = _TIER_LABEL[self._tier(inflow_mult)]
            st.inflow_alerts += 1
            st.last_inflow_ts = now
            st.last_inflow_buy_count = big_buy_count
            extra = f"（本轮新增{new_buys}笔）" if new_buys > 1 else ""
            bs_txt = ("(大买%.0f万/大卖%.0f万 买占比%.0f%%) " % (win_buy / 1e4, win_sell / 1e4, win_ratio * 100)
                      if has_bs else "")
            hot_txt = ("市场宽度%.0f%% 成交额前%.0f%% "
                       % (market_breadth * 100, max(0.0, (1.0 - turnover_rank) * 100))
                       if inflow_context is not None else "")
            plate_txt = (
                "%s宽度%.0f%% 相对板块%+.1f点 "
                % (plate_name, plate_breadth * 100, relative_strength)
                if plate_name else ""
            )

            confirming = (
                st.inflow_stage == "SECOND_WATCH"
                or (st.inflow_stage == "WATCH" and st.inflow_required_confirmations == 2)
            )
            if confirming:
                peak_pullback = (
                    (st.inflow_peak_price - lp) / st.inflow_peak_price
                    if st.inflow_peak_price > 0 and lp > 0 else 0.0
                )
                price_quality_ok = (
                    lp > 0
                    and lp >= st.inflow_first_price
                    and peak_pullback <= self.cfg.inflow_confirm_max_pullback_pct
                )
                if not price_quality_ok:
                    first_price = st.inflow_first_price
                    first_peak = st.inflow_peak_price
                    sequence_no = st.inflow_sequence_no + 1
                    st.inflow_stage = ""
                    st.inflow_first_ts = None
                    st.inflow_sequence_no = 0
                    st.inflow_block_until = now + self.cfg.inflow_confirm_window_sec
                    reason = (
                        "资金继续流入但价格确认失败·冲高回落｜首次价%.3f 峰值%.3f "
                        "现价%.3f 峰值回撤%.1f%%"
                        % (first_price, first_peak, lp, peak_pullback * 100)
                    )
                    return CapitalTrendAlert(
                        stock_code=code, stock_name=name, trade_date=day, timestamp=now,
                        direction="RISING", strength_tier=tier_lbl,
                        strength_mult=round(inflow_mult, 2),
                        cum_main_net=round(cum, 2), window_main_net=round(window_net, 2),
                        pullback_amount=0.0, intraday_change_pct=round(chg, 2),
                        big_buy_count=big_buy_count, big_sell_count=big_sell_count,
                        big_order_threshold=round(large_thr, 2), last_price=lp,
                        reason=reason, is_strong_push=False, is_large_inflow=True,
                        window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                        window_buy_ratio=round(win_ratio, 4), inflow_stage="REJECTED",
                        inflow_sequence_no=sequence_no,
                        inflow_first_price=round(first_price, 4),
                        inflow_peak_price=round(first_peak, 4),
                        price_pullback_pct=round(peak_pullback, 4),
                        wechat_suppressed=True, **state_context,
                    )

            if st.inflow_stage == "WATCH":
                if st.inflow_required_confirmations >= 3:
                    stage = "SECOND_WATCH"
                    st.inflow_stage = stage
                    st.inflow_sequence_no = 2
                    reason = (
                        "极弱市第二次强流入·继续观察（等待第三次确认）｜窗口净流入+%.0f万 "
                        "%s%s%s力度%.1f× 日内%+.2f%% 第%d次大单买入%s"
                        % (window_net / 1e4, bs_txt, hot_txt, plate_txt, inflow_mult,
                           chg, big_buy_count, extra)
                    )
                else:
                    stage = "CONFIRMED"
                    st.inflow_stage = stage
                    st.inflow_confirmed_ts = now
                    st.inflow_confirm_price = lp
                    st.inflow_sequence_no = 2
                    reason = (
                        "15分钟内第二次强流入·买点确认/继续持有｜窗口净流入+%.0f万 "
                        "%s%s%s力度%.1f× 日内%+.2f%% 第%d次大单买入%s"
                        % (window_net / 1e4, bs_txt, hot_txt, plate_txt, inflow_mult,
                           chg, big_buy_count, extra)
                    )
            elif st.inflow_stage == "SECOND_WATCH":
                stage = "CONFIRMED"
                st.inflow_stage = stage
                st.inflow_confirmed_ts = now
                st.inflow_confirm_price = lp
                st.inflow_sequence_no = 3
                reason = (
                    "60分钟内第三次强流入·极弱市逆势确认｜窗口净流入+%.0f万 "
                    "%s%s%s力度%.1f× 日内%+.2f%% 第%d次大单买入%s"
                    % (window_net / 1e4, bs_txt, hot_txt, plate_txt, inflow_mult,
                       chg, big_buy_count, extra)
                )
            elif (st.inflow_stage == "CONFIRMED" and st.inflow_first_ts is not None
                  and st.inflow_sequence_no == 2
                  and now - st.inflow_first_ts <= self.cfg.inflow_sequence_window_sec):
                stage = "STRENGTHENED"
                st.inflow_sequence_no = 3
                reason = ("60分钟内第三次强流入·趋势加强/继续持有｜窗口净流入+%.0f万 "
                          "%s%s%s力度%.1f× 日内%+.2f%% 第%d次大单买入%s"
                          % (window_net / 1e4, bs_txt, hot_txt, plate_txt, inflow_mult, chg,
                             big_buy_count, extra))
            else:
                stage = "FIRST"
                st.inflow_stage = "WATCH"
                st.inflow_first_ts = now
                st.inflow_first_price = lp
                st.inflow_confirmed_ts = None
                st.inflow_confirm_price = 0.0
                st.inflow_peak_price = lp
                st.inflow_sequence_no = 1
                st.inflow_risk_mode = risk_mode
                st.inflow_required_confirmations = required_confirmations
                watch_text = {
                    "NORMAL": "试仓观察（等待15分钟二次确认）",
                    "WEAK": "弱市逆势观察（等待15分钟二次确认）",
                    "EXTREME": "极弱市观察（60分钟内需三次确认）",
                }.get(risk_mode, "试仓观察")
                reason = ("首次强流入·%s｜窗口净流入+%.0f万 "
                          "%s%s%s力度%.1f× 日内%+.2f%% 第%d次大单买入%s"
                          % (watch_text, window_net / 1e4, bs_txt, hot_txt, plate_txt,
                             inflow_mult, chg,
                             big_buy_count, extra))

            event_context = dict(alert_context)
            event_context["inflow_risk_mode"] = st.inflow_risk_mode
            event_context["required_confirmations"] = st.inflow_required_confirmations
            suppress_wechat = (
                st.inflow_risk_mode == "EXTREME"
                and stage in {"FIRST", "SECOND_WATCH"}
            )
            return CapitalTrendAlert(
                stock_code=code, stock_name=name, trade_date=day, timestamp=now,
                direction="RISING", strength_tier=tier_lbl, strength_mult=round(inflow_mult, 2),
                cum_main_net=round(cum, 2), window_main_net=round(window_net, 2),
                pullback_amount=0.0, intraday_change_pct=round(chg, 2),
                big_buy_count=big_buy_count, big_sell_count=big_sell_count,
                big_order_threshold=round(large_thr, 2), last_price=lp, reason=reason,
                is_strong_push=(stage in {"CONFIRMED", "STRENGTHENED"}), is_large_inflow=True,
                window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                window_buy_ratio=round(win_ratio, 4),
                inflow_stage=stage,
                inflow_sequence_no=st.inflow_sequence_no,
                inflow_first_price=round(st.inflow_first_price, 4),
                inflow_peak_price=round(st.inflow_peak_price, 4),
                inflow_confirm_price=round(st.inflow_confirm_price, 4),
                wechat_suppressed=suppress_wechat, **event_context,
            )

        if scale <= 0:
            return None
        strength_mult = abs(window_net) / scale
        tier = self._tier(strength_mult)

        # ── 回落 / 拉高出货（优先判断；两类都属 FALLING，一律推企微）──
        #   ① retreat：主力资金从当日净流入峰值回落（先涨后撤）。
        #   ② distribution：无净流入峰值，但**股价在涨而主力大单净流出**——典型"拉高出货"
        #      (治用户 06-24 痛点：日内拉高、最终净流出，该在拉高时及时卖)。
        pullback = peak - cum
        had_peak = peak >= large_thr
        retreat = had_peak and pullback >= max(large_thr, peak * self.cfg.pullback_pct)
        distribution = (not had_peak) and chg > 0 and cum <= -large_thr
        if window_net < 0 and tier >= 1 and sell_structure and (retreat or distribution):
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
                    window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                    window_buy_ratio=round(win_ratio, 4),
                )
            return None

        # ── 上升（早盘建仓拉升）──
        #   同样过"卖方强度"闸：多空对砸(买500万/卖400万)只是净额偏正，不是主力在扫货。
        at_new_high = cum > 0 and cum >= peak - 1.0    # 创当日累计净流入新高（容 1 元浮点）
        if (inflow_allowed and st.inflow_stage not in {"WATCH", "CONFIRMED"}
                and at_new_high and window_net > 0
                and tier >= 1 and _buy_side_dominant(self.cfg.inflow_min_buy_ratio)):
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
                    window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                    window_buy_ratio=round(win_ratio, 4),
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
