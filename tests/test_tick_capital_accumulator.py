#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TickCapitalAccumulator 单测 —— 纯内存、注入时钟/交易日，覆盖：
阈值分级过滤、全天累计、滚动窗口裁剪、跨日复位、方向归一化、买入占比、动态阈值provider、flag OFF。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.analysis.flow.tick_capital_accumulator import (  # noqa: E402
    TickCapitalAccumulator,
    TickCapitalConfig,
)


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class FakeDay:
    def __init__(self, d="2026-06-24"):
        self.d = d

    def __call__(self):
        return self.d


def _acc(clock, day, **ov):
    cfg = TickCapitalConfig(enabled=True, large_threshold=100_000,
                            super_threshold=1_000_000, window_seconds=900)
    for k, v in ov.items():
        setattr(cfg, k, v)
    return TickCapitalAccumulator(cfg, clock=clock, today_provider=day)


# ---------- 1. 阈值过滤：小单不计入主力 ----------
def test_below_large_threshold_ignored():
    clock, day = FakeClock(), FakeDay()
    a = _acc(clock, day)
    a.on_tick("HK.00700", 50_000, "BUY")     # < 10万，忽略
    assert a.snapshot("HK.00700") is None      # 无任何主力单 → 无状态


# ---------- 2. 大单 vs 超大单 分级 + 全天累计 ----------
def test_super_vs_large_and_cum():
    clock, day = FakeClock(), FakeDay()
    a = _acc(clock, day)
    a.on_tick("HK.00700", 1_500_000, "BUY")   # 超大买
    a.on_tick("HK.00700", 200_000, "BUY")     # 大买
    a.on_tick("HK.00700", 300_000, "SELL")    # 大卖
    s = a.snapshot("HK.00700")
    assert s["super_large_buy"] == 1_500_000
    assert s["large_buy"] == 200_000
    assert s["large_sell"] == 300_000
    # 全天累计主力净 = (1.5M+0.2M) - (0+0.3M) = +1.4M
    assert s["cum_main_net"] == 1_400_000


# ---------- 3. 滚动窗口裁剪（全天累计不受影响） ----------
def test_rolling_window_trims():
    clock, day = FakeClock(), FakeDay()
    a = _acc(clock, day, window_seconds=900)
    a.on_tick("HK.00700", 200_000, "BUY", now=1000)
    a.on_tick("HK.00700", 300_000, "SELL", now=1000)
    s = a.snapshot("HK.00700", now=1000)
    assert s["window_main_net"] == -100_000      # 200k - 300k
    assert s["cum_main_net"] == -100_000
    # 901s 后两笔都滚出窗口 → 滚动归零，但全天累计保留
    s2 = a.snapshot("HK.00700", now=1901)
    assert s2["window_main_net"] == 0
    assert s2["cum_main_net"] == -100_000


# ---------- 4. 买入占比 ----------
def test_big_order_buy_ratio():
    clock, day = FakeClock(), FakeDay()
    a = _acc(clock, day)
    a.on_tick("HK.00700", 600_000, "BUY")
    a.on_tick("HK.00700", 400_000, "SELL")
    s = a.snapshot("HK.00700")
    assert abs(s["big_order_buy_ratio"] - 0.6) < 1e-9   # 600k/(600k+400k)


# ---------- 5. 方向归一化（BULL/BEAR/中性） ----------
def test_direction_normalization():
    clock, day = FakeClock(), FakeDay()
    a = _acc(clock, day)
    a.on_tick("HK.00700", 200_000, "BULL")    # → BUY
    a.on_tick("HK.00700", 100_000, "BEAR")    # → SELL
    a.on_tick("HK.00700", 500_000, "NEUTRAL")  # 中性，忽略
    s = a.snapshot("HK.00700")
    assert s["large_buy"] == 200_000
    assert s["large_sell"] == 100_000
    assert s["cum_main_net"] == 100_000        # 中性单不影响


