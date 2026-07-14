#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CapitalTrendDetector 单测 —— 纯内存、注入时钟，覆盖：
上升/回落触发、力度分档、冷却内不重复、档位升级/计数前进/回落加深 re-arm、
日内涨幅、第几次大单、每日上限、跨日复位、flag OFF。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_trade.services.analysis.flow.capital_trend_detector import (  # noqa: E402
    CapitalTrendDetector,
    CapitalTrendConfig,
)


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def _det(clock, **ov):
    cfg = CapitalTrendConfig(enabled=True, strong_mult=2.0, mid_mult=1.0,
                             cooldown_sec=300, pullback_pct=0.15,
                             max_rising_per_day=6, max_falling_per_day=4)
    for k, v in ov.items():
        setattr(cfg, k, v)
    return CapitalTrendDetector(cfg, clock=clock)


# scale=1e6：window_main_net 直接除以 1e6 即力度倍数
TIERS = (2_000_000.0, 6_000_000.0, 1_000_000.0)   # (大单门槛, 超大单, 力度基准)


def _snap(cum=0.0, peak=None, window=0.0, bbc=0, bsc=0,
          code="HK.00100", day="2026-06-24", wbuy=None, wsell=None):
    """wbuy/wsell = 窗口内大单买/卖额。缺省=按净额推成"单边"(买方压倒/卖方压倒)，
    使既有用例只考察量与力度；卖方强度闸另由 wbuy/wsell 显式用例覆盖。"""
    if wbuy is None and wsell is None:
        wbuy = window if window > 0 else 0.0
        wsell = -window if window < 0 else 0.0
    return {
        "stock_code": code, "trade_date": day,
        "cum_main_net": cum, "cum_peak": peak if peak is not None else cum,
        "window_main_net": window, "big_buy_count": bbc, "big_sell_count": bsc,
        "window_big_buy": wbuy or 0.0, "window_big_sell": wsell or 0.0,
    }


# ---------- 1. 上升触发 + 字段 ----------
def test_rising_fires():
    a = _det(FakeClock())
    s = _snap(cum=5_000_000, peak=5_000_000, window=1_500_000, bbc=3)
    al = a.evaluate(s, last_price=110, prev_close=100, tiers=TIERS, stock_name="MINIMAX")
    assert al is not None
    assert al.direction == "RISING"
    assert al.strength_tier == "中"          # mult 1.5 → 中
    assert abs(al.strength_mult - 1.5) < 1e-6
    assert al.big_buy_count == 3
    assert abs(al.intraday_change_pct - 10.0) < 1e-6   # (110-100)/100
    assert "第3次大单买入" in al.reason
    assert al.is_strong_push is False        # 中档不推企微


# ---------- 2. 净流入仅 1.25 倍门槛：够不上"大额流入"(需≥3倍)，退回普通上升 ----------
def test_moderate_inflow_is_not_large_inflow():
    a = _det(FakeClock())
    s = _snap(cum=5_000_000, peak=5_000_000, window=2_500_000, bbc=1)  # 2.5M = 1.25×门槛 2M
    al = a.evaluate(s, 105, 100, TIERS)
    assert al is not None and al.is_large_inflow is False   # 量不够 → 不报大额流入
    assert al.direction == "RISING" and al.strength_tier == "强"


# ---------- 3. 弱档/未创新高 不触发 ----------
def test_no_fire_when_weak_or_not_new_high():
    a = _det(FakeClock())
    # 力度弱（mult 0.5 < mid 1.0）
    assert a.evaluate(_snap(cum=5e6, peak=5e6, window=500_000, bbc=1), 105, 100, TIERS) is None
    # 未创新高（cum < peak），且回落不足
    assert a.evaluate(_snap(cum=4_500_000, peak=5_000_000, window=1_500_000, bbc=1), 105, 100, TIERS) is None


