#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit test for SmartPositionManager 'hybrid' exit profile (two-mode exit).

Loads the module by file path (it has no intra-package imports) so the test runs
without importing the whole simple_trade package.
"""
import importlib.util
import os
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_HERE, "..", "simple_trade", "services", "trading", "risk",
                     "smart_position_manager.py")
_spec = importlib.util.spec_from_file_location("spm", _PATH)
spm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spm)

SmartPositionManager = spm.SmartPositionManager


def _feed(mgr, code, prices, t0, step_sec):
    """Feed a price sequence at step_sec intervals; return list of actions."""
    actions = []
    for i, p in enumerate(prices):
        t = t0 + timedelta(seconds=i * step_sec)
        a = mgr.evaluate(code, p, current_time=t)
        actions.append((round(p, 2), a.action, a.qty_to_sell, a.reason))
        if a.action in ("SELL_PARTIAL", "SELL_ALL") and a.qty_to_sell > 0:
            mgr.update_after_sell(code, a.qty_to_sell)
    return actions


def test_spike_partials_then_velocity_runner():
    """脉冲: 快速冲高 → +2%/+4% 分批锁仓, runner 因 3分钟暴力涨速被砍。"""
    mgr = SmartPositionManager()
    t0 = datetime(2026, 6, 17, 10, 0, 0)
    mgr.register_position("HK.TEST1", "脉冲", entry_price=100.0, qty=1000, atr=2.0,
                          entry_time=t0, exit_profile="hybrid")
    # 每 5 秒 +1%: 100→101→102(+2 锁50%)→103→104(+4 锁25%)→105(runner, 3分窗最低~100 → 涨速+5% 砍)
    prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    acts = _feed(mgr, "HK.TEST1", prices, t0, step_sec=5)
    kinds = [a[1] for a in acts]
    assert "SELL_PARTIAL" in kinds, f"应有分批锁仓: {acts}"
    assert kinds[-1] == "SELL_ALL", f"runner 应被速度触发清仓: {acts}"
    # 卖光
    assert mgr.get_position("HK.TEST1").remaining_qty == 0, "应已清仓"
    print("PASS spike:", [(a[0], a[1], a[2]) for a in acts])


def test_grind_partials_then_runner_holds():
    """趋势: 缓慢爬升 → 分批锁仓后 runner 因涨速温和而持有(不被砍)。"""
    mgr = SmartPositionManager()
    t0 = datetime(2026, 6, 17, 10, 0, 0)
    mgr.register_position("HK.TEST2", "趋势", entry_price=100.0, qty=1000, atr=2.0,
                          entry_time=t0, exit_profile="hybrid")
    # 每 60 秒 +0.5%: 慢慢爬到 +4% 之后, 3分钟(180s)窗内只含最近~3-4个点(涨幅~1.5%)→涨速<4%→持有
    prices = [100.0 + 0.5 * i for i in range(0, 12)]  # 100 ... 105.5
    acts = _feed(mgr, "HK.TEST2", prices, t0, step_sec=60)
    kinds = [a[1] for a in acts]
    assert "SELL_PARTIAL" in kinds, f"应有分批锁仓: {acts}"
    # runner 阶段后应有 HOLD（未被速度触发清仓）
    pos = mgr.get_position("HK.TEST2")
    assert pos.remaining_qty > 0, f"runner 应仍持有(慢拉不砍): 剩余={pos.remaining_qty} {acts}"
    assert "SELL_ALL" not in kinds, f"慢拉不应触发速度清仓: {acts}"
    print("PASS grind:", [(a[0], a[1], a[2]) for a in acts])


def test_hard_stop():
    """硬止损: 跌破 -5% 全部卖出。"""
    mgr = SmartPositionManager()
    t0 = datetime(2026, 6, 17, 10, 0, 0)
    mgr.register_position("HK.TEST3", "止损", entry_price=100.0, qty=1000, atr=2.0,
                          entry_time=t0, exit_profile="hybrid")
    prices = [100.0, 99.0, 97.0, 94.5]  # -5.5% 触发
    acts = _feed(mgr, "HK.TEST3", prices, t0, step_sec=5)
    assert acts[-1][1] == "SELL_ALL", f"应硬止损清仓: {acts}"
    assert mgr.get_position("HK.TEST3").remaining_qty == 0
    print("PASS hard_stop:", [(a[0], a[1], a[2]) for a in acts])


def test_standard_profile_unchanged():
    """对照: 默认 'standard' profile 不走 hybrid 分支(+2% 不触发, 因 standard Stage1 是 +3% 且有最小持仓)。"""
    mgr = SmartPositionManager()
    t0 = datetime(2026, 6, 17, 10, 0, 0)
    mgr.register_position("HK.TEST4", "标准", entry_price=100.0, qty=1000, atr=2.0,
                          entry_time=t0)  # 默认 standard
    # +2% 在 standard 下不触发(Stage1=+3%), 且 5 分钟内最小持仓 → HOLD
    a = mgr.evaluate("HK.TEST4", 102.0, current_time=t0 + timedelta(seconds=10))
    assert a.action == "HOLD", f"standard +2% 10秒内应持有: {a.to_dict()}"
    print("PASS standard unchanged:", a.action)


if __name__ == "__main__":
    test_spike_partials_then_velocity_runner()
    test_grind_partials_then_runner_holds()
    test_hard_stop()
    test_standard_profile_unchanged()
    print("\nALL HYBRID EXIT TESTS PASSED")
