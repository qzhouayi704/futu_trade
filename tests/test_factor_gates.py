#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段2 因子门(_check_factor_gates) 单测。

软门语义: 仅当"非在动票 且 评分不足以越过更高门槛"时拦截，强评分票照常放行；
午后(>=14点)同理抬高门槛。时间用 monkeypatch 固定，保证确定性。
"""
import sys
import types

sys.path.insert(0, ".")
from simple_trade.services.trading.decision import engine as E  # noqa: E402


class _FakeScorer:
    def __init__(self, ind, score):
        self._r = types.SimpleNamespace(indicators=ind, total_score=score)

    def get_score(self, code):
        return self._r


def _make(ind, score):
    eng = E.UnifiedTradeDecisionEngine.__new__(E.UnifiedTradeDecisionEngine)
    eng.container = types.SimpleNamespace(stock_scorer=_FakeScorer(ind, score))
    return eng


class _Clock:
    def __init__(self, hour):
        self.hour = hour

    def now(self):
        return types.SimpleNamespace(hour=self.hour)


def test_factor_gates():
    orig = E.datetime
    E.datetime = _Clock(10)  # 上午
    try:
        # 在动(前日大涨10%) + 低分 → 放行
        assert _make({'prev_day_change': 10.0, 'day_amplitude': 3.0, 'kline_pos_20d': 0.2}, 50)._check_factor_gates("X") == ""
        # 非在动 + 低分 → 日线门拦截
        b = _make({'prev_day_change': 1.0, 'day_amplitude': 3.0, 'kline_pos_20d': 0.2}, 50)._check_factor_gates("X")
        assert b.startswith("[日线门]"), b
        # 非在动 + 高分 → 软门放行
        assert _make({'prev_day_change': 1.0, 'day_amplitude': 3.0, 'kline_pos_20d': 0.2}, 80)._check_factor_gates("X") == ""
        # 今日振幅≥8 视为在动 → 放行
        assert _make({'prev_day_change': 0.0, 'day_amplitude': 9.0, 'kline_pos_20d': 0.1}, 40)._check_factor_gates("X") == ""
        # 日线高位≥0.67 视为在动 → 放行
        assert _make({'prev_day_change': 0.0, 'day_amplitude': 1.0, 'kline_pos_20d': 0.7}, 40)._check_factor_gates("X") == ""

        E.datetime = _Clock(15)  # 午后
        b5 = _make({'prev_day_change': 10.0, 'day_amplitude': 3.0, 'kline_pos_20d': 0.2}, 60)._check_factor_gates("X")
        assert b5.startswith("[午后门]"), b5
        assert _make({'prev_day_change': 10.0, 'day_amplitude': 3.0, 'kline_pos_20d': 0.2}, 80)._check_factor_gates("X") == ""
    finally:
        E.datetime = orig

    # 无评分缓存 → 放行(交由其它门处理)
    eng = E.UnifiedTradeDecisionEngine.__new__(E.UnifiedTradeDecisionEngine)
    eng.container = types.SimpleNamespace(stock_scorer=types.SimpleNamespace(get_score=lambda c: None))
    assert eng._check_factor_gates("X") == ""


if __name__ == "__main__":
    test_factor_gates()
    print("FACTOR_GATE_TESTS_PASS")