# ---------- 4. 冷却内不重复；冷却后须计数前进 ----------
def test_rising_cooldown_and_count_rearm():
    clk = FakeClock()
    a = _det(clk)
    assert a.evaluate(_snap(cum=5e6, peak=5e6, window=1.5e6, bbc=1), 105, 100, TIERS) is not None
    clk.advance(100)   # 冷却内
    assert a.evaluate(_snap(cum=6e6, peak=6e6, window=1.5e6, bbc=1), 106, 100, TIERS) is None  # 同档同计数
    assert a.evaluate(_snap(cum=6e6, peak=6e6, window=1.5e6, bbc=2), 106, 100, TIERS) is None  # 冷却内即便新大单也不报
    clk.advance(250)   # 累计超 300s 冷却
    assert a.evaluate(_snap(cum=7e6, peak=7e6, window=1.5e6, bbc=2), 107, 100, TIERS) is not None  # 新大单+冷却到 → 报


# ---------- 5. 档位升级可在冷却内再报 ----------
def test_rising_tier_upgrade_breaks_cooldown():
    clk = FakeClock()
    a = _det(clk)
    assert a.evaluate(_snap(cum=5e6, peak=5e6, window=1.5e6, bbc=1), 105, 100, TIERS) is not None  # 中
    clk.advance(50)
    al = a.evaluate(_snap(cum=6e6, peak=6e6, window=2.5e6, bbc=1), 106, 100, TIERS)  # 升强档
    assert al is not None and al.strength_tier == "强"


# ---------- 6. 回落触发 + 字段 ----------
def test_falling_fires():
    a = _det(FakeClock())
    # 峰值 10M，现 6M → 回落 4M ≥ max(门槛2M, peak*0.15=1.5M)；窗口净流出 -1.5M（力度中）
    s = _snap(cum=6_000_000, peak=10_000_000, window=-1_500_000, bsc=5)
    al = a.evaluate(s, last_price=98, prev_close=100, tiers=TIERS, stock_name="MINIMAX")
    assert al is not None and al.direction == "FALLING"
    assert abs(al.pullback_amount - 4_000_000) < 1e-6
    assert al.big_sell_count == 5
    assert "第5次大单流出" in al.reason
    assert al.is_strong_push is True          # 回落一律推企微


# ---------- 7. 回落 re-arm：冷却后须回落加深≥一个门槛 ----------
def test_falling_rearm_deepen():
    clk = FakeClock()
    a = _det(clk)
    assert a.evaluate(_snap(cum=6e6, peak=10e6, window=-1.5e6, bsc=1), 98, 100, TIERS) is not None  # 回落4M
    clk.advance(400)   # 冷却已过
    # 回落 5M：未比上次(4M)加深≥一个门槛(2M) → 不报
    assert a.evaluate(_snap(cum=5e6, peak=10e6, window=-1.5e6, bsc=2), 97, 100, TIERS) is None
    # 回落 6.5M：比上次加深≥2M → 报
    assert a.evaluate(_snap(cum=3.5e6, peak=10e6, window=-1.5e6, bsc=3), 96, 100, TIERS) is not None


# ---------- 8. 纯下跌（价跌+流出，无峰值）不报；拉高出货（价涨+流出）报 ----------
def test_falling_distribution_vs_pure_downtrend():
    a = _det(FakeClock())
    # 价跌 -5% + 主力流出 + 无流入峰值 → 纯弱势，不报（非"拉高出货"）
    assert a.evaluate(_snap(cum=-3e6, peak=0, window=-1.5e6, bsc=2), 95, 100, TIERS) is None
    # 价涨 +2% 但主力大单净流出 -3M（无峰值）→ 拉高出货，报 FALLING
    al = a.evaluate(_snap(cum=-3_000_000, peak=0, window=-1_500_000, bsc=4), 102, 100, TIERS)
    assert al is not None and al.direction == "FALLING"
    assert "拉高出货" in al.reason
    assert al.is_strong_push is True


