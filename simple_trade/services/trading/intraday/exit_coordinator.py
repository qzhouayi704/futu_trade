#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持仓离场协调器（ExitCoordinator）

把当前各自为政、每分钟重复推送的**持仓卖出传感器**收口成
"每持仓一条、果断、会升级、智能去重/重新武装"的离场判定。

背景：2026-06-23 仅 HK.00100 一只持仓就收到 112 条 `⚠️持仓风险` CRITICAL + 23 条
`⚠️持仓预警` ≈135 条裸告警，全部无差别重复——决断的"该止盈了"淹没在洪流里。
本协调器是这些传感器（资金流 R2/R3/R10/R13、动量 SELL 类、信号仲裁 SELL/STRONG_SELL、
开盘风险）唯一的中心化收口层。

设计取舍（与 `push_governor.py` 同款）：
- 纯逻辑、无 I/O、无网络 → 便于单测（注入假时钟）。
- 单事件循环串行调用，用普通 dict，无锁（**此假设须保持**）。
- master flag(`enabled`) 默认 False：`observe`/`decide` 全短路，对外行为可逆。

**非持仓硬保证**：`decide()` 只对传入的 `held_codes` 产出告警；非持仓状态被丢弃，
故"没有仓位的卖出信号不提醒"在此处成为单点不变量，而非分散在各传感器里碰巧成立。

置 `EXIT_COORDINATOR_ENABLED` 环境变量为 1/true 才启用。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# 各传感器信号 → 撤离强度权重（数字越大越强）。键为 observe() 的 signal_tag。
# 设计：R10/R13/OPEN 是"单条即可离场"的高置信规则(=emit_threshold)，单独就触发；
# R2/R3/R7/RISK/动量 偏弱，需叠加或配合（避免单条弱信号刷屏）。
_SIGNAL_WEIGHTS: Dict[str, int] = {
    # 资金流规则（量价背离/波段高抛/净流出·弱流入 高位派发）
    "R10": 40,           # 最可靠阶段顶部信号(贴日高量缩)，单条即离场
    "R13": 40,           # 日内波段高抛(涨+主力净流出=高位派发)，sell-into-strength，单条即离场
    "R2": 25,
    "R3": 22,
    "R7": 20,
    "OPEN": 40,          # 开盘红灯风险，单条即离场
    "RISK": 30,          # 盘中风控（跌破强支撑/真空区止盈/大单骤降）等无规则 id 的持仓卖出
    # 动量引擎卖出类（按优先级）：单维度分值偏低，靠"多维共振"累加——下跌日资金流高位派发
    # 规则不触发时，动量是唯一离场依据(2026-06-23 HK.00100 全天只有动量在喊)，故按 signal_type
    # 细分子键(observe 传 'MOM_HIGH:<type>')使卖方碾压/看跌背离/大卖单等不同维度可叠加而非互相覆盖。
    "MOM_HIGH": 15,
    "MOM_MEDIUM": 8,
    # 信号仲裁判定
    "ARB_SELL": 15,
    "ARB_STRONG_SELL": 35,
}

# tag → 人类可读短语（用于告警里聚合"为什么"）
_TAG_LABELS: Dict[str, str] = {
    "R10": "量价背离(贴日高量缩)",
    "R13": "日内波段高抛",
    "R2": "高位主力净流出",
    "R3": "上涨乏力·流入不足",
    "R7": "跌破VWAP",
    "OPEN": "开盘风险",
    "RISK": "盘中风控触发",
    "MOM_HIGH": "动量派发(强)",
    "MOM_MEDIUM": "动量转弱",
    "ARB_SELL": "多策略转空",
    "ARB_STRONG_SELL": "多策略强烈看空",
}


