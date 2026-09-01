#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持仓做T助手测试：纯触发/护栏函数 + DB roundtrip + 两腿状态机（告警模式虚拟成交）。"""

import os
import sys
import tempfile
import types
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from simple_trade.database.core.db_manager import DatabaseManager
from simple_trade.database.models.schema import DatabaseSchema
from simple_trade.database.queries.t_trade_queries import TTradeQueries
from simple_trade.services.trading.intraday.t_trade_assistant import (
    TTradeAssistant, TConfig, TMode,
    eligible, eval_sell_trigger, eval_buyback_trigger, compute_trim_qty,
    _change_pct, _amplitude_pct, S_SOLD_WAITING, S_COMPLETED, S_EXPIRED,
)


def _mom(direction=0.0, has_bottom=False, lower_support=False):
    m = types.SimpleNamespace()
    m.momentum_direction = direction
    m.has_bottom_pattern = has_bottom
    m.lower_shadow_support = lower_support
    return m


_TMP_DBS = []


def _create_db() -> DatabaseManager:
    # 用临时文件库：连接是线程本地的，:memory: 不能跨连接共享建表
    fd, path = tempfile.mkstemp(suffix='.db', prefix='ttrade_test_')
    os.close(fd)
    _TMP_DBS.append(path)
    db = DatabaseManager(path)
    for ddl in DatabaseSchema.get_all_tables():
        db.execute_update(ddl)
    db.execute_insert("INSERT INTO stocks (code, name, market) VALUES (?,?,?)",
                      ('HK.00100', 'MINIMAX-W', 'HK'))
    return db


def tearDownModule():
    for p in _TMP_DBS:
        for suffix in ('', '-wal', '-shm'):
            try:
                os.remove(p + suffix)
            except OSError:
                pass


# 一个"高位+净流出"的卖腿场景报价
HIGH_OUTFLOW_QUOTE = {
    'code': 'HK.00100', 'last_price': 520.0, 'prev_close': 500.0,
    'high_price': 525.0, 'low_price': 505.0, 'turnover': 5.0e8, 'volume': 1_000_000,
}
OUTFLOW = {'main_net_inflow': -30_000_000, 'net_inflow_ratio': -0.09, 'inflow_change': -5_000_000}
INFLOW = {'main_net_inflow': 20_000_000, 'net_inflow_ratio': 0.05, 'inflow_change': 7_000_000}