# ---------- 9. 每日上限 ----------
def test_daily_cap_rising():
    clk = FakeClock()
    a = _det(clk, max_rising_per_day=2)
    fired = 0
    for i in range(1, 6):
        al = a.evaluate(_snap(cum=i * 1e6 + 1e6, peak=i * 1e6 + 1e6, window=1.5e6, bbc=i), 105, 100, TIERS)
        if al:
            fired += 1
        clk.advance(350)   # 每次都过冷却
    assert fired == 2      # 命中每日上限


# ---------- 10. 跨日复位 ----------
def test_cross_day_reset():
    clk = FakeClock()
    a = _det(clk, max_rising_per_day=1)
    assert a.evaluate(_snap(cum=5e6, peak=5e6, window=1.5e6, bbc=1, day="2026-06-24"), 105, 100, TIERS) is not None
    clk.advance(350)
    # 同日已达上限
    assert a.evaluate(_snap(cum=6e6, peak=6e6, window=1.5e6, bbc=2, day="2026-06-24"), 106, 100, TIERS) is None
    # 次日复位 → 又能报
    assert a.evaluate(_snap(cum=5e6, peak=5e6, window=1.5e6, bbc=1, day="2026-06-25"), 105, 100, TIERS) is not None


# ---------- 12. 持仓净流出：讯策 9:49 场景（价平/跌+开盘砸大单+无峰）----------
def test_held_immediate_outflow_fires_on_pure_downtrend():
    a = _det(FakeClock())
    # 窗口净流出 -2M ≥ 大单门槛 2M
    s = _snap(cum=-2_000_000, peak=0, window=-2_000_000, bsc=1)
    # 非持仓：维持旧行为——纯下跌不报（回归 test 8 语义）
    assert a.evaluate(s, 99, 100, TIERS) is None
    # 持仓：净流出提醒必报
    al = a.evaluate(s, 99, 100, TIERS, is_held=True, stock_name="讯策")
    assert al is not None and al.direction == "FALLING"
    assert al.is_held_outflow is True and al.is_strong_push is True
    assert "持仓大单净流出·首次风险" in al.reason and "第1次大单流出" in al.reason


# ---------- 13. 持仓净流出：小额净流出（< 大单门槛）不推 ----------
def test_held_immediate_skips_small_outflow():
    a = _det(FakeClock())
    # 窗口净流出仅 -80万 < 大单门槛 200万 → 小额，不推
    assert a.evaluate(_snap(cum=-800_000, peak=0, window=-800_000, bsc=1),
                      99, 100, TIERS, is_held=True) is None


# ---------- 14. 持仓净流出：1 分钟内不重复，跨分钟攒批（不漏笔数）----------
def test_held_immediate_cooldown_batches_new_sells():
    clk = FakeClock()
    a = _det(clk, held_cooldown_sec=60)
    assert a.evaluate(_snap(cum=-2e6, peak=0, window=-2e6, bsc=1), 99, 100, TIERS, is_held=True) is not None
    clk.advance(20)  # 1 分钟内 → 即便又来大单也不报
    assert a.evaluate(_snap(cum=-2.5e6, peak=0, window=-2.5e6, bsc=3), 98, 100, TIERS, is_held=True) is None
    clk.advance(50)  # 跨过 60s；自上次(第1笔)以来累计新增至第4笔
    al = a.evaluate(_snap(cum=-3e6, peak=0, window=-3e6, bsc=4), 97, 100, TIERS, is_held=True)
    assert al is not None and "新增3笔" in al.reason
    assert al.held_outflow_level == "STRENGTHENED"


# ---------- 15. 持仓净流出：窗口仍净流入（被吸收）不报 ----------
def test_held_immediate_no_fire_when_window_not_outflow():
    a = _det(FakeClock())
    assert a.evaluate(_snap(cum=2e6, peak=2e6, window=500_000, bsc=2), 101, 100, TIERS, is_held=True) is None