def _weight_of(signal_tag: str):
    """tag → 权重。支持 'MOM_HIGH:SELL_MOMENTUM' 子类型形式（取基础键权重，存储仍用完整
    tag 以便不同动量维度并存累加而非互相覆盖）。未知返回 None。"""
    if signal_tag in _SIGNAL_WEIGHTS:
        return _SIGNAL_WEIGHTS[signal_tag]
    return _SIGNAL_WEIGHTS.get(signal_tag.split(":", 1)[0])


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _default_today() -> str:
    """港股自然交易日 YYYY-MM-DD（懒导入避免循环依赖/测试可 stub）。"""
    try:
        from ....utils.market_helper import MarketTimeHelper
        return MarketTimeHelper.get_market_today("HK")
    except Exception:
        return time.strftime("%Y-%m-%d", time.localtime())


@dataclass
class ExitCoordinatorConfig:
    """协调器参数（全部可经环境变量覆盖；改这些不影响 master flag）。"""

    enabled: bool = False              # 主开关；False=完全短路=历史行为
    observation_ttl: int = 240         # 单条观测有效期(秒)，过期不再计入强度
    emit_threshold: int = 40           # 撤离强度≥此值才发离场告警
    critical_threshold: int = 70       # ≥此值升级为 CRITICAL(强烈离场)
    escalate_delta: int = 20           # 较上次推送强度再升≥此值 → 重新推送
    reemit_cooldown: int = 3600        # 强度持平时，至少隔此秒数才重推(1h，治全天派发反复刷)
    new_high_pct: float = 0.008        # 创日内新高≥此比例视为"新的盘中走强" → 重新武装

    @classmethod
    def from_env(cls) -> "ExitCoordinatorConfig":
        raw = os.environ.get("EXIT_COORDINATOR_ENABLED", "")
        enabled = str(raw).strip().lower() in ("1", "true", "yes", "on")
        cfg = cls(enabled=enabled)
        cfg.observation_ttl = _env_int("EXIT_COORD_TTL", cfg.observation_ttl)
        cfg.emit_threshold = _env_int("EXIT_COORD_THRESHOLD", cfg.emit_threshold)
        cfg.reemit_cooldown = _env_int("EXIT_COORD_REEMIT", cfg.reemit_cooldown)
        return cfg


@dataclass
class _PosState:
    """单持仓的离场状态。"""
    # tag -> (points, reason, ts)
    signals: Dict[str, Tuple[int, str, float]] = field(default_factory=dict)
    intraday_high: float = 0.0
    last_emit_ts: float = 0.0
    last_emit_score: int = 0
    last_emit_high: float = 0.0


@dataclass
class ExitDecision:
    """一条待推送的离场告警（协调器只产出结构，渲染/推送交由上层）。"""
    stock_code: str
    score: int
    level: str                 # "CRITICAL" | "WARNING"
    reasons: List[str]         # 聚合后的"为什么"短语（去重，强→弱）
    tags: List[str]            # 命中的 signal_tag（强→弱）
    price: float = 0.0


