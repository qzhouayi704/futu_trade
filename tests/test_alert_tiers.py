#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提醒分层单测: IntradaySniper._classify_alert / _pre_jump_pct + SniperSignal.to_dict。

分层依据(6 天逐日验证): 信号前3分钟急涨幅(脉冲接盘判定) + 持续抢筹次数(可持有) + 当日已涨幅(追高)。
"""
import sys

sys.path.insert(0, ".")
from simple_trade.services.sniper.intraday_sniper import IntradaySniper, SniperSignal  # noqa: E402


def test_classify_alert():
    ca = IntradaySniper._classify_alert
    # 安静(<1%急涨) + 持续抢筹 → 可持有
    assert ca(3, 0.7, 0.2)[:2] == ('opportunity', 'trend')
    # 安静 + 单次 → 观察(pulse/watch)
    assert ca(1, 0.3, 0.0)[:2] == ('pulse', 'watch')
    # 信号前已涨 1~6% → 谨慎(pulse/spike), 即便是持续抢筹也降级
    assert ca(3, 0.5, 2.0)[:2] == ('pulse', 'spike')
    assert ca(1, 0.0, 3.0)[:2] == ('pulse', 'spike')
    # 信号前急涨≥6% → 急涨别碰(reference/chase)
    assert ca(2, 1.0, 8.0)[:2] == ('reference', 'chase')
    assert ca(1, 0.0, 6.0)[0] == 'reference'  # 6% 含进别碰
    # 当日已涨≥12% → 别碰(追高), 不论急涨
    assert ca(5, 13.0, 0.0)[:2] == ('reference', 'chase')


def test_pre_jump_pct():
    pj = IntradaySniper._pre_jump_pct
    # 时间线每分钟一条; idx=4(10:04) 价 110, 3分钟前(10:01)价 100 → +10%
    tl = [
        {'time': '10:00', 'price': 100.0},
        {'time': '10:01', 'price': 100.0},
        {'time': '10:02', 'price': 102.0},
        {'time': '10:03', 'price': 105.0},
        {'time': '10:04', 'price': 110.0},
    ]
    assert pj(tl, 4, 3) == 10.0  # 110 vs 10:01 的 100
    # 历史不足3分钟(开盘附近) → 0
    assert pj(tl, 1, 3) == 0.0
    # 含空分钟(跳过 10:02/10:03), 仍按 time 回看
    tl2 = [
        {'time': '10:00', 'price': 100.0},
        {'time': '10:04', 'price': 103.0},
    ]
    assert pj(tl2, 1, 3) == 3.0


def test_to_dict_carries_tier():
    sig = SniperSignal(
        time='10:00', stock_code='HK.X', stock_name='测', signal_type='mega_buy',
        is_red=False, price=10.0, detail='d', action='a',
        tier='opportunity', mode='trend', buy_count=3, intraday_gain=0.7,
        pre_jump3=0.2, posture='可持有',
    )
    d = sig.to_dict()
    assert d['tier'] == 'opportunity' and d['buy_count'] == 3 and d['pre_jump3'] == 0.2
    plain = SniperSignal(time='10:00', stock_code='HK.Y', stock_name='普', signal_type='mega_sell',
                         is_red=True, price=5.0, detail='d', action='a')
    assert 'tier' not in plain.to_dict()


if __name__ == "__main__":
    test_classify_alert()
    test_pre_jump_pct()
    test_to_dict_carries_tier()
    print("ALERT_TIER_TESTS_PASS")