# ---------- 16. 持仓净流出：每日上限 ----------
def test_held_immediate_daily_cap():
    clk = FakeClock()
    a = _det(clk, max_held_sell_per_day=2, held_cooldown_sec=0)
    fired = 0
    for i in range(1, 6):
        window = -2e6 * (1.6 ** (i - 1))
        al = a.evaluate(_snap(cum=window, peak=0, window=window, bsc=i), 99, 100, TIERS, is_held=True)
        if al:
            fired += 1
        clk.advance(1)
    assert fired == 2


# ---------- 17. 持仓净流出：未标定(scale=0)也能报（门槛/力度基准回退）----------
def test_held_immediate_works_uncalibrated():
    a = _det(FakeClock())
    al = a.evaluate(_snap(cum=-1e6, peak=0, window=-1e6, bsc=1), 99, 100,
                    tiers=(0.0, 0.0, 0.0), is_held=True)
    assert al is not None and al.is_held_outflow is True


# ---------- 18. 持仓净流出：held_immediate=False 时退化为旧行为 ----------
def test_held_immediate_disabled_falls_back():
    a = _det(FakeClock(), held_immediate=False)
    assert a.evaluate(_snap(cum=-2_000_000, peak=0, window=-2_000_000, bsc=1),
                      99, 100, TIERS, is_held=True) is None


# ---------- 19. 大额主力资金流入：买方压倒 + 量够大 → 报（用户截图样本：大买1334万/大卖135万）----------
def test_large_inflow_fires_when_buy_side_dominant():
    a = _det(FakeClock())
    # 净流入 +1200万 = 6×门槛(2M)；大买1334万 vs 大卖135万 → 买占比 91%
    al = a.evaluate(_snap(cum=12e6, peak=12e6, window=11_990_000, bbc=2,
                          wbuy=13_340_000, wsell=1_350_000), 105, 100, TIERS, stock_name="某股")
    assert al is not None and al.direction == "RISING"
    assert al.is_large_inflow is True and al.is_strong_push is False
    assert al.inflow_stage == "FIRST" and al.inflow_sequence_no == 1
    assert "首次强流入" in al.reason and "第2次大单买入" in al.reason
    assert "买占比91%" in al.reason           # 文案摊开买卖强度
    assert al.window_big_buy == 13_340_000 and al.window_big_sell == 1_350_000


def test_large_inflow_requires_hot_market_context_when_supplied():
    a = _det(FakeClock())
    snap = _snap(cum=12e6, peak=12e6, window=11_990_000, bbc=2,
                 wbuy=13_340_000, wsell=1_350_000)
    blocked = {
        "eligible": False, "is_hot": True, "market_breadth": 0.54,
        "market_universe_size": 100, "turnover_rank_percentile": 1.0,
        "reason": "市场宽度不足",
    }
    assert a.evaluate(snap, 105, 100, TIERS, inflow_context=blocked) is None


def test_large_inflow_carries_hot_market_context():
    a = _det(FakeClock())
    snap = _snap(cum=12e6, peak=12e6, window=11_990_000, bbc=2,
                 wbuy=13_340_000, wsell=1_350_000)
    allowed = {
        "eligible": True, "is_hot": True, "market_breadth": 0.63,
        "market_universe_size": 121, "turnover_rank_percentile": 0.92,
        "reason": "热门股且市场宽度通过",
    }
    alert = a.evaluate(snap, 105, 100, TIERS, inflow_context=allowed)
    assert alert is not None and alert.is_large_inflow
    assert alert.inflow_stage == "FIRST"
    assert alert.is_hot_candidate is True
    assert alert.market_breadth == 0.63
    assert alert.market_universe_size == 121
    assert alert.turnover_rank_percentile == 0.92
    assert "市场宽度63%" in alert.reason


# ---------- 19b. 大额流入：多空对砸（买卖势均力敌）不报——治"55笔买/58笔卖也报流入" ----------
def test_large_inflow_blocked_when_sellers_strong():
    a = _det(FakeClock())
    # 净流入 +600万(=3×门槛，量闸过) 但大买1400万/大卖800万 → 买卖比仅 1.75 < 3.0 → 卖方在抛，不报
    al = a.evaluate(_snap(cum=6e6, peak=6e6, window=6_000_000, bbc=55, bsc=58,
                          wbuy=14_000_000, wsell=8_000_000), 105, 100, TIERS)
    assert al is None or not al.is_large_inflow