class TestPureTriggers(unittest.TestCase):
    def setUp(self):
        self.cfg = TConfig()  # 推荐默认值

    def test_change_and_amplitude(self):
        self.assertAlmostEqual(_change_pct(HIGH_OUTFLOW_QUOTE), 4.0, places=3)
        self.assertAlmostEqual(_amplitude_pct(HIGH_OUTFLOW_QUOTE), 4.0, places=3)

    def test_eligible_requires_volatility_and_liquidity(self):
        ok, _ = eligible(HIGH_OUTFLOW_QUOTE, self.cfg)
        self.assertTrue(ok)
        # 振幅不足
        flat = dict(HIGH_OUTFLOW_QUOTE, high_price=501.0, low_price=500.0)
        self.assertFalse(eligible(flat, self.cfg)[0])
        # 成交额不足
        illiquid = dict(HIGH_OUTFLOW_QUOTE, turnover=1.0e6)
        self.assertFalse(eligible(illiquid, self.cfg)[0])

    def test_sell_trigger_high_plus_outflow(self):
        self.assertIsNotNone(eval_sell_trigger(HIGH_OUTFLOW_QUOTE, OUTFLOW, self.cfg))
        # 高位但资金流入 → 不高抛
        self.assertIsNone(eval_sell_trigger(HIGH_OUTFLOW_QUOTE, INFLOW, self.cfg))
        # 净流出但不在高位（涨幅不足 且 远离日高）→ 不高抛
        low = dict(HIGH_OUTFLOW_QUOTE, last_price=505.0)  # +1%, 离日高525较远
        self.assertIsNone(eval_sell_trigger(low, OUTFLOW, self.cfg))

    def test_sell_trigger_local_high_on_flat_day(self):
        # 用户真实场景：当日没涨2%(523 vs 昨收519 仅+0.8%)，但523是局部日高 + 主力净流出 → 应高抛
        flat_local_high = {
            'code': 'HK.00100', 'last_price': 523.0, 'prev_close': 519.0,
            'high_price': 523.5, 'low_price': 505.0, 'turnover': 5.0e8, 'volume': 1_000_000,
        }
        self.assertLess(_change_pct(flat_local_high), self.cfg.min_high_change_pct)  # 涨幅不足2%
        self.assertIsNotNone(eval_sell_trigger(flat_local_high, OUTFLOW, self.cfg))   # 但逼近日高+净流出→触发

    def test_buyback_trigger_needs_2of3_and_profit_gap(self):
        leg = {'sold_price': 520.0, 'peak_after_sell': 520.0, 'sold_qty': 200}
        quote = dict(HIGH_OUTFLOW_QUOTE, last_price=505.0)  # 回落2.88%
        # 3/3：回落 + 资金回流 + 动量转正
        hit = eval_buyback_trigger(leg, quote, INFLOW, _mom(direction=0.5), self.cfg)
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit[1], 2)
        # 仅1/3（只有回落，无资金、无动量）→ 不买回
        self.assertIsNone(eval_buyback_trigger(leg, quote, None, None, self.cfg))
        # 利润间隔不足：价格仅低0.5%（<1.5%）即便2条件满足也不买
        near = dict(HIGH_OUTFLOW_QUOTE, last_price=517.5)
        leg2 = {'sold_price': 520.0, 'peak_after_sell': 520.0, 'sold_qty': 200}
        self.assertIsNone(eval_buyback_trigger(leg2, near, INFLOW, _mom(direction=0.5), self.cfg))

    def test_compute_trim_qty_respects_core_floor_and_lot(self):
        # 默认 1/4，1000股 → 250 → 整手200
        self.assertEqual(compute_trim_qty(1000, 1000, self.cfg), 200)
        # 底仓下限：原仓只有100股，保留50% → 最多卖50 → 不足一手 → 0
        self.assertEqual(compute_trim_qty(100, 100, self.cfg), 0)
        # 可卖量限制
        self.assertEqual(compute_trim_qty(1000, 100, self.cfg), 100)

    def test_compute_trim_qty_honors_real_lot_size(self):
        # 每手50股：1000股仓位 1/4=250 → 整手250（硬编码100会砍成200）
        self.assertEqual(compute_trim_qty(1000, 1000, self.cfg, lot_size=50), 250)
        # 每手200股：250 → 向下取整到200
        self.assertEqual(compute_trim_qty(1000, 1000, self.cfg, lot_size=200), 200)
        # 每手500股：250不足一手 → 0（不能下非整手单）
        self.assertEqual(compute_trim_qty(1000, 1000, self.cfg, lot_size=500), 0)
        # lot_size 取不到（None/0）时退回 cfg.lot_size=100
        self.assertEqual(compute_trim_qty(1000, 1000, self.cfg, lot_size=None), 200)
        self.assertEqual(compute_trim_qty(1000, 1000, self.cfg, lot_size=0), 200)


class TestQueriesRoundtrip(unittest.TestCase):
    def setUp(self):
        self.db = _create_db()
        self.q = TTradeQueries(self.db)

    def test_create_get_update_counts(self):
        leg_id = self.q.create_leg(
            stock_code='HK.00100', stock_name='MINIMAX-W', trade_date='2026-06-24',
            mode='alert', state=S_SOLD_WAITING, original_qty=1000, sold_qty=200,
            sold_price=520.0, sold_time='10:00:00', sell_reason='测试', peak_after_sell=520.0)
        self.assertGreater(leg_id, 0)
        # stock_id 解析
        leg = self.q.get_leg(leg_id)
        self.assertEqual(leg['stock_id'], 1)
        self.assertEqual(leg['state'], S_SOLD_WAITING)

        opens = self.q.get_open_legs('2026-06-24')
        self.assertEqual(len(opens), 1)

        self.q.update_leg(leg_id, state=S_COMPLETED, bought_price=505.0, realized_pnl=3000.0)
        self.assertEqual(self.q.count_completed_today('HK.00100', '2026-06-24'), 1)
        self.assertEqual(self.q.get_open_legs('2026-06-24'), [])
        self.assertAlmostEqual(self.q.sum_realized_loss_today('2026-06-24'), 3000.0)