class ExitCoordinator:
    """中心化持仓离场协调器。线程假设：单事件循环串行调用。"""

    def __init__(
        self,
        config: Optional[ExitCoordinatorConfig] = None,
        clock: Callable[[], float] = time.time,
        today_provider: Callable[[], str] = _default_today,
    ):
        self.cfg = config or ExitCoordinatorConfig()
        self._clock = clock
        self._today = today_provider
        self._market_day: str = self._today()
        self._state: Dict[str, _PosState] = {}

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

    # ---------- 观测 ----------
    def observe(
        self,
        stock_code: str,
        signal_tag: str,
        reason: str = "",
        price: Optional[float] = None,
        now: Optional[float] = None,
    ) -> None:
        """记录一条对持仓的离场观测。signal_tag ∈ _SIGNAL_WEIGHTS。

        非持仓的过滤在 decide() 统一做（单点硬保证），observe 不做持仓判断，
        以便各传感器无脑上报、解耦。未知 tag 直接忽略。
        """
        if not self.cfg.enabled or not stock_code:
            return
        points = _weight_of(signal_tag)
        if points is None:
            return
        now = self._clock() if now is None else now
        self._roll_day(now)
        st = self._state.get(stock_code)
        if st is None:
            st = _PosState()
            self._state[stock_code] = st
        st.signals[signal_tag] = (points, reason or _TAG_LABELS.get(signal_tag, signal_tag), now)
        if price is not None and price > 0:
            st.intraday_high = max(st.intraday_high, float(price))

    @staticmethod
    def tag_from_text(text: str) -> Optional[str]:
        """从信号文本提取规则 tag（R2/R3/R7/R10/R13/OPEN）。

        资金流 action 的 `message` 形如 `🔴 [R10]量价背离: ...`、开盘风险 `reason` 形如
        `[OPEN] 开盘风险 ...`——规则 id 在 message/reason 里，不在纯 reason 文本里。
        多位优先（R13 先于 R3、R10 先于 R2）避免子串误命中。
        """
        if not text:
            return None
        for tag in ("OPEN", "R13", "R10", "R7", "R3", "R2"):
            if tag in text:
                return tag
        return None

    # ---------- 决策 ----------
    def decide(
        self,
        held_codes,
        price_map: Optional[Dict[str, float]] = None,
        now: Optional[float] = None,
    ) -> List[ExitDecision]:
        """对每个持仓产出至多一条离场告警。

        非持仓状态被清理（"没有仓位的卖出信号不提醒"的单点保证）。
        重新推送条件：首次跨阈值 / 强度升级 / 创日内新高(盘中走强) / 冷却到期。
        """
        if not self.cfg.enabled:
            return []
        now = self._clock() if now is None else now
        self._roll_day(now)
        held = set(held_codes or [])
        price_map = price_map or {}

        # 丢弃非持仓状态（含已清仓的）——硬保证
        for code in list(self._state.keys()):
            if code not in held:
                del self._state[code]

        out: List[ExitDecision] = []
        for code in held:
            st = self._state.get(code)
            if st is None:
                continue
            # 更新日内高
            cur_price = float(price_map.get(code) or 0.0)
            if cur_price > 0:
                st.intraday_high = max(st.intraday_high, cur_price)

            score, reasons, tags = self._aggregate(st, now)
            if score < self.cfg.emit_threshold:
                continue
            if not self._should_emit(st, score, now):
                continue

            level = "CRITICAL" if score >= self.cfg.critical_threshold else "WARNING"
            out.append(ExitDecision(
                stock_code=code, score=score, level=level,
                reasons=reasons, tags=tags, price=cur_price,
            ))
            st.last_emit_ts = now
            st.last_emit_score = score
            st.last_emit_high = st.intraday_high
        return out

    # ---------- 内部 ----------
    def _aggregate(self, st: _PosState, now: float) -> Tuple[int, List[str], List[str]]:
        """汇总未过期观测 → (强度0-100, 原因短语[], tags[])，按权重强→弱。"""
        cutoff = now - self.cfg.observation_ttl
        live: List[Tuple[int, str, str]] = []  # (points, tag, reason)
        for tag, (points, reason, ts) in st.signals.items():
            if ts >= cutoff:
                live.append((points, tag, reason))
        if not live:
            return 0, [], []
        live.sort(key=lambda x: x[0], reverse=True)
        score = min(100, sum(p for p, _, _ in live))
        reasons, tags, seen = [], [], set()
        for _p, tag, reason in live:
            tags.append(tag)
            base = tag.split(":", 1)[0]                 # 动量子类型(MOM_HIGH:xxx)归并到基础标签
            label = _TAG_LABELS.get(base, base)
            if label not in seen:
                seen.add(label)
                reasons.append(label)
        return score, reasons, tags

    def _should_emit(self, st: _PosState, score: int, now: float) -> bool:
        if st.last_emit_ts == 0.0:
            return True                                  # 首次跨阈值
        if score - st.last_emit_score >= self.cfg.escalate_delta:
            return True                                  # 强度升级
        if (st.last_emit_high > 0 and st.intraday_high
                >= st.last_emit_high * (1 + self.cfg.new_high_pct)):
            return True                                  # 创日内新高=盘中走强，重新武装
        if now - st.last_emit_ts >= self.cfg.reemit_cooldown:
            return True                                  # 冷却到期
        return False

    def _roll_day(self, now: float) -> None:
        today = self._today()
        if today != self._market_day:
            self._market_day = today
            self._state.clear()