# ---------- 19c. 大额流入：力度不够（相对该股自身太弱）不报 ----------
def test_large_inflow_blocked_when_weak_strength():
    a = _det(FakeClock())
    # 净流入 +600万 = 3×门槛(量闸过)、买方压倒(闸过)，但力度基准 1000万 → mult 0.6 < 1.0 → 不报
    tiers_big_scale = (2_000_000.0, 6_000_000.0, 10_000_000.0)
    al = a.evaluate(_snap(cum=6e6, peak=6e6, window=6_000_000, bbc=2,
                          wbuy=6_500_000, wsell=500_000), 105, 100, tiers_big_scale)
    assert al is None or not al.is_large_inflow


# ---------- 20. 大额流入：小额流入（< 大单门槛）不报大额 ----------
def test_large_inflow_skips_small():
    a = _det(FakeClock())
    # 窗口净流入 +1.5M < 门槛 2M；且未创新高 → 大额不报、RISING 也不报
    assert a.evaluate(_snap(cum=4e6, peak=5e6, window=1_500_000, bbc=1), 105, 100, TIERS) is None


def test_normal_market_large_inflow_requires_four_thresholds():
    a = _det(FakeClock())
    alert = a.evaluate(
        _snap(cum=7.9e6, peak=7.9e6, window=7.9e6, bbc=1,
              wbuy=8.5e6, wsell=0.6e6),
        105, 100, TIERS,
    )
    assert alert is None or not alert.is_large_inflow


# ---------- 21. 大额流入：相邻独立确认至少5分钟，且必须有当前新增大单 ----------
def test_large_inflow_cooldown_batches():
    clk = FakeClock()
    a = _det(clk, inflow_cooldown_sec=300)
    a1 = a.evaluate(_snap(cum=8e6, peak=8e6, window=8e6, bbc=1), 105, 100, TIERS)
    assert a1 is not None and a1.inflow_stage == "FIRST"
    clk.advance(20)   # 5分钟内的新大单只标记已看见，不能留到冷却后冒充确认
    a2 = a.evaluate(_snap(cum=8e6, peak=8e6, window=8e6, bbc=3), 106, 100, TIERS)
    assert a2 is None or not a2.is_large_inflow
    clk.advance(280)
    assert a.evaluate(_snap(cum=8e6, peak=8e6, window=8e6, bbc=3), 106, 100, TIERS) is None
    # 冷却到期后必须再来一笔新大单，才构成二次确认。
    a3 = a.evaluate(_snap(cum=9e6, peak=9e6, window=9e6, bbc=4), 107, 100, TIERS)
    assert a3 is not None and a3.inflow_stage == "CONFIRMED"
    assert "本轮新增3笔" in a3.reason


def test_second_inflow_within_15_minutes_confirms_buy_point():
    clk = FakeClock()
    a = _det(clk)
    first = a.evaluate(_snap(cum=8e6, peak=8e6, window=8e6, bbc=1), 100, 100, TIERS)
    assert first is not None and first.inflow_stage == "FIRST"
    clk.advance(300)
    second = a.evaluate(_snap(cum=9e6, peak=9e6, window=9e6, bbc=2), 101, 100, TIERS)
    assert second is not None and second.inflow_stage == "CONFIRMED"
    assert second.inflow_sequence_no == 2
    assert "买点确认/继续持有" in second.reason


def test_first_inflow_expires_without_second_confirmation():
    clk = FakeClock()
    a = _det(clk)
    a.evaluate(_snap(cum=8e6, peak=8e6, window=8e6, bbc=1), 100, 100, TIERS)
    clk.advance(901)
    expired = a.evaluate(_snap(cum=5e6, peak=7e6, window=1e6, bbc=1), 99, 100, TIERS)
    assert expired is not None and expired.is_inflow_expired
    assert expired.inflow_stage == "EXPIRED"
    assert "观察失效" in expired.reason


