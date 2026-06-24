#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业微信推送治理器（PushGovernor）

把"全市场每分钟刷数百条企微"的噪声收敛到可用量级。它是 `WeChatAlertService.send()`
唯一的、中心化的决策层——一处覆盖所有通道/所有股票：

- **全局令牌桶**：低优(INFO bulk)推送 ≤ N 条/窗口。
- **每股每日上限**：同一 (类别, 股票) 当日推送上限（默认 交易信号≤2）。
- **CRITICAL 升级节流**：同股同类紧急告警 ≤1/15min，除非价格反向≥1%（治"单只持仓刷 64 条"）。
- **折叠摘要**：被预算/上限挡下的低优信号不硬丢，攒成一条"📊 低优信号摘要"周期补发。
- **优先级豁免**：持仓风险/止损(100)、早段突破(90)、🚀强买(60) 不被预算丢弃——必看信号绝不饿死。

设计取舍：
- 纯逻辑、无 I/O、无网络——便于单测（注入假时钟/假交易日）。
- 运行在单事件循环里被各异步任务调用 → 用普通 dict/deque，无锁（**此假设须保持**）。
- master flag(`enabled`) 默认 False：整条治理路径短路，行为与历史**字节级一致**（可逆）。

置 `WECHAT_GOVERNOR_ENABLED` 环境变量为 1/true 才启用。
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional, Tuple

# 决策结果
SEND = "SEND"
DROP = "DROP"
DIGEST = "DIGEST"

# 类别 → 基础优先级（数字越大越受保护）
_CAT_PRIORITY = {
    "持仓风险": 100,
    "止损": 100,
    "早段突破": 90,
}
_LEVEL_PRIORITY = {"CRITICAL": 100, "WARNING": 50, "INFO": 10}


def _default_today() -> str:
    """港股自然交易日 YYYY-MM-DD（懒导入避免循环依赖/测试可 stub）。"""
    try:
        from ...utils.market_helper import MarketTimeHelper
        return MarketTimeHelper.get_market_today("HK")
    except Exception:
        return time.strftime("%Y-%m-%d", time.localtime())


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
class GovernorConfig:
    """治理器参数（全部可经环境变量覆盖；改这些不影响 master flag）。"""

    enabled: bool = False                 # 主开关；False=完全短路=历史行为
    info_budget_per_window: int = 8       # 低优(INFO bulk) ≤N 条/窗口（全局令牌桶）
    info_window_seconds: int = 600        # 令牌桶窗口 10min
    crit_throttle_seconds: int = 900      # 同股同类 CRITICAL ≤1/15min …
    crit_escalation_price_pct: float = 0.01  # …除非价格反向≥1%（视为升级，放行）
    budget_exempt_priority: int = 60      # 优先级≥此值不受令牌桶丢弃（🚀强买及以上）
    digest_flush_seconds: int = 600       # 折叠摘要至多 10min 出一条
    digest_max_items: int = 30            # 摘要缓冲上限（超出丢最旧）
    daily_cap_per_stock: Dict[str, int] = field(
        default_factory=lambda: {"交易信号": 2, "抗跌吸筹": 2, "大单": 2, "默认": 4}
    )

    @classmethod
    def from_env(cls) -> "GovernorConfig":
        raw = os.environ.get("WECHAT_GOVERNOR_ENABLED", "")
        enabled = str(raw).strip().lower() in ("1", "true", "yes", "on")
        cfg = cls(enabled=enabled)
        cfg.info_budget_per_window = _env_int("WECHAT_GOV_INFO_BUDGET", cfg.info_budget_per_window)
        cfg.info_window_seconds = _env_int("WECHAT_GOV_INFO_WINDOW", cfg.info_window_seconds)
        cfg.crit_throttle_seconds = _env_int("WECHAT_GOV_CRIT_THROTTLE", cfg.crit_throttle_seconds)
        cfg.crit_escalation_price_pct = _env_float(
            "WECHAT_GOV_CRIT_ESCALATION_PCT", cfg.crit_escalation_price_pct
        )
        cfg.digest_flush_seconds = _env_int("WECHAT_GOV_DIGEST_FLUSH", cfg.digest_flush_seconds)
        return cfg


