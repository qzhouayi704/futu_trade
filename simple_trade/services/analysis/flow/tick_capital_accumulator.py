#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐笔主力资金累加器（TickCapitalAccumulator，推送驱动）

挂在 TICKER 推送链（ticker_push_handler）上**逐笔实时累加**主力资金，产出两种口径：
① **全天累计主力净流入**：从开盘累加，不被 `get_rt_ticker` 最近 500 笔上限截断
   （旧 daily_order_accumulator 是 500 笔覆盖快照、不准——本累加器治此）。
② **滚动窗口**：最近 N 分钟大单净额，供盘中实时离场/动量判断。

主力 = 超大单 + 大单，按**单笔成交额**阈值分级（默认固定，可注入动态阈值 provider）。
推送每笔只消费一次 → 天然增量、不漏、无需序号去重（绕开 ticker_data 无唯一序号问题）。

设计取舍：
- 纯内存、线程安全（单锁）——推送回调在富途 SDK 线程，快照可能被管道线程读，故加锁。
- on_tick 为热路径：阈值过滤 + O(1) 摊还窗口裁剪，不查 DB、不做重活。
- 可注入时钟/交易日 → 便于单测；跨日自动复位。
- master flag(`enabled`) 默认 False：on_tick/snapshot 全短路，零开销、可逆。

置 `CAPITAL_TICK_ACCUMULATOR_ENABLED` 环境变量为 1/true 才启用。
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, Optional, Tuple


def _norm_dir(direction) -> Optional[str]:
    """富途逐笔方向归一化为 BUY/SELL；中性单(无主动方)不计入主力。"""
    d = str(direction or "").upper()
    if d in ("BUY", "BULL"):
        return "BUY"
    if d in ("SELL", "BEAR"):
        return "SELL"
    return None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _default_today() -> str:
    try:
        from ....utils.market_helper import MarketTimeHelper
        return MarketTimeHelper.get_market_today("HK")
    except Exception:
        return time.strftime("%Y-%m-%d", time.localtime())


@dataclass
class TickCapitalConfig:
    enabled: bool = False
    large_threshold: float = 100_000.0      # 单笔成交额 ≥ 此值 = 大单
    super_threshold: float = 1_000_000.0     # ≥ 此值 = 超大单
    window_seconds: int = 900                # 滚动窗口 15min

    @classmethod
    def from_env(cls) -> "TickCapitalConfig":
        from ....utils import env_flag
        enabled = env_flag("CAPITAL_TICK_ACCUMULATOR_ENABLED")
        cfg = cls(enabled=enabled)
        cfg.window_seconds = _env_int("CAPITAL_TICK_WINDOW_SEC", cfg.window_seconds)
        return cfg


@dataclass
class _DayState:
    date: str
    super_buy: float = 0.0
    super_sell: float = 0.0
    large_buy: float = 0.0
    large_sell: float = 0.0
    big_buy_count: int = 0       # 当日大单买入笔数(第几次大单买入)
    big_sell_count: int = 0      # 当日大单流出笔数(第几次大单流出)
    cum_peak: float = 0.0        # 当日累计主力净流入峰值(从0开盘)
    cum_trough: float = 0.0      # 当日累计主力净流入谷值
    seen_keys: set = field(default_factory=set)  # 已计入业务键(成交时间,价,量,向)去重，与 ticker_data 一致
    window: Deque[Tuple[float, float]] = field(default_factory=deque)  # (ts, signed_amt)

    @property
    def cum_main_net(self) -> float:
        return (self.super_buy + self.large_buy) - (self.super_sell + self.large_sell)

    @property
    def big_buy(self) -> float:
        return self.super_buy + self.large_buy

    @property
    def big_sell(self) -> float:
        return self.super_sell + self.large_sell