def test_late_second_inflow_starts_a_new_first_observation():
    clk = FakeClock()
    a = _det(clk)
    a.evaluate(_snap(cum=8e6, peak=8e6, window=8e6, bbc=1), 100, 100, TIERS)
    clk.advance(901)
    restarted = a.evaluate(_snap(cum=9e6, peak=9e6, window=9e6, bbc=2), 101, 100, TIERS)
    assert restarted is not None and restarted.inflow_stage == "FIRST"
    assert restarted.inflow_sequence_no == 1


def test_third_inflow_strengthens_once_without_further_spam():
    clk = FakeClock()
    a = _det(clk, inflow_cooldown_sec=300)
    a.evaluate(_snap(cum=8e6, peak=8e6, window=8e6, bbc=1), 100, 100, TIERS)
    clk.advance(300)
    a.evaluate(_snap(cum=9e6, peak=9e6, window=9e6, bbc=2), 101, 100, TIERS)
    clk.advance(300)
    third = a.evaluate(_snap(cum=11e6, peak=11e6, window=9e6, bbc=3), 102, 100, TIERS)
    assert third is not None and third.inflow_stage == "STRENGTHENED"
    clk.advance(300)
    assert a.evaluate(_snap(cum=13e6, peak=13e6, window=9e6, bbc=4), 103, 100, TIERS) is None


def test_confirmed_inflow_trails_peak_by_1_5_percent():
    clk = FakeClock()
    a = _det(clk, inflow_cooldown_sec=300)
    a.evaluate(_snap(cum=8e6, peak=8e6, window=8e6, bbc=1), 100, 100, TIERS)
    clk.advance(300)
    a.evaluate(_snap(cum=9e6, peak=9e6, window=9e6, bbc=2), 102, 100, TIERS)
    clk.advance(60)
    assert a.evaluate(_snap(cum=9e6, peak=9e6, window=8e6, bbc=2), 104, 100, TIERS) is None
    clk.advance(60)
    trailing = a.evaluate(_snap(cum=8e6, peak=9e6, window=5e6, bbc=2), 102.4, 100, TIERS)
    assert trailing is not None and trailing.is_inflow_trailing_exit
    assert trailing.inflow_stage == "TRAIL_EXIT"
    assert trailing.price_pullback_pct >= 0.015
    assert "止盈提醒" in trailing.reason
    assert trailing.is_profit_exit is True


def test_held_outflow_requires_sell_side_structure():
    a = _det(FakeClock())
    # 净额虽为-200万，但大买800万/大卖1000万，属于对敲而非卖方压倒。
    alert = a.evaluate(
        _snap(cum=-2e6, peak=0, window=-2e6, bsc=2,
              wbuy=8e6, wsell=10e6),
        99, 100, TIERS, is_held=True,
    )
    assert alert is None
    # 即使股价上涨，也不能绕到“拉高出货”通用分支重复报风险。
    rising_alert = a.evaluate(
        _snap(cum=-3e6, peak=0, window=-2e6, bsc=3,
              wbuy=8e6, wsell=10e6),
        102, 100, TIERS, is_held=True,
    )
    assert rising_alert is None


def test_held_outflow_does_not_repeat_until_risk_worsens():
    clk = FakeClock()
    a = _det(clk, held_cooldown_sec=60)
    first = a.evaluate(
        _snap(cum=-2e6, peak=0, window=-2e6, bsc=1),
        100, 100, TIERS, is_held=True,
    )
    assert first is not None
    clk.advance(120)
    assert a.evaluate(
        _snap(cum=-2.5e6, peak=0, window=-2.5e6, bsc=2),
        99.5, 100, TIERS, is_held=True,
    ) is None
    price_break = a.evaluate(
        _snap(cum=-2.5e6, peak=0, window=-2.5e6, bsc=2),
        98.4, 100, TIERS, is_held=True,
    )
    assert price_break is not None
    assert price_break.held_outflow_level == "PRICE_BREAK"