class PushGovernor:
    """中心化推送治理器。线程假设：单事件循环串行调用。"""

    def __init__(
        self,
        config: Optional[GovernorConfig] = None,
        clock: Callable[[], float] = time.time,
        today_provider: Callable[[], str] = _default_today,
    ):
        self.cfg = config or GovernorConfig()
        self._clock = clock
        self._today = today_provider
        self._market_day: str = self._today()
        self._info_events: Deque[float] = deque()                 # 令牌桶时间戳
        self._daily_counts: Dict[Tuple[str, str], int] = {}       # (类别,股票) -> 当日已发
        self._crit_last: Dict[Tuple[str, str], Tuple[float, float]] = {}  # (类别,股票) -> (ts, price)
        self._digest_buffer: List[Tuple[str, str, str]] = []      # (类别, 股票, 标题)
        self._digest_last_flush: float = self._clock()

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

    # ---------- 优先级 ----------
    def resolve_priority(
        self,
        level_name: str,
        category: str,
        severity: Optional[str] = None,
        priority: Optional[int] = None,
    ) -> int:
        if priority is not None:
            base = priority
        elif category in _CAT_PRIORITY:
            base = _CAT_PRIORITY[category]
        else:
            base = _LEVEL_PRIORITY.get(level_name, 10)
        # 🚀 高强度买点提升到豁免线（不被令牌桶丢弃）
        if severity == "high" and base < self.cfg.budget_exempt_priority:
            base = self.cfg.budget_exempt_priority
        return base

    # ---------- 决策 ----------
    def decide(
        self,
        category: str,
        stock_code: Optional[str],
        prio: int,
        level_name: str,
        price: Optional[float] = None,
        now: Optional[float] = None,
    ) -> Tuple[str, str]:
        """返回 (verdict, reason)。verdict ∈ {SEND, DROP, DIGEST}。"""
        if not self.cfg.enabled:
            return (SEND, "governor disabled")
        now = self._clock() if now is None else now
        self._roll_day(now)

        # 必看信号（持仓风险/止损/早段突破）：永远放行，唯一例外是同股 CRITICAL 短期重复
        if prio >= 90:
            if level_name == "CRITICAL" and not self._crit_escalation_ok(category, stock_code, price, now):
                return (DROP, "crit throttled <%ds, not escalated" % self.cfg.crit_throttle_seconds)
            return (SEND, "must-see prio>=90")

        # 每股每日上限：折叠不硬丢
        if stock_code and self._daily_count(category, stock_code) >= self._cap(category):
            return (DIGEST, "daily cap reached")

        # 🚀 强买等豁免预算
        if prio >= self.cfg.budget_exempt_priority:
            return (SEND, "budget-exempt prio>=%d" % self.cfg.budget_exempt_priority)

        # 低优 INFO：全局令牌桶
        if level_name == "INFO" and not self._budget_ok(now):
            return (DIGEST, "over info budget")

        return (SEND, "ok")

    def record_sent(
        self,
        category: str,
        stock_code: Optional[str],
        prio: int,
        level_name: str,
        price: Optional[float] = None,
        now: Optional[float] = None,
    ) -> None:
        """真正发出后调用，更新计数/节流状态。"""
        now = self._clock() if now is None else now
        if prio >= 90 and level_name == "CRITICAL":
            self._crit_last[(category, stock_code or "")] = (now, float(price) if price is not None else 0.0)
        if level_name == "INFO" and prio < self.cfg.budget_exempt_priority:
            self._info_events.append(now)
        if stock_code:
            key = (category, stock_code)
            self._daily_counts[key] = self._daily_counts.get(key, 0) + 1

    # ---------- 折叠摘要 ----------
    def buffer_digest(self, category: str, stock_code: Optional[str], title: str) -> None:
        self._digest_buffer.append((category, stock_code or "", title))
        if len(self._digest_buffer) > self.cfg.digest_max_items:
            self._digest_buffer.pop(0)  # 丢最旧

    def due_digest(self, now: Optional[float] = None) -> Optional[str]:
        """到点且有积压则返回摘要文本并清空缓冲，否则 None。"""
        now = self._clock() if now is None else now
        if not self._digest_buffer:
            return None
        if now - self._digest_last_flush < self.cfg.digest_flush_seconds:
            return None
        text = self._render_digest(now)
        self._digest_buffer = []
        self._digest_last_flush = now
        return text

    def _render_digest(self, now: float) -> str:
        minutes = max(1, int(self.cfg.digest_flush_seconds // 60))
        n = len(self._digest_buffer)
        by_cat: Dict[str, List[str]] = {}
        for cat, stock, _title in self._digest_buffer:
            by_cat.setdefault(cat, []).append(stock or "?")
        lines = [f"- 过去约{minutes}分钟还有 **{n}** 条低优信号被折叠："]
        for cat, stocks in by_cat.items():
            shown = stocks[:8]
            more = len(stocks) - len(shown)
            tail = f" (+{more}更多)" if more > 0 else ""
            lines.append(f"  - [{cat}] {', '.join(shown)}{tail}")
        return "\n".join(lines)

    # ---------- 内部 ----------
    def _roll_day(self, now: float) -> None:
        today = self._today()
        if today != self._market_day:
            self._market_day = today
            self._info_events.clear()
            self._daily_counts.clear()
            self._crit_last.clear()
            # 跨日强制下次 due_digest 立即 flush 残余
            self._digest_last_flush = 0.0

    def _crit_escalation_ok(
        self, category: str, stock_code: Optional[str], price: Optional[float], now: float
    ) -> bool:
        key = (category, stock_code or "")
        last = self._crit_last.get(key)
        if last is None:
            return True
        last_ts, last_price = last
        if now - last_ts >= self.cfg.crit_throttle_seconds:
            return True
        if price is not None and last_price and last_price > 0:
            move = abs(float(price) - last_price) / last_price
            if move >= self.cfg.crit_escalation_price_pct:
                return True
        return False

    def _daily_count(self, category: str, stock_code: str) -> int:
        return self._daily_counts.get((category, stock_code), 0)

    def _cap(self, category: str) -> int:
        caps = self.cfg.daily_cap_per_stock
        return caps.get(category, caps.get("默认", 4))

    def _budget_ok(self, now: float) -> bool:
        cutoff = now - self.cfg.info_window_seconds
        while self._info_events and self._info_events[0] < cutoff:
            self._info_events.popleft()
        return len(self._info_events) < self.cfg.info_budget_per_window
