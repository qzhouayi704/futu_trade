#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PushGovernor 单测 —— 纯逻辑、无网络、注入假时钟与假交易日。

覆盖：全局令牌桶、每股每日上限、CRITICAL 升级节流(治 HK.00100 64×)、折叠摘要、
必看信号豁免、master flag OFF 可逆性。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.alert.push_governor import (  # noqa: E402
    GovernorConfig,
    PushGovernor,
    SEND,
    DROP,
    DIGEST,
)


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs


class FakeDay:
    def __init__(self, day="2026-06-24"):
        self.day = day

    def __call__(self):
        return self.day


def _gov(clock, day, **overrides):
    cfg = GovernorConfig(enabled=True)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return PushGovernor(config=cfg, clock=clock, today_provider=day)


def _flow(gov, category, stock, level, severity=None, price=None):
    """模拟 send() 的决策→记账闭环，返回 verdict。"""
    prio = gov.resolve_priority(level, category, severity, None)
    verdict, _reason = gov.decide(category, stock, prio, level, price)
    if verdict == SEND:
        gov.record_sent(category, stock, prio, level, price)
    elif verdict == DIGEST:
        gov.buffer_digest(category, stock, f"{category}-{stock}")
    return verdict


# ---------- 1. 全局令牌桶 ----------
def test_info_budget_bucket():
    clock, day = FakeClock(), FakeDay()
    gov = _gov(clock, day, info_budget_per_window=8, info_window_seconds=600)
    # 20 只不同股票（避开每股上限），同为低优 INFO 交易信号
    verdicts = [_flow(gov, "交易信号", f"HK.{i:05d}", "INFO") for i in range(20)]
    assert verdicts.count(SEND) == 8, verdicts
    assert verdicts.count(DIGEST) == 12
    # 窗口推进后令牌桶补充
    clock.advance(601)
    assert _flow(gov, "交易信号", "HK.99999", "INFO") == SEND


# ---------- 2. 每股每日上限 + 跨日重置 ----------
def test_per_stock_daily_cap_and_rollover():
    clock, day = FakeClock(), FakeDay("2026-06-24")
    gov = _gov(clock, day)  # 交易信号 cap=2
    v = [_flow(gov, "交易信号", "HK.06871", "INFO") for _ in range(4)]
    assert v == [SEND, SEND, DIGEST, DIGEST], v
    # 另一只股票独立计数
    assert _flow(gov, "交易信号", "HK.00700", "INFO") == SEND
    # 跨日 → 计数清零，HK.06871 又能推
    day.day = "2026-06-25"
    assert _flow(gov, "交易信号", "HK.06871", "INFO") == SEND


# ---------- 3. CRITICAL 升级节流（HK.00100 64× 回归） ----------
def test_critical_escalation_throttle_hk00100():
    clock, day = FakeClock(), FakeDay()
    gov = _gov(clock, day, crit_throttle_seconds=900, crit_escalation_price_pct=0.01)
    # 同股同类 10 条 CRITICAL、价格不变、均在 15min 内
    verdicts = []
    for _ in range(10):
        clock.advance(30)  # 每 30s 一条（远小于 900s 节流窗）
        verdicts.append(_flow(gov, "持仓风险", "HK.00100", "CRITICAL", price=10.0))
    assert verdicts.count(SEND) == 1, verdicts          # 64×→恰 1
    assert verdicts.count(DROP) == 9
    # 价格反向≥1% = 升级 → 放行
    assert _flow(gov, "持仓风险", "HK.00100", "CRITICAL", price=10.2) == SEND
    # 超过节流窗后自然放行
    clock.advance(901)
    assert _flow(gov, "持仓风险", "HK.00100", "CRITICAL", price=10.2) == SEND


# ---------- 4. 折叠摘要 flush 时序 ----------
def test_digest_flush_timing():
    clock, day = FakeClock(), FakeDay()
    gov = _gov(clock, day, digest_flush_seconds=600)
    gov.buffer_digest("交易信号", "HK.00001", "t1")
    gov.buffer_digest("抗跌吸筹", "HK.00002", "t2")
    assert gov.due_digest() is None          # 未到点
    clock.advance(601)
    text = gov.due_digest()
    assert text is not None
    assert "HK.00001" in text and "HK.00002" in text
    assert "2" in text                        # 折叠条数
    # flush 后缓冲清空
    assert gov.due_digest() is None


# ---------- 5. 预算耗尽时必看信号不被饿死 ----------
def test_must_see_not_starved_when_budget_exhausted():
    clock, day = FakeClock(), FakeDay()
    gov = _gov(clock, day, info_budget_per_window=8)
    for i in range(8):                        # 填满低优预算
        _flow(gov, "交易信号", f"HK.{i:05d}", "INFO")
    assert _flow(gov, "交易信号", "HK.55555", "INFO") == DIGEST   # 低优已被挤
    # 早段突破(P90, WARNING) 仍 SEND
    assert _flow(gov, "早段突破", "HK.06651", "WARNING") == SEND
    # 全新持仓风险(P100, CRITICAL) 仍 SEND
    assert _flow(gov, "持仓风险", "HK.00100", "CRITICAL", price=50.0) == SEND
    # 🚀 高强度买点(P60) 豁免预算 → SEND
    assert _flow(gov, "交易信号", "HK.06666", "INFO", severity="high") == SEND


# ---------- 6. master flag OFF = 恒 SEND（可逆性证明） ----------
def test_master_flag_off_is_noop():
    clock, day = FakeClock(), FakeDay()
    cfg = GovernorConfig(enabled=False)       # OFF
    gov = PushGovernor(config=cfg, clock=clock, today_provider=day)
    assert gov.enabled is False
    for _ in range(50):
        v, _r = gov.decide("交易信号", "HK.06871", 10, "INFO")
        assert v == SEND


# ---------- 7. 优先级推导 ----------
def test_resolve_priority():
    clock, day = FakeClock(), FakeDay()
    gov = _gov(clock, day)
    assert gov.resolve_priority("CRITICAL", "持仓风险", None, None) == 100
    assert gov.resolve_priority("WARNING", "早段突破", None, None) == 90
    assert gov.resolve_priority("INFO", "交易信号", None, None) == 10
    assert gov.resolve_priority("INFO", "交易信号", "high", None) == 60   # 🚀提升
    assert gov.resolve_priority("INFO", "交易信号", None, 77) == 77       # 显式覆盖


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