def test_held_outflow_does_not_fall_through_to_generic_retreat():
    clk = FakeClock()
    a = _det(clk, held_cooldown_sec=60)
    first = a.evaluate(
        _snap(cum=6e6, peak=10e6, window=-2e6, bsc=1),
        102, 100, TIERS, is_held=True,
    )
    assert first is not None and first.is_held_outflow
    clk.advance(10)
    repeated = a.evaluate(
        _snap(cum=5e6, peak=10e6, window=-2.5e6, bsc=2),
        101.5, 100, TIERS, is_held=True,
    )
    assert repeated is None


def test_held_outflow_recovery_alerts_once_when_buyers_absorb():
    clk = FakeClock()
    a = _det(clk)
    a.evaluate(
        _snap(cum=-2e6, peak=0, window=-2e6, bsc=1),
        99, 100, TIERS, is_held=True,
    )
    clk.advance(60)
    recovered = a.evaluate(
        _snap(cum=0, peak=0, window=2e6, bbc=1, bsc=1,
              wbuy=3e6, wsell=1e6),
        99.5, 100, TIERS, is_held=True,
    )
    assert recovered is not None and recovered.is_held_outflow_recovery
    assert "流出被承接" in recovered.reason
    clk.advance(60)
    follow_up = a.evaluate(
        _snap(cum=1e6, peak=1e6, window=2e6, bbc=2, bsc=1,
              wbuy=3e6, wsell=1e6),
        100, 100, TIERS, is_held=True,
    )
    assert follow_up is None or not follow_up.is_held_outflow_recovery


def test_extreme_market_requires_three_independent_inflows():
    clk = FakeClock()
    a = _det(clk)
    context = {
        "eligible": True, "is_hot": True, "market_breadth": 0.30,
        "market_universe_size": 100, "turnover_rank_percentile": 0.99,
        "risk_mode": "EXTREME", "plate_name": "半导体",
        "plate_breadth": 0.80, "plate_universe_size": 10,
        "plate_median_change_pct": 1.0, "relative_strength_pct": 3.0,
        "required_confirmations": 3, "reason": "极弱市强板块逆势候选通过",
    }
    first = a.evaluate(
        _snap(cum=11e6, peak=11e6, window=10e6, bbc=1,
              wbuy=12e6, wsell=2e6),
        100, 100, TIERS, inflow_context=context,
    )
    assert first is not None and first.inflow_stage == "FIRST"
    assert first.wechat_suppressed is True
    clk.advance(300)
    second = a.evaluate(
        _snap(cum=21e6, peak=21e6, window=10e6, bbc=2,
              wbuy=12e6, wsell=2e6),
        101, 100, TIERS, inflow_context=context,
    )
    assert second is not None and second.inflow_stage == "SECOND_WATCH"
    assert second.wechat_suppressed is True
    clk.advance(300)
    third = a.evaluate(
        _snap(cum=31e6, peak=31e6, window=10e6, bbc=3,
              wbuy=12e6, wsell=2e6),
        102, 100, TIERS, inflow_context=context,
    )
    assert third is not None and third.inflow_stage == "CONFIRMED"
    assert third.inflow_sequence_no == 3
    assert third.wechat_suppressed is False


def test_second_inflow_rejected_when_price_is_below_first_price():
    clk = FakeClock()
    a = _det(clk)
    a.evaluate(_snap(cum=8e6, peak=8e6, window=8e6, bbc=1), 100, 100, TIERS)
    clk.advance(120)
    assert a.evaluate(
        _snap(cum=8e6, peak=8e6, window=0, bbc=1), 100.8, 100, TIERS
    ) is None
    clk.advance(180)
    rejected = a.evaluate(
        _snap(cum=9e6, peak=9e6, window=9e6, bbc=2), 99.9, 100, TIERS
    )
    assert rejected is not None and rejected.inflow_stage == "REJECTED"
    assert rejected.wechat_suppressed is True
    assert "价格确认失败" in rejected.reason