class TestStateMachineAlertMode(unittest.TestCase):
    """端到端：告警模式下卖腿(虚拟成交)→买腿(完成+实现盈亏)。"""

    def setUp(self):
        self.db = _create_db()
        self.db.system_queries.set_system_config('t_trade.enabled', 'true')
        self.assistant = TTradeAssistant(db_manager=self.db)
        self.positions = {'HK.00100': {
            'stock_code': 'HK.00100', 'stock_name': 'MINIMAX-W',
            'qty': 1000, 'can_sell_qty': 1000, 'cost_price': 480.0, 'nominal_price': 520.0,
        }}

    def test_disabled_returns_nothing(self):
        self.db.system_queries.set_system_config('t_trade.enabled', 'false')
        acts = self.assistant.evaluate_cycle(
            [HIGH_OUTFLOW_QUOTE], self.positions, {'HK.00100': OUTFLOW}, {},
            now=datetime(2026, 6, 24, 10, 0))
        self.assertEqual(acts, [])

    def test_sell_then_buyback_roundtrip(self):
        # 1) 卖腿：高位+净流出 → SELL 动作，建 SOLD_WAITING 腿（虚拟成交@520）
        sell_acts = self.assistant.evaluate_cycle(
            [HIGH_OUTFLOW_QUOTE], self.positions, {'HK.00100': OUTFLOW}, {},
            now=datetime(2026, 6, 24, 10, 0))
        self.assertEqual(len(sell_acts), 1)
        a = sell_acts[0]
        self.assertEqual(a['signal_type'], 'SELL')
        self.assertEqual(a['source'], 't_trade')
        self.assertEqual(a['t_leg']['trim_qty'], 200)
        legs = TTradeQueries(self.db).list_legs('2026-06-24')
        self.assertEqual(len(legs), 1)
        self.assertEqual(legs[0]['state'], S_SOLD_WAITING)
        self.assertAlmostEqual(legs[0]['sold_price'], 520.0)

        # 2) 买腿：回落+资金转入+动量转正，且过冷却(25min) → BUY，腿 COMPLETED + 实现盈亏
        drop_quote = dict(HIGH_OUTFLOW_QUOTE, last_price=505.0)
        buy_acts = self.assistant.evaluate_cycle(
            [drop_quote], self.positions, {'HK.00100': INFLOW},
            {'HK.00100': _mom(direction=0.5, has_bottom=True)},
            now=datetime(2026, 6, 24, 10, 25))
        self.assertEqual(len(buy_acts), 1)
        b = buy_acts[0]
        self.assertEqual(b['signal_type'], 'BUY')
        self.assertAlmostEqual(b['t_leg']['realized_pnl'], (520.0 - 505.0) * 200)
        legs = TTradeQueries(self.db).list_legs('2026-06-24')
        self.assertEqual(legs[0]['state'], S_COMPLETED)

    def test_time_window_guard_blocks_open(self):
        # 开盘 15min 内不动手
        acts = self.assistant.evaluate_cycle(
            [HIGH_OUTFLOW_QUOTE], self.positions, {'HK.00100': OUTFLOW}, {},
            now=datetime(2026, 6, 24, 9, 40))
        self.assertEqual(acts, [])

    def test_daily_loss_kill_freezes_new_sell(self):
        # 预置一条当日大额亏损的已完成腿 → 触发熔断，新卖腿被冻结
        TTradeQueries(self.db).create_leg(
            stock_code='HK.00100', stock_name='X', trade_date='2026-06-24',
            mode='alert', state=S_COMPLETED, original_qty=1000, sold_qty=200,
            sold_price=500.0)
        TTradeQueries(self.db).update_leg(1, realized_pnl=-9999.0, state=S_COMPLETED)
        acts = self.assistant.evaluate_cycle(
            [HIGH_OUTFLOW_QUOTE], self.positions, {'HK.00100': OUTFLOW}, {},
            now=datetime(2026, 6, 24, 10, 0))
        # 已有完成腿计数也会触发 max_per_day，但核心：不产生新卖腿
        self.assertEqual([x for x in acts if x['signal_type'] == 'SELL'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
