#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""早段突破抢筹判据单测 —— 纯函数 + 06651 实证 fixture，不触 DB/网络。

EARLY_BREAKOUT_ENABLED 默认 OFF；正例测试里临时 patch 模块全局为 True。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simple_trade.services.sniper.intraday_sniper as ism  # noqa: E402
from simple_trade.services.sniper.intraday_sniper import IntradaySniper  # noqa: E402


class Sig:
    def __init__(self, signal_type, time, stock_code="HK.06651",
                 stock_name="五一视界", price=82.07):
        self.signal_type = signal_type
        self.time = time
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.price = price


class _C:
    db_manager = None


def _sniper():
    return IntradaySniper(container=_C())


def _tl(prices):
    return [{"price": p} for p in prices]


# ---------- _crossed_up ----------
def test_crossed_up_true_on_55_to_65():
    series = [(608, 55.76), (613, 65.27)]
    assert IntradaySniper._crossed_up(series, 614, 60.0, 5.0, 12) is True


def test_crossed_up_false_when_flat_above():
    series = [(600, 64.0), (610, 64.0)]  # 都≥60，无向上穿越
    assert IntradaySniper._crossed_up(series, 610, 60.0, 5.0, 12) is False


def test_crossed_up_false_when_cross_outside_lookback():
    series = [(600, 55.0), (601, 65.0)]  # 穿越发生在 601，但 upto=620/lookback=12 → 窗口[608,620]外
    assert IntradaySniper._crossed_up(series, 620, 60.0, 5.0, 12) is False


def test_crossed_up_false_when_slope_too_small():
    series = [(608, 59.0), (613, 60.5)]  # 穿越但涨幅仅 1.5 < 5
    assert IntradaySniper._crossed_up(series, 614, 60.0, 5.0, 12) is False


# ---------- _gain_and_pos_at ----------
def test_gain_and_pos_math():
    gain, pos = IntradaySniper._gain_and_pos_at(_tl([85.0, 80.5, 82.07]))
    assert abs(gain - ((82.07 / 85.0 - 1) * 100)) < 1e-6
    assert abs(pos - ((82.07 - 80.5) / (85.0 - 80.5))) < 1e-6
    # 数据不足
    assert IntradaySniper._gain_and_pos_at(_tl([85.0])) == (None, None)


# ---------- _check_early_breakout (06651 fixture) ----------
def _arm(sniper, series):
    """开启 flag + 注入资金评分序列。"""
    ism.EARLY_BREAKOUT_ENABLED = True
    sniper._capital_score_series = lambda code, today: series


def _disarm():
    ism.EARLY_BREAKOUT_ENABLED = False


def test_early_breakout_hits_on_06651():
    # 06651 实证：10:14 @82.07 accel_in，资金评分 10:08→10:18 由 55.76 上穿 70.93
    sniper = _sniper()
    series = [(608, 55.76), (613, 65.27), (618, 70.93)]
    _arm(sniper, series)
    try:
        sig = Sig("accel_in", "10:14")
        reason = sniper._check_early_breakout(sig, _tl([85.0, 80.5, 82.07]), [sig], "2026-06-24")
        assert reason is not None and "早段" in reason
    finally:
        _disarm()


def test_early_breakout_none_when_flag_off():
    sniper = _sniper()
    sniper._capital_score_series = lambda code, today: [(608, 55.76), (613, 65.27)]
    _disarm()  # flag OFF
    sig = Sig("accel_in", "10:14")
    assert sniper._check_early_breakout(sig, _tl([85.0, 80.5, 82.07]), [sig], "2026-06-24") is None


def test_early_breakout_none_when_already_extended():
    # 已冲高 +9%（追高）→ 早段 cap 拦截
    sniper = _sniper()
    _arm(sniper, [(608, 55.76), (613, 65.27), (618, 70.93)])
    try:
        sig = Sig("accel_in", "10:35", price=92.0)
        # 价从 85 拉到 92.7 = +9% > EB_EARLY_GAIN_CAP(4%)
        assert sniper._check_early_breakout(sig, _tl([85.0, 88.0, 92.7]), [sig], "2026-06-24") is None
    finally:
        _disarm()


def test_early_breakout_none_when_no_score_cross():
    sniper = _sniper()
    _arm(sniper, [(608, 41.0), (613, 44.0)])  # 资金评分没上穿 60
    try:
        sig = Sig("accel_in", "10:14")
        assert sniper._check_early_breakout(sig, _tl([85.0, 80.5, 82.07]), [sig], "2026-06-24") is None
    finally:
        _disarm()


def test_early_breakout_none_for_wrong_signal_type():
    sniper = _sniper()
    _arm(sniper, [(608, 55.76), (613, 65.27), (618, 70.93)])
    try:
        sig = Sig("mega_sell", "10:14")  # 非 accel_in/reversal_bull
        assert sniper._check_early_breakout(sig, _tl([85.0, 80.5, 82.07]), [sig], "2026-06-24") is None
    finally:
        _disarm()


# ---------- _eb_throttle_ok ----------
def test_eb_throttle():
    sniper = _sniper()
    assert sniper._eb_throttle_ok("HK.06651", "10:14") is True   # 首次
    sniper._eb_last["HK.06651"] = "10:14"
    assert sniper._eb_throttle_ok("HK.06651", "10:30") is False  # 16min < 30min 节流
    assert sniper._eb_throttle_ok("HK.06651", "10:50") is True   # 36min ≥ 30min


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