def test_watch_is_invalidated_by_large_outflow_before_confirmation():
    clk = FakeClock()
    a = _det(clk)
    a.evaluate(_snap(cum=8e6, peak=8e6, window=8e6, bbc=1), 100, 100, TIERS)
    clk.advance(60)
    invalidated = a.evaluate(
        _snap(cum=5e6, peak=8e6, window=-2e6, bbc=1, bsc=1),
        99.5, 100, TIERS,
    )
    assert invalidated is not None
    assert invalidated.inflow_stage == "INVALIDATED"
    assert invalidated.wechat_suppressed is True


def test_first_watch_uses_1_5_gain_and_1_percent_trailing_exit():
    clk = FakeClock()
    a = _det(clk)
    a.evaluate(_snap(cum=8e6, peak=8e6, window=8e6, bbc=1), 100, 100, TIERS)
    clk.advance(60)
    assert a.evaluate(
        _snap(cum=8e6, peak=8e6, window=0, bbc=1), 102, 100, TIERS
    ) is None
    clk.advance(60)
    trailing = a.evaluate(
        _snap(cum=8e6, peak=8e6, window=0, bbc=1), 100.9, 100, TIERS
    )
    assert trailing is not None and trailing.is_watch_trailing_exit
    assert trailing.inflow_stage == "WATCH_TRAIL_EXIT"


# ---------- 22. 大额流入：每日上限 ----------
def test_large_inflow_daily_cap():
    clk = FakeClock()
    a = _det(clk, max_inflow_per_day=2, inflow_cooldown_sec=0)
    fired = 0
    for i in range(1, 6):
        al = a.evaluate(_snap(cum=i * 8e6, peak=i * 8e6, window=8e6, bbc=i), 105, 100, TIERS)
        if al and al.is_large_inflow:
            fired += 1
        clk.advance(1)
    assert fired == 2


# ---------- 23. 大额流入：inflow_immediate=False 时不出大额流入 ----------
def test_large_inflow_disabled_falls_back():
    a = _det(FakeClock(), inflow_immediate=False)
    al = a.evaluate(_snap(cum=8e6, peak=8e6, window=8e6, bbc=2), 105, 100, TIERS)
    assert al is None or not al.is_large_inflow


# ---------- 24. 上升分支同样过卖方强度闸：多空对砸不报"主力资金上升" ----------
def test_rising_blocked_when_sellers_strong():
    a = _det(FakeClock())
    # 创新高 + 力度中(1.5×)，但窗口 大买500万/大卖350万 → 买卖比 1.43 < 3.0 → 不报
    assert a.evaluate(_snap(cum=5e6, peak=5e6, window=1_500_000, bbc=3,
                            wbuy=5_000_000, wsell=3_500_000), 105, 100, TIERS) is None


# ---------- 25. 老快照（无窗口买卖分解字段）：卖方强度未知 → 买卖比闸放行，不静默拦截 ----------
def test_legacy_snapshot_without_buy_sell_split_still_works():
    a = _det(FakeClock())
    legacy = {
        "stock_code": "HK.00100", "trade_date": "2026-06-24",
        "cum_main_net": 8e6, "cum_peak": 8e6, "window_main_net": 8e6,
        "big_buy_count": 2, "big_sell_count": 0,
    }
    al = a.evaluate(legacy, 105, 100, TIERS)
    assert al is not None and al.is_large_inflow is True
    assert "买占比" not in al.reason      # 无数据就不编造买卖强度


# ---------- 11. flag OFF = 全短路 ----------
def test_flag_off_noop():
    a = CapitalTrendDetector(CapitalTrendConfig(enabled=False), clock=FakeClock())
    assert a.evaluate(_snap(cum=5e6, peak=5e6, window=2.5e6, bbc=3), 110, 100, TIERS) is None


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
