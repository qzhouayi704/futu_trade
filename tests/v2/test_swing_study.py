"""Synthetic minute paths, never live APIs or trading state."""
from dataclasses import replace
import unittest
import numpy as np

from scripts.analysis.minute_entry_study.models import INDEX, N, Tape, build_features
from scripts.analysis.swing_study.data import background,theme_of
from scripts.analysis.swing_study.engine import after,replay,run
from scripts.analysis.swing_study.models import (Background,Daily,EntryRule,ExitRule,FillCosts,
    Market,Opportunity,Signal,StockPath)
from scripts.analysis.swing_study.signals import signal_for,entry_grid,exit_grid


def stock(days: int = 6) -> StockPath:
    p = np.full(N*days,100.)
    bg = Background(True,.02,95,115,99,100,96,100,1000000,True)
    return StockPath('HK.00100',p,p+.1,p-.1,np.full(len(p),100000.),np.full(len(p),100000.),
                     np.full(len(p),20000.),[bg]*days)


def sig(day: int = 0) -> Signal:
    return Signal('HK.00100',day,day*N+5,'AI',.02,100,day*N+5)


class SwingStudyTests(unittest.TestCase):
    def test_grid_is_frozen(self):
        self.assertEqual(len(entry_grid()),18)
        self.assertEqual(len(exit_grid()),24)

    def test_theme_is_explicit_not_all_new_energy(self):
        self.assertEqual(theme_of('光伏'),'光伏')
        self.assertEqual(theme_of('AI医疗'),'AI')
        self.assertIsNone(theme_of('风电'))
        self.assertIsNone(theme_of('新能源物料'))

    def test_daily_features_never_use_same_or_future_date(self):
        rows = [Daily(f'2026-08-{d:02}',100,101,99,10000) for d in range(1,32)]
        first = background(rows,'2026-09-01')
        changed = background(rows+[Daily('2026-09-01',500,900,1,900000)],'2026-09-01')
        self.assertEqual(first,changed)
        self.assertTrue(first.valid)

    def test_daily_conflict_invalidates_used_lookback(self):
        rows = [Daily(f'2026-08-{d:02}',100,101,99,10000,d == 30) for d in range(1,32)]
        self.assertFalse(background(rows,'2026-09-01').valid)

    def test_completed_minute_and_session_boundary(self):
        self.assertEqual(after(5),7)
        self.assertEqual(after(INDEX[719]),INDEX[780])
        self.assertEqual(after(N-1),N)

    def test_flat_three_sessions_charges_costs_and_holds_overnight(self):
        t = replay(stock(),sig(),ExitRule(3),FillCosts(),5)
        self.assertEqual(t.entry,7)
        self.assertEqual(t.exit,2*N+INDEX[951])
        self.assertEqual(t.overnight_count,2)
        self.assertAlmostEqual(t.net,.9995/1.0005*.9985/1.0015-1)

    def test_gap_stop_fills_next_observed_price_not_threshold(self):
        p = stock()
        p.mean[N:],p.high[N:],p.low[N:] = 80,81,79
        t = replay(p,sig(),ExitRule(5),FillCosts(),5)
        self.assertEqual(t.trigger,N)
        self.assertEqual(t.exit,N+2)
        self.assertLess(t.net,-.19)

    def test_stop_target_same_bar_stop_has_precedence(self):
        p = stock()
        p.low[9],p.high[9] = 90,120
        t = replay(p,sig(),ExitRule(),FillCosts(),5)
        self.assertEqual(t.reason,'STOP')
        self.assertEqual(t.exit,11)

    def test_final_clock_exit_does_not_require_quote_at_trigger(self):
        p = stock()
        p.mean[INDEX[949]] = np.nan
        t = replay(p,sig(),ExitRule(1),FillCosts(),5)
        self.assertEqual(t.trigger,INDEX[949])
        self.assertEqual(t.exit,INDEX[951])

    def test_pending_exit_carries_to_next_day(self):
        p = stock()
        p.mean[INDEX[950]:N] = np.nan
        t = replay(p,sig(),ExitRule(1),FillCosts(),5)
        self.assertEqual(t.exit,N)
        self.assertEqual(t.overnight_count,1)
        self.assertEqual(t.reason,'TIME')

    def test_missing_whole_day_is_not_filled_or_ignored(self):
        p = stock()
        p.mean[N:2*N] = np.nan
        t = replay(p,sig(),ExitRule(3),FillCosts(),5)
        self.assertEqual(t.missing_whole_days,1)
        self.assertEqual(t.gap_minutes,N)

    def test_no_forward_history_is_censored_not_zero(self):
        t = replay(stock(2),sig(),ExitRule(5),FillCosts(),1)
        self.assertIsNone(t.net)
        self.assertEqual(t.reason,'RIGHT_CENSORED')

    def test_boundary_does_not_use_later_stop_to_close_training(self):
        p = stock()
        p.low[2*N:] = 80
        t = replay(p,sig(),ExitRule(5),FillCosts(),1)
        self.assertIsNone(t.exit)

    def test_no_entry_capacity_means_no_trade(self):
        p = stock()
        p.volume[:20] = 1
        self.assertIsNone(replay(p,sig(),ExitRule(),FillCosts(),5))

    def test_same_stock_stays_occupied_overnight(self):
        p = stock()
        m = Market([str(d) for d in range(6)],{p.code:p},[],'test',{}, {})
        result = run(m,[sig(0),sig(1),sig(2),sig(3)],ExitRule(3),FillCosts(),list(range(4)),5)
        self.assertEqual(len(result.trades),2)
        self.assertEqual(result.blocked_by_position,2)

    def test_future_minutes_cannot_change_earlier_entry(self):
        p = stock()
        p.mean[5:20] = np.arange(100.1,101.6,.1)[:15]
        bg = p.backgrounds[0]
        t = Tape('2026-09-01',p.code,'test',p.mean[:N],p.high[:N],p.low[:N],p.buy[:N],p.sell[:N],
                 p.volume[:N],5,100,100,95,115,100,())
        build_features(t)
        o = Opportunity(0,'AI','人工智能',t,bg,None,None)
        first = signal_for(o,EntryRule('low'))
        self.assertIsNotNone(first)
        t.mean[100:] = 900
        build_features(t)
        self.assertEqual(signal_for(o,EntryRule('low')),first)

    def test_unfilled_exit_never_frees_same_stock(self):
        p = stock()
        p.volume[N:] = 1
        m = Market([str(d) for d in range(6)],{p.code:p},[],'test',{}, {})
        result = run(m,[sig(0),sig(3)],ExitRule(3),FillCosts(),[0,3],5)
        self.assertEqual(len(result.trades),1)
        self.assertIsNone(result.trades[0].exit)
        self.assertEqual(result.trades[0].reason,'PENDING_EXIT_NO_FILL')
        self.assertEqual(result.blocked_by_position,1)

    def test_trailing_uses_previous_peak_not_same_bar_high(self):
        p = stock()
        p.high[9] = 105
        t = replay(p,sig(),ExitRule(3,1,3,True),FillCosts(),5)
        self.assertEqual(t.trigger,10)
        self.assertEqual(t.reason,'TRAIL')

    def test_slots_and_cash_prevent_sixth_concurrent_ticket(self):
        paths = {}
        candidates = []
        for i in range(6):
            p = stock()
            p.code = f'HK.{i:05}'
            paths[p.code] = p
            candidates.append(replace(sig(),code=p.code))
        m = Market([str(d) for d in range(6)],paths,[],'test',{}, {})
        result = run(m,candidates,ExitRule(3),FillCosts(),[0],5,slots=5)
        self.assertEqual(len(result.trades),5)
        self.assertEqual(result.blocked_by_position,1)

    def test_train_result_unchanged_when_validation_prices_change(self):
        p = stock()
        first = replay(p,sig(),ExitRule(3),FillCosts(),2)
        p.mean[3*N:],p.low[3*N:],p.high[3*N:] = 1000,500,2000
        self.assertEqual(replay(p,sig(),ExitRule(3),FillCosts(),2),first)


if __name__ == '__main__':
    unittest.main()
