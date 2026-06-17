#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段1 提醒分层(IntradaySniper._classify_alert + SniperSignal.to_dict) 单测。

分层依据(6 天逐日验证): 持续抢筹次数(当日该股第几次 mega_buy) + 当日已涨幅。
"""
import sys

sys.path.insert(0, ".")
from simple_trade.services.sniper.intraday_sniper import IntradaySniper, SniperSignal  # noqa: E402


def test_classify_alert():
    ca = IntradaySniper._classify_alert
    # 持续抢筹(第3次+) 且 低涨幅 → 机会·趋势型(可持有)
    assert ca(3, 0.7)[:2] == ('opportunity', 'trend')
    assert ca(4, 5.0)[0] == 'opportunity'
    assert ca(3, 8.0)[0] == 'opportunity'  # 上限含 8
    # 第1/2次/孤立 → 脉冲型(快出)
    assert ca(1, 0.3)[:2] == ('pulse', 'spike')
    assert ca(2, 2.0)[0] == 'pulse'
    # 持续抢筹但已涨 8-12% → 降为脉冲(略extended,不进机会)
    assert ca(3, 10.0)[0] == 'pulse'
    # 已涨≥12% → 参考(追高),不论次数
    assert ca(5, 13.0)[:2] == ('reference', 'chase')
    assert ca(1, 15.0)[0] == 'reference'


def test_to_dict_carries_tier():
    sig = SniperSignal(
        time='10:00', stock_code='HK.X', stock_name='测', signal_type='mega_buy',
        is_red=False, price=10.0, detail='d', action='a',
        tier='opportunity', mode='trend', buy_count=3, intraday_gain=0.7, posture='可持有',
    )
    d = sig.to_dict()
    assert d['tier'] == 'opportunity' and d['buy_count'] == 3 and d['mode'] == 'trend'
    # 无 tier 的普通信号不带这些字段
    plain = SniperSignal(time='10:00', stock_code='HK.Y', stock_name='普', signal_type='mega_sell',
                         is_red=True, price=5.0, detail='d', action='a')
    assert 'tier' not in plain.to_dict()


if __name__ == "__main__":
    test_classify_alert()
    test_to_dict_carries_tier()
    print("ALERT_TIER_TESTS_PASS")
