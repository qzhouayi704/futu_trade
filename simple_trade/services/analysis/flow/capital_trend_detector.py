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
    # 持仓专用·主力净流出提醒（用户口径：按 1 分钟推一次、仅大单级别净流出才推、小额不推、
    # 不看涨跌、不要求先建峰）——治"持仓被开盘直接砸大单却零提醒"盲区（讯策 9:49）。
    # held_cooldown_sec=60 → 每股每分钟至多一条，期间新增大单笔数攒进这一条文案（不漏）。
    held_immediate: bool = True
    held_cooldown_sec: int = 60      # 每股推送最小间隔秒（1 分钟一次；期间新增大单攒进一条）
    held_min_outflow: float = 1.0    # 窗口净流出需 ≥ 此倍数×该股大单门槛才推（滤掉小额净流出）
    max_held_sell_per_day: int = 20  # 每股每日持仓提醒硬上限
    # 大额主力资金流入候选（由调用方先做热门度和市场宽度过滤，1 分钟一次）。
    # 不设 must-see——经治理器 INFO 预算/每股上限/折叠摘要限流，防全市场刷屏 45009。
    #
    # 【2026-07-13 收紧】原口径"窗口净流入≥1个大单门槛 + 有新大单买入"过松：只看净额、不看
    # 卖方在不在抛，也不看力度——生产当日 123 条流入提醒里大量是"大单买 55 笔 / 卖 58 笔"
    # 这种多空对砸、净额碰巧为正的噪音。用户口径：要的是**买方压倒性**那种（截图样本：
    # 大买 1334 万 / 大卖 135 万、净 +1200 万），而非"一有流入就报"。故加三道闸：
    #   ① 卖方强度：窗口大买额 ≥ inflow_min_buy_ratio × 窗口大卖额（对砸行情直接出局）
    #   ② 绝对资金量：窗口净流入 ≥ inflow_min_inflow × 该股大单门槛（默认 1→3 倍）
    #   ③ 力度：strength_mult ≥ inflow_min_mult（≥中档，原分支完全没接力度闸）
    inflow_immediate: bool = True
    inflow_cooldown_sec: int = 60      # 每股推送最小间隔秒（1 分钟一次）
    inflow_min_inflow: float = 3.0     # 窗口净流入需 ≥ 此倍数×该股大单门槛才推
    inflow_min_buy_ratio: float = 3.0  # 窗口大买额 ≥ 此倍数×窗口大卖额（买占比 ≥75%）才推
    inflow_min_mult: float = 1.0       # 力度倍数下限（≥中档）
    max_inflow_per_day: int = 8        # 每股每日大额流入提醒硬上限

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
        cfg.max_held_sell_per_day = _env_int("CAPITAL_TREND_MAX_HELD_SELL", cfg.max_held_sell_per_day)
        cfg.inflow_immediate = env_flag("CAPITAL_TREND_INFLOW_IMMEDIATE", True)
        cfg.inflow_cooldown_sec = _env_int("CAPITAL_TREND_INFLOW_COOLDOWN_SEC", cfg.inflow_cooldown_sec)
        cfg.inflow_min_inflow = _env_float("CAPITAL_TREND_INFLOW_MIN", cfg.inflow_min_inflow)
        cfg.inflow_min_buy_ratio = _env_float("CAPITAL_TREND_INFLOW_BUY_RATIO", cfg.inflow_min_buy_ratio)
        cfg.inflow_min_mult = _env_float("CAPITAL_TREND_INFLOW_MIN_MULT", cfg.inflow_min_mult)
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
    window_main_net: float       # 当前 15min 窗口主力净流入（元）
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
    last_inflow_ts: Optional[float] = None
    last_inflow_buy_count: int = 0
    inflow_alerts: int = 0


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

        def _buy_side_dominant() -> bool:
            """卖方在不在抛：窗口大买额须压倒大卖额（无卖方=直接通过）。"""
            if not has_bs:
                return True
            if win_sell <= 0:
                return win_buy > 0
            return win_buy >= self.cfg.inflow_min_buy_ratio * win_sell

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

        # ── 持仓专用·主力净流出提醒（用户口径：1 分钟推一次、仅大单级别净流出才推、小额不推）──
        #   条件：持仓 + 窗口净流出 ≥ 一个大单门槛（滤小额）+ 有新的大单卖出（big_sell_count 前进）。
        #   不看涨跌、不要求先建峰——治"持仓被开盘直接砸大单却零提醒"盲区（讯策 9:49）。
        #   held_cooldown_sec=60 → 每股每分钟至多一条，期间的新大单笔数攒进这一条文案（不漏）。
        #   放在 scale 守卫之前，且门槛/力度基准缺失时回退，保证未标定的持仓股也能报。
        thr_eff = large_thr if large_thr > 0 else 100_000.0
        if (is_held and self.cfg.held_immediate and window_net < 0
                and abs(window_net) >= self.cfg.held_min_outflow * thr_eff
                and big_sell_count > st.last_held_sell_count
                and st.held_sell_alerts < self.cfg.max_held_sell_per_day
                and (st.last_held_sell_ts is None
                     or now - st.last_held_sell_ts >= self.cfg.held_cooldown_sec)):
            new_sells = big_sell_count - st.last_held_sell_count
            scale_eff = scale if scale > 0 else thr_eff
            mult = abs(window_net) / scale_eff if scale_eff > 0 else 0.0
            tier_lbl = _TIER_LABEL[self._tier(mult)]
            st.held_sell_alerts += 1
            st.last_held_sell_ts = now
            st.last_held_sell_count = big_sell_count
            extra = f"（本轮新增{new_sells}笔）" if new_sells > 1 else ""
            reason = ("持仓大单净流出·卖出提醒｜窗口净流出%.0f万 力度%.1f× 日内%+.2f%% 第%d次大单流出%s"
                      % (abs(window_net) / 1e4, mult, chg, big_sell_count, extra))
            return CapitalTrendAlert(
                stock_code=code, stock_name=name, trade_date=day, timestamp=now,
                direction="FALLING", strength_tier=tier_lbl, strength_mult=round(mult, 2),
                cum_main_net=round(cum, 2), window_main_net=round(window_net, 2),
                pullback_amount=0.0, intraday_change_pct=round(chg, 2),
                big_buy_count=big_buy_count, big_sell_count=big_sell_count,
                big_order_threshold=round(large_thr, 2), last_price=lp, reason=reason,
                is_strong_push=True, is_held_outflow=True,
                window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                window_buy_ratio=round(win_ratio, 4),
            )

        # ── 大额主力资金流入候选（热门度和市场宽度门控后，1 分钟一次）──
        #   发现主力**压倒性**进场。独立类别、INFO 级——经治理器预算/每股上限/折叠摘要限流
        #   （不设 must-see，防强势行情几十只同时触发刷屏 45009）。不看涨跌、不要求先建峰。
        #   三道闸(见 CapitalTrendConfig 注释)：卖方强度 + 绝对资金量 + 力度。
        inflow_scale_eff = scale if scale > 0 else thr_eff
        inflow_mult = window_net / inflow_scale_eff if inflow_scale_eff > 0 else 0.0
        if (self.cfg.inflow_immediate and inflow_allowed and window_net > 0
                and window_net >= self.cfg.inflow_min_inflow * thr_eff      # ② 绝对资金量
                and _buy_side_dominant()                                    # ① 卖方强度
                and inflow_mult >= self.cfg.inflow_min_mult                 # ③ 力度
                and big_buy_count > st.last_inflow_buy_count
                and st.inflow_alerts < self.cfg.max_inflow_per_day
                and (st.last_inflow_ts is None
                     or now - st.last_inflow_ts >= self.cfg.inflow_cooldown_sec)):
            new_buys = big_buy_count - st.last_inflow_buy_count
            tier_lbl = _TIER_LABEL[self._tier(inflow_mult)]
            st.inflow_alerts += 1
            st.last_inflow_ts = now
            st.last_inflow_buy_count = big_buy_count
            extra = f"（本轮新增{new_buys}笔）" if new_buys > 1 else ""
            # 文案摊开买卖强度：让人一眼看出"买方压倒"而不是"多空对砸净额偏正"
            bs_txt = ("(大买%.0f万/大卖%.0f万 买占比%.0f%%) " % (win_buy / 1e4, win_sell / 1e4, win_ratio * 100)
                      if has_bs else "")
            hot_txt = ("市场宽度%.0f%% 成交额前%.0f%% "
                       % (market_breadth * 100, max(0.0, (1.0 - turnover_rank) * 100))
                       if inflow_context is not None else "")
            reason = ("热门股大额主力资金流入候选｜窗口净流入+%.0f万 %s%s力度%.1f× 日内%+.2f%% "
                      "第%d次大单买入%s"
                      % (window_net / 1e4, bs_txt, hot_txt, inflow_mult, chg,
                         big_buy_count, extra))
            return CapitalTrendAlert(
                stock_code=code, stock_name=name, trade_date=day, timestamp=now,
                direction="RISING", strength_tier=tier_lbl, strength_mult=round(inflow_mult, 2),
                cum_main_net=round(cum, 2), window_main_net=round(window_net, 2),
                pullback_amount=0.0, intraday_change_pct=round(chg, 2),
                big_buy_count=big_buy_count, big_sell_count=big_sell_count,
                big_order_threshold=round(large_thr, 2), last_price=lp, reason=reason,
                is_strong_push=False, is_large_inflow=True,
                window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                window_buy_ratio=round(win_ratio, 4),
                is_hot_candidate=is_hot_candidate,
                market_breadth=round(market_breadth, 4),
                market_universe_size=market_universe_size,
                turnover_rank_percentile=round(turnover_rank, 4),
                inflow_gate_reason=gate_reason,
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
                    window_big_buy=round(win_buy, 2), window_big_sell=round(win_sell, 2),
                    window_buy_ratio=round(win_ratio, 4),
                )
            return None

        # ── 上升（早盘建仓拉升）──
        #   同样过"卖方强度"闸：多空对砸(买500万/卖400万)只是净额偏正，不是主力在扫货。
        at_new_high = cum > 0 and cum >= peak - 1.0    # 创当日累计净流入新高（容 1 元浮点）
        if (inflow_allowed and at_new_high and window_net > 0
                and tier >= 1 and _buy_side_dominant()):
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