# ---------- 6. 跨日复位 ----------
def test_cross_day_reset():
    clock, day = FakeClock(), FakeDay("2026-06-24")
    a = _acc(clock, day)
    a.on_tick("HK.00700", 500_000, "BUY")
    assert a.snapshot("HK.00700")["cum_main_net"] == 500_000
    day.d = "2026-06-25"
    # 跨日后该股状态视为过期 → 快照 None，新笔从 0 起累
    assert a.snapshot("HK.00700") is None
    a.on_tick("HK.00700", 300_000, "SELL")
    assert a.snapshot("HK.00700")["cum_main_net"] == -300_000


# ---------- 7. 动态阈值 provider ----------
def test_threshold_provider():
    clock, day = FakeClock(), FakeDay()
    # 腾讯阈值更高：大单≥50万、超大单≥500万
    prov = lambda code: (500_000, 5_000_000) if code == "HK.00700" else None
    cfg = TickCapitalConfig(enabled=True, large_threshold=100_000, super_threshold=1_000_000)
    a = TickCapitalAccumulator(cfg, clock=clock, today_provider=day, threshold_provider=prov)
    a.on_tick("HK.00700", 200_000, "BUY")     # < 50万 → 对腾讯不算大单，忽略
    assert a.snapshot("HK.00700") is None
    a.on_tick("HK.00700", 6_000_000, "BUY")   # ≥ 500万 → 超大单
    s = a.snapshot("HK.00700")
    assert s["super_large_buy"] == 6_000_000
    # 其它股回退固定阈值：20万 ≥ 10万 = 大单
    a.on_tick("HK.00001", 200_000, "BUY")
    assert a.snapshot("HK.00001")["large_buy"] == 200_000


# ---------- 8. master flag OFF = 全短路 ----------
def test_flag_off_noop():
    clock, day = FakeClock(), FakeDay()
    cfg = TickCapitalConfig(enabled=False)
    a = TickCapitalAccumulator(cfg, clock=clock, today_provider=day)
    for _ in range(20):
        a.on_tick("HK.00700", 5_000_000, "BUY")
    assert a.snapshot("HK.00700") is None
    assert a.snapshot_all() == {}


# ---------- 9b. 大单计数 + 当日累计峰/谷 ----------
def test_big_counts_and_peak_trough():
    clock, day = FakeClock(), FakeDay()
    a = _acc(clock, day)
    a.on_tick("HK.00700", 500_000, "BUY")     # 大买1 → cum +0.5M, peak 0.5M
    a.on_tick("HK.00700", 300_000, "BUY")     # 大买2 → cum +0.8M, peak 0.8M
    a.on_tick("HK.00700", 1_200_000, "SELL")  # 大卖1(超大) → cum -0.4M, trough -0.4M
    a.on_tick("HK.00700", 60_000, "BUY")      # < 10万，忽略，不计数
    s = a.snapshot("HK.00700")
    assert s["big_buy_count"] == 2
    assert s["big_sell_count"] == 1
    assert s["cum_peak"] == 800_000           # 历史峰值（即便当前已回落）
    assert s["cum_trough"] == -400_000
    assert s["cum_main_net"] == -400_000


# ---------- 10. 序号去重：回放/补发不重复累加（Bug2） ----------
def test_sequence_dedup_blocks_replay():
    clock, day = FakeClock(), FakeDay()
    a = _acc(clock, day)
    a.on_tick("HK.00700", 500_000, "BUY", sequence=5001)   # 计入
    a.on_tick("HK.00700", 300_000, "BUY", sequence=5002)   # 计入
    assert a.snapshot("HK.00700")["cum_main_net"] == 800_000
    # 断线补发/缓存回放：重发序号 ≤ 已计入最大序号 → 跳过，不重复累加
    a.on_tick("HK.00700", 500_000, "BUY", sequence=5001)
    a.on_tick("HK.00700", 300_000, "BUY", sequence=5002)
    s = a.snapshot("HK.00700")
    assert s["cum_main_net"] == 800_000        # 仍是 0.8M，未翻倍
    assert s["big_buy_count"] == 2             # 计数也未被回放抬高
    # 新序号继续正常累加
    a.on_tick("HK.00700", 200_000, "BUY", sequence=5003)
    assert a.snapshot("HK.00700")["cum_main_net"] == 1_000_000


