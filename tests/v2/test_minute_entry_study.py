"""Causality and accounting tests for the independent minute study."""
from dataclasses import replace
import gzip
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts.analysis.minute_entry_study.models import (
    Event, Exit, INDEX, N, Rule, Tape, available_index, build_features, rolling_sum, load,
)
from scripts.analysis.minute_entry_study.replay import Costs, next_complete_minute, replay, train_score
from scripts.analysis.minute_entry_study.rules import signal_index


def tape() -> Tape:
    price = np.full(N,100.)
    t = Tape('2026-09-17','HK.00100','test',price,price+.1,price-.1,
             np.full(N,100000.),np.full(N,30000.),np.full(N,100000.),5,100,99,90,120,105,())
    build_features(t)
    t.features['breadth'] = np.full(N,.6)
    return t


class MinuteEntryStudyTests(unittest.TestCase):
    def test_loader_preserves_tiny_mean_rounding_and_only_prior_daily_bars(self):
        data = {'events':[['id','CANDIDATE_ENTERED','HK.00100','2026-09-17T09:35:00+08:00',
                          '2026-09-17T01:35:01+00:00','SETUP','test','v',False,
                          {'quote':{'last_price':22.1,'prev_close':22}},[]]],
                'minutes':[['HK.00100','2026-09-17','09:36',22.100000000000005,22.1,22.1,100000,50000,10000]],
                'daily':[['HK.00100','2026-09-16',22,23,21,10000],
                         ['HK.00100','2026-09-17',100,200,1,10000]],
                'names':{'HK.00100':'test'}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'data.json.gz'
            path.write_bytes(gzip.compress(json.dumps(data).encode()))
            dataset = load(path)
        self.assertEqual(len(dataset.tapes),1)
        self.assertEqual(dataset.tapes[0].prior_high,23)
        self.assertEqual(dataset.tapes[0].prior_low,21)
        self.assertEqual(dataset.tapes[0].mean[6],22.1)

    def test_received_timestamp_controls_availability(self):
        self.assertEqual(available_index('2026-09-17T09:30:00+08:00','2026-09-17T01:35:00+00:00'),5)

    def test_rolling_sum_uses_only_past(self):
        np.testing.assert_equal(rolling_sum(np.array([1.,2.,3.,1000.]),2),[1,3,5,1003])

    def test_no_signal_minute_or_partly_elapsed_minute_fill(self):
        trade = replay(tape(),5,Rule('candidate_immediate'),Exit(hold=5),Costs())
        self.assertEqual(trade.entry,7)
        self.assertEqual(trade.exit,14)

    def test_lunch_does_not_add_sixty_holding_minutes(self):
        self.assertEqual(next_complete_minute(INDEX[719]),INDEX[780])
        trade = replay(tape(),INDEX[718],Rule('candidate_immediate'),Exit(hold=5),Costs())
        self.assertEqual(trade.entry,INDEX[780])
        self.assertEqual(trade.exit,INDEX[787])

    def test_flat_market_loses_fees_and_slippage(self):
        trade = replay(tape(),5,Rule('candidate_immediate'),Exit(hold=5),Costs())
        self.assertAlmostEqual(trade.net,(.9995/1.0005)*(.9985/1.0015)-1)

    def test_missing_minutes_not_filled(self):
        t = tape()
        t.mean[7:12] = np.nan
        self.assertIsNone(replay(t,5,Rule('candidate_immediate'),Exit(),Costs()))

    def test_entry_requires_capacity(self):
        t = tape()
        t.volume[:] = 1
        self.assertIsNone(replay(t,5,Rule('candidate_immediate'),Exit(),Costs()))

    def test_stop_and_target_same_bar_stop_wins_and_exit_later(self):
        t = tape()
        t.low[9],t.high[9] = 95,106
        trade = replay(t,5,Rule('candidate_immediate'),Exit(),Costs())
        self.assertEqual(trade.reason,'STOP')
        self.assertEqual(trade.exit,11)

    def test_no_exit_data_is_unresolved_not_zero_return(self):
        t = tape()
        t.mean[10:] = np.nan
        trade = replay(t,5,Rule('candidate_immediate'),Exit(hold=5),Costs())
        self.assertIsNone(trade.net)
        self.assertEqual(trade.reason,'MISSING_EXIT_DATA')

    def test_future_prices_do_not_change_earlier_signal(self):
        t = tape()
        t.mean[6:15] = np.arange(100.2,102,.2)[:9]
        t.high = t.mean+.05
        t.low = t.mean-.05
        build_features(t)
        t.features['breadth'] = np.full(N,.6)
        rule = Rule('sustained_flow',window=3,ratio=.6,extension=.03)
        first = signal_index(t,rule)
        self.assertIsNotNone(first)
        t.mean[100:] = 500
        build_features(t)
        t.features['breadth'] = np.full(N,.6)
        self.assertEqual(signal_index(t,rule),first)

    def test_formal_baseline_excludes_shadow(self):
        t = tape()
        t.events = (Event('BUY_CONFIRMED',10,100,'CONFIRMED',False,'shadow','v'),)
        self.assertIsNone(signal_index(t,Rule('recorded_confirmed')))
        self.assertEqual(signal_index(t,Rule('recorded_shadow')),10)

    def test_staged_buy_requires_later_confirmation_and_cannot_add_same_bar(self):
        t = tape()
        t.mean[10:] = 100.5
        t.high[10:] = 100.6
        t.low[10:] = 100.4
        t.events = (Event('BUY_CONFIRMED',11,100.5,'CONFIRMED',True,'confirm','v'),)
        trade = replay(t,5,Rule('candidate_immediate',stage_weight=.25),Exit(hold=15),Costs())
        self.assertTrue(trade.added)
        self.assertEqual(trade.weight,1)
        self.assertEqual(trade.exit,24)
        t.events = ()
        unconfirmed = replay(t,5,Rule('candidate_immediate',stage_weight=.25),Exit(hold=15),Costs())
        self.assertFalse(unconfirmed.added)
        self.assertEqual(unconfirmed.weight,.25)

    def test_stop_cannot_retroactively_cancel_add_minute_already_started(self):
        t = tape()
        t.mean[10:] = 100.5
        t.high[10:] = 100.6
        t.low[10:] = 100.4
        t.low[12] = 95
        t.events = (Event('BUY_CONFIRMED',11,100.5,'CONFIRMED',True,'confirm','v'),)
        trade = replay(t,5,Rule('candidate_immediate',stage_weight=.25),Exit(hold=15),Costs())
        self.assertTrue(trade.added)
        self.assertEqual(trade.exit,14)

    def test_small_sample_cannot_win_training_grid(self):
        stats = {'closed':3,'active_days':2,'unresolved':0,'filled':3,'daily_mean_pct':{'a':100,'b':100}}
        self.assertEqual(train_score(stats),-1e9)


if __name__ == '__main__':
    unittest.main()