class TickCapitalAccumulator:
    """逐笔主力资金累加器。线程假设：on_tick(推送线程) 与 snapshot(管道线程) 并发，单锁保护。"""

    def __init__(
        self,
        config: Optional[TickCapitalConfig] = None,
        clock: Callable[[], float] = time.time,
        today_provider: Callable[[], str] = _default_today,
        threshold_provider: Optional[Callable[[str], Optional[Tuple[float, float]]]] = None,
    ):
        self.cfg = config or TickCapitalConfig()
        self._clock = clock
        self._today = today_provider
        # provider(code) -> (large_threshold, super_threshold) 或 None（回退固定阈值）
        self._thr_provider = threshold_provider
        self._lock = threading.Lock()
        self._state: Dict[str, _DayState] = {}

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

    def _thresholds(self, code: str) -> Tuple[float, float]:
        if self._thr_provider is not None:
            try:
                t = self._thr_provider(code)
                if t and t[0] > 0:
                    large = float(t[0])
                    return large, max(float(t[1]), large)
            except Exception:
                pass
        return self.cfg.large_threshold, self.cfg.super_threshold

    def on_tick(self, code: str, turnover: float, direction,
                now: Optional[float] = None, trade_time=None,
                price=None, volume=None) -> None:
        """累加一笔逐笔成交。非大单/中性单直接忽略（热路径，先过滤再加锁）。

        业务键去重（与 ticker_data 去重口径一致）：同一笔成交按 (成交时间, 价, 量, 方向)
        只计一次，挡住断线补发(BYDISCONN)/订阅缓存回放(CACHE) 的重复累加。trade_time/price/
        volume 任一缺失则退化为不去重（避免误杀；正常推送均带这三项）。
        """
        if not self.cfg.enabled or not code:
            return
        d = _norm_dir(direction)
        if d is None:
            return
        try:
            amt = float(turnover)
        except (TypeError, ValueError):
            return
        large_thr, super_thr = self._thresholds(code)
        if amt < large_thr:
            return  # 非大单，不计入主力
        # 业务键（仅大单进入此处，集合规模小）
        key = None
        if trade_time and price is not None and volume is not None:
            try:
                key = (str(trade_time), float(price), int(volume), d)
            except (TypeError, ValueError):
                key = None
        now = self._clock() if now is None else now
        today = self._today()
        is_super = amt >= super_thr
        signed = amt if d == "BUY" else -amt
        cutoff = now - self.cfg.window_seconds
        with self._lock:
            st = self._state.get(code)
            if st is None or st.date != today:
                st = _DayState(date=today)
                self._state[code] = st
            # 业务键去重：已计入过的同笔成交（回放/补发）直接跳过，避免重复累加
            if key is not None:
                if key in st.seen_keys:
                    return
                st.seen_keys.add(key)
            if d == "BUY":
                if is_super:
                    st.super_buy += amt
                else:
                    st.large_buy += amt
                st.big_buy_count += 1
            else:
                if is_super:
                    st.super_sell += amt
                else:
                    st.large_sell += amt
                st.big_sell_count += 1
            # O(1) 更新当日累计净流入峰/谷（供 detector 判回落幅度）
            cur = st.cum_main_net
            if cur > st.cum_peak:
                st.cum_peak = cur
            elif cur < st.cum_trough:
                st.cum_trough = cur
            st.window.append((now, signed))
            # O(1) 摊还裁剪：丢弃滚动窗口外的旧笔
            while st.window and st.window[0][0] < cutoff:
                st.window.popleft()

    def snapshot(self, code: str, now: Optional[float] = None) -> Optional[dict]:
        """返回该股当前 tick 口径快照；无数据或已跨日(未刷新)返回 None。"""
        if not self.cfg.enabled:
            return None
        now = self._clock() if now is None else now
        today = self._today()
        cutoff = now - self.cfg.window_seconds
        with self._lock:
            st = self._state.get(code)
            if st is None or st.date != today:
                return None
            while st.window and st.window[0][0] < cutoff:
                st.window.popleft()
            window_net = sum(a for _, a in st.window)
            big_buy, big_sell = st.big_buy, st.big_sell
            ratio = big_buy / (big_buy + big_sell) if (big_buy + big_sell) > 0 else 0.0
            return {
                "stock_code": code,
                "trade_date": st.date,
                "cum_main_net": round(st.cum_main_net, 2),
                "window_main_net": round(window_net, 2),
                "super_large_buy": round(st.super_buy, 2),
                "super_large_sell": round(st.super_sell, 2),
                "large_buy": round(st.large_buy, 2),
                "large_sell": round(st.large_sell, 2),
                "big_order_buy_ratio": round(ratio, 4),
                "big_buy_count": st.big_buy_count,
                "big_sell_count": st.big_sell_count,
                "cum_peak": round(st.cum_peak, 2),
                "cum_trough": round(st.cum_trough, 2),
                "updated_at": now,
            }

    def seed(self, snap: Optional[dict]) -> None:
        """用持久化快照(tick_capital_flow 最新行)重建某股当日状态——治后端重启内存清空、
        丢当日累积(cum/peak/计数),致看板回退富途口径、capital_trend 回落判读失真。

        竞态安全(on_tick 在 SDK 推送线程并发)：锁内做**增量合并**——把 snap 的当日基线
        加到现有状态上。窗口 deque 不持久化→留给 live 重填(15min 内逐步恢复力度)。

        注：去重改用业务键(成交时间,价,量,向)后，seen_keys 无法廉价持久化，故重启后不再恢复
        去重集——若富途在重连瞬间回放(CACHE)了 seed 基线内已计的逐笔，会有少量重复累加(有界、
        可接受)。正常 live 推送(新成交)与基线不相交，相加正确。

        只应在启动期调用一次(每股一次)；snap 须为当日(跨日的不喂)。
        """
        if not self.cfg.enabled or not snap:
            return
        code = snap.get("stock_code")
        day = snap.get("trade_date")
        if not code or not day:
            return
        with self._lock:
            st = self._state.get(code)
            if st is None or st.date != day:
                st = _DayState(date=day)
                self._state[code] = st
            st.super_buy += float(snap.get("super_large_buy") or 0.0)
            st.super_sell += float(snap.get("super_large_sell") or 0.0)
            st.large_buy += float(snap.get("large_buy") or 0.0)
            st.large_sell += float(snap.get("large_sell") or 0.0)
            st.big_buy_count += int(snap.get("big_buy_count") or 0)
            st.big_sell_count += int(snap.get("big_sell_count") or 0)
            # 峰/谷：取基线峰谷与合并后当日累计的极值（近似，足够 detector 判回落幅度）
            cur = st.cum_main_net
            st.cum_peak = max(float(snap.get("cum_peak") or 0.0), st.cum_peak, cur)
            st.cum_trough = min(float(snap.get("cum_trough") or 0.0), st.cum_trough, cur)

    def snapshot_all(self, now: Optional[float] = None) -> Dict[str, dict]:
        with self._lock:
            codes = list(self._state.keys())
        out = {}
        for c in codes:
            snap = self.snapshot(c, now=now)
            if snap is not None:
                out[c] = snap
        return out