def test_no_sequence_keeps_backward_compat():
    """不传 sequence（None）时退化为不去重，保持旧行为。"""
    clock, day = FakeClock(), FakeDay()
    a = _acc(clock, day)
    a.on_tick("HK.00700", 500_000, "BUY")      # 无序号
    a.on_tick("HK.00700", 500_000, "BUY")      # 无序号 → 照常累加
    assert a.snapshot("HK.00700")["cum_main_net"] == 1_000_000


# ---------- 9. snapshot_all ----------
def test_snapshot_all():
    clock, day = FakeClock(), FakeDay()
    a = _acc(clock, day)
    a.on_tick("HK.00700", 500_000, "BUY")
    a.on_tick("HK.00100", 300_000, "SELL")
    allsnap = a.snapshot_all()
    assert set(allsnap.keys()) == {"HK.00700", "HK.00100"}
    assert allsnap["HK.00700"]["cum_main_net"] == 500_000
    assert allsnap["HK.00100"]["cum_main_net"] == -300_000


# ---------- 11. seed：从持久化快照重建当日状态（治后端重启丢累积） ----------
def _snap(day, **ov):
    base = {
        "stock_code": "HK.00700", "trade_date": day,
        "super_large_buy": 0.0, "super_large_sell": 0.0,
        "large_buy": 0.0, "large_sell": 0.0,
        "cum_peak": 0.0, "cum_trough": 0.0,
        "big_buy_count": 0, "big_sell_count": 0, "last_seq": 0,
    }
    base.update(ov)
    return base


def test_seed_into_empty_restores_state():
    clock, day = FakeClock(), FakeDay()
    a = _acc(clock, day)
    a.seed(_snap(day.d, super_large_buy=1_500_000, large_buy=200_000, large_sell=300_000,
                 cum_peak=2_000_000, cum_trough=-100_000,
                 big_buy_count=2, big_sell_count=1, last_seq=8000))
    s = a.snapshot("HK.00700")
    assert s["cum_main_net"] == 1_400_000      # (1.5M+0.2M)-0.3M
    assert s["cum_peak"] == 2_000_000          # 历史峰值恢复（早盘高点）
    assert s["big_buy_count"] == 2 and s["big_sell_count"] == 1
    assert s["last_seq"] == 8000


def test_seed_sets_last_seq_dedup_blocks_replayed_morning_ticks():
    """seed 后早盘逐笔被回放(seq≤seed.last_seq)应被去重丢弃，不重复累加。"""
    clock, day = FakeClock(), FakeDay()
    a = _acc(clock, day)
    a.seed(_snap(day.d, large_buy=500_000, big_buy_count=1, last_seq=5002))
    # 回放早盘逐笔(序号≤5002) → 跳过
    a.on_tick("HK.00700", 500_000, "BUY", sequence=5001)
    a.on_tick("HK.00700", 300_000, "BUY", sequence=5002)
    assert a.snapshot("HK.00700")["cum_main_net"] == 500_000   # 未翻倍
    # 重启后的新逐笔(序号>5002) 正常续累
    a.on_tick("HK.00700", 200_000, "BUY", sequence=5003)
    assert a.snapshot("HK.00700")["cum_main_net"] == 700_000


def test_seed_merges_with_live_state():
    """竞态：live 推送(SDK线程)已先建状态，seed 增量合并早盘基线、last_seq 取 max。"""
    clock, day = FakeClock(), FakeDay()
    a = _acc(clock, day)
    a.on_tick("HK.00700", 200_000, "BUY", sequence=6000)   # 重启后先到的新逐笔
    a.seed(_snap(day.d, large_buy=500_000, big_buy_count=3, last_seq=5500))  # 早盘基线
    s = a.snapshot("HK.00700")
    assert s["cum_main_net"] == 700_000        # 200k(live) + 500k(seed基线)
    assert s["big_buy_count"] == 4             # 1(live) + 3(seed)
    assert s["last_seq"] == 6000               # max(6000, 5500)


def test_seed_noop_when_disabled_or_empty():
    clock, day = FakeClock(), FakeDay()
    off = TickCapitalAccumulator(TickCapitalConfig(enabled=False), clock=clock, today_provider=day)
    off.seed(_snap(day.d, large_buy=500_000))
    assert off.snapshot_all() == {}
    a = _acc(clock, day)
    a.seed(None)
    a.seed({})
    assert a.snapshot_all() == {}


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
