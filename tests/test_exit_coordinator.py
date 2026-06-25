#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ExitCoordinator 单测 —— 纯逻辑、无网络、注入假时钟与假交易日。

覆盖：阈值/强度聚合、135×→1 去重、强度升级重推、创日内新高重新武装、冷却到期、
非持仓硬保证、观测过期、CRITICAL 分级、跨日重置、master flag OFF 可逆性。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.trading.intraday.exit_coordinator import (  # noqa: E402
    ExitCoordinator,
    ExitCoordinatorConfig,
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


def _coord(clock, day, **overrides):
    cfg = ExitCoordinatorConfig(enabled=True)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return ExitCoordinator(config=cfg, clock=clock, today_provider=day)


# ---------- 1. 阈值：弱信号不发，强信号发一条 ----------
def test_threshold_weak_vs_strong():
    clock, day = FakeClock(), FakeDay()
    c = _coord(clock, day)
    # 单 R3(22) < 40 → 不发
    c.observe("HK.00100", "R3", price=100.0)
    assert c.decide(["HK.00100"], {"HK.00100": 100.0}) == []
    # 再叠加 R10(40) → 62 ≥ 40 → 发一条
    c.observe("HK.00100", "R10", price=100.0)
    out = c.decide(["HK.00100"], {"HK.00100": 100.0})
    assert len(out) == 1
    assert out[0].stock_code == "HK.00100"
    assert out[0].score == 62
    assert out[0].level == "WARNING"
    assert "量价背离(贴日高量缩)" in out[0].reasons


# ---------- 2. 135×→1：重复观测、价格不变、强度持平 → 只发一次 ----------
def test_dedup_flood_to_one():
    clock, day = FakeClock(), FakeDay()
    c = _coord(clock, day)
    emits = 0
    for _ in range(135):
        clock.advance(5)  # 135×5s=675s，单个 1800s 冷却窗内
        c.observe("HK.00100", "R10", price=100.0)
        c.observe("HK.00100", "R2", price=100.0)  # 60 分，持平、价格不变
        emits += len(c.decide(["HK.00100"], {"HK.00100": 100.0}))
    assert emits == 1, f"同一冷却窗内 135 次重复观测应只发 1 条，实发 {emits}"


# ---------- 3. 强度升级 → 重推 + 升级 CRITICAL ----------
def test_escalation_reemit_and_critical():
    clock, day = FakeClock(), FakeDay()
    c = _coord(clock, day)
    c.observe("HK.00100", "R10", price=100.0)
    c.observe("HK.00100", "R2", price=100.0)              # 40+25=65
    assert len(c.decide(["HK.00100"], {"HK.00100": 100.0})) == 1
    clock.advance(30)
    # 叠加 R13(40) → 40+25+40=105→封顶100，升级 ≥20 → 重推，且 ≥70=CRITICAL
    c.observe("HK.00100", "R10", price=100.0)
    c.observe("HK.00100", "R2", price=100.0)
    c.observe("HK.00100", "R13", price=100.0)
    out = c.decide(["HK.00100"], {"HK.00100": 100.0})
    assert len(out) == 1 and out[0].score == 100 and out[0].level == "CRITICAL"


# ---------- 4. 创日内新高 → 重新武装（治"上午报过、下午拉高不再报"） ----------
def test_rearm_on_new_intraday_high():
    clock, day = FakeClock(), FakeDay()
    c = _coord(clock, day, new_high_pct=0.008)
    c.observe("HK.00100", "R10", price=100.0)
    c.observe("HK.00100", "R2", price=100.0)
    assert len(c.decide(["HK.00100"], {"HK.00100": 100.0})) == 1  # 首发，记 high=100
    # 价格仍持平、强度持平、冷却内 → 不重发
    clock.advance(60)
    c.observe("HK.00100", "R10", price=100.0)
    c.observe("HK.00100", "R2", price=100.0)
    assert c.decide(["HK.00100"], {"HK.00100": 100.0}) == []
    # 拉高到 101 (>100*1.008) → 重新武装
    clock.advance(60)
    c.observe("HK.00100", "R10", price=101.0)
    c.observe("HK.00100", "R2", price=101.0)
    out = c.decide(["HK.00100"], {"HK.00100": 101.0})
    assert len(out) == 1


# ---------- 5. 冷却到期 → 重推 ----------
def test_reemit_after_cooldown():
    clock, day = FakeClock(), FakeDay()
    c = _coord(clock, day, reemit_cooldown=1800, observation_ttl=100000)
    c.observe("HK.00100", "R10", price=100.0)
    c.observe("HK.00100", "R2", price=100.0)
    assert len(c.decide(["HK.00100"], {"HK.00100": 100.0})) == 1
    clock.advance(1801)
    c.observe("HK.00100", "R10", price=100.0)
    c.observe("HK.00100", "R2", price=100.0)
    assert len(c.decide(["HK.00100"], {"HK.00100": 100.0})) == 1


# ---------- 6. 非持仓硬保证：observe 了但 decide 不含该持仓 → 不发且状态清理 ----------
def test_nonheld_never_emits():
    clock, day = FakeClock(), FakeDay()
    c = _coord(clock, day)
    c.observe("HK.09999", "R10", price=50.0)
    c.observe("HK.09999", "R13", price=50.0)   # 65 ≥ 阈值
    # 持仓集合不含 HK.09999 → 不发，且状态被清掉
    assert c.decide(["HK.00700"], {"HK.09999": 50.0, "HK.00700": 1.0}) == []
    assert "HK.09999" not in c._state
    # 即便它后续仍被 observe，只要不在持仓集合就永不发
    c.observe("HK.09999", "R10", price=50.0)
    assert c.decide(["HK.00700"], {}) == []


# ---------- 7. 观测过期：超 TTL 的信号不再计入强度 ----------
def test_observation_ttl_expiry():
    clock, day = FakeClock(), FakeDay()
    c = _coord(clock, day, observation_ttl=240)
    c.observe("HK.00100", "R10", price=100.0)
    c.observe("HK.00100", "R2", price=100.0)
    assert len(c.decide(["HK.00100"], {"HK.00100": 100.0})) == 1
    # 241s 后两条观测都过期 → 强度归零 → 不发（已无离场依据）
    clock.advance(241)
    assert c.decide(["HK.00100"], {"HK.00100": 100.0}) == []


# ---------- 8. 跨日重置 ----------
def test_day_rollover_clears_state():
    clock, day = FakeClock(), FakeDay("2026-06-24")
    c = _coord(clock, day)
    c.observe("HK.00100", "R10", price=100.0)
    c.observe("HK.00100", "R2", price=100.0)
    assert len(c.decide(["HK.00100"], {"HK.00100": 100.0})) == 1
    day.day = "2026-06-25"
    # 跨日后状态清空 → 同样的观测视为全新的一天首发
    c.observe("HK.00100", "R10", price=100.0)
    c.observe("HK.00100", "R2", price=100.0)
    assert len(c.decide(["HK.00100"], {"HK.00100": 100.0})) == 1


# ---------- 9. master flag OFF = 全短路（可逆性） ----------
def test_master_flag_off_is_noop():
    clock, day = FakeClock(), FakeDay()
    cfg = ExitCoordinatorConfig(enabled=False)
    c = ExitCoordinator(config=cfg, clock=clock, today_provider=day)
    assert c.enabled is False
    for _ in range(50):
        c.observe("HK.00100", "R10", price=100.0)
        assert c.decide(["HK.00100"], {"HK.00100": 100.0}) == []
    assert c._state == {}


# ---------- 11. 动量多维共振累加（下跌日无资金流时的离场依据） ----------
def test_momentum_multidimension_accumulates():
    clock, day = FakeClock(), FakeDay()
    c = _coord(clock, day)
    # 单一动量维度(MOM_HIGH=15) < 40 → 不发
    c.observe("HK.00100", "MOM_HIGH:SELL_MOMENTUM", price=100.0)
    assert c.decide(["HK.00100"], {"HK.00100": 100.0}) == []
    # 同维度重复(同子键)只覆盖、不累加 → 仍 15 < 40
    c.observe("HK.00100", "MOM_HIGH:SELL_MOMENTUM", price=100.0)
    assert c.decide(["HK.00100"], {"HK.00100": 100.0}) == []
    # 叠加 3 个不同看空维度 = 45 ≥ 40 → 发（多维共振）
    c.observe("HK.00100", "MOM_HIGH:BEARISH_DIVERGENCE", price=100.0)
    c.observe("HK.00100", "MOM_HIGH:BIG_SELL_CLUSTER", price=100.0)
    out = c.decide(["HK.00100"], {"HK.00100": 100.0})
    assert len(out) == 1 and out[0].score == 45
    # 标签去重：多个动量维度只显示一次"动量派发(强)"
    assert out[0].reasons == ["动量派发(强)"]


# ---------- 10. 信号文本 → tag 提取（message 的 [R10] / reason 的 [OPEN]） ----------
def test_tag_from_text():
    f = ExitCoordinator.tag_from_text
    assert f("🔴 [R10]量价背离: 腾讯(HK.00700) @ 527 — 即时减仓") == "R10"
    assert f("🔴 [R13]日内波段高抛: ...") == "R13"
    assert f("[OPEN] 开盘风险 红灯：低开跌破昨收") == "OPEN"
    assert f("🔴 [R2]高位净流出: 主力净流出2197万(占日均2.2%)") == "R2"
    assert f("🔴 [R3]上涨乏力: ...") == "R3"
    assert f("纯 reason 无规则标记，量价背离") is None


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
