"""Synthetic timing, episode lifecycle and walk-forward leakage guards."""
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
import unittest
import numpy as np

from scripts.analysis.minute_entry_study.models import HK, N, build_features
from scripts.analysis.swing_study.legacy.data import event_time, make_episodes, normalize_events
from scripts.analysis.swing_study.legacy.analytics import paired
from scripts.analysis.swing_study.legacy.models import LegacyEvent, Policy, Study
from scripts.analysis.swing_study.legacy.signals import choose, exits, folds, policies, signal_for, training_score
from scripts.analysis.swing_study.models import Market
from tests.v2.test_swing_study import stock


def event(eid: int = 1, index: int = 5, stage: str = 'FIRST', sector: str = '人工智能') -> LegacyEvent:
    return LegacyEvent(eid, 'HK.00100', '2026-07-14', datetime(2026, 7, 14, 9, 30, tzinfo=HK)+timedelta(minutes=index),
                       index, stage, 'RISING', True, 100., 100., 1 if stage == 'FIRST' else 2,
                       sector, 'observe', .8, 1000000, True)


def market() -> Market:
    p = stock(2)
    return Market(['2026-07-14', '2026-07-15'], {p.code: p}, [], 'test', {}, {})


class LegacySwingTests(unittest.TestCase):
    def test_created_time_is_utc_and_later_persistence_defers_event(self):
        original = datetime(2026, 7, 14, 9, 30, 5, tzinfo=HK)
        when, lag = event_time(original.timestamp(), '2026-07-14T09:30:05', '2026-07-14 01:30:20')
        self.assertEqual(when, original+timedelta(seconds=15))
        self.assertEqual(lag, 15)

    def test_second_precision_storage_does_not_shift_earlier(self):
        original = datetime(2026, 7, 14, 9, 30, 5, 900000, tzinfo=HK)
        when, lag = event_time(original.timestamp(), original.isoformat(), '2026-07-14 01:30:05')
        self.assertEqual(when, original)
        self.assertAlmostEqual(lag, -.9)

    def test_disagreeing_epoch_and_iso_is_rejected(self):
        with self.assertRaises(ValueError):
            event_time(event().when.timestamp(), '2026-07-14T01:35:00', '2026-07-14 01:35:00')

    def test_delayed_day_is_not_backdated(self):
        e = event()
        rows = [[1, e.day, e.code, 'capital_trend', 'observe', e.when.isoformat(), '2026-07-15 01:30:00',
                 {'timestamp': e.when.timestamp(), 'last_price': 100}]]
        counts = Counter()
        result, _ = normalize_events(rows, [e.day], counts)
        self.assertEqual(result, [])
        self.assertEqual(counts['delayed_into_another_day'], 1)

    def test_later_theme_never_backfills_unlabeled_first(self):
        counts = Counter()
        result = make_episodes([event(sector=''), event(2, 10, 'CONFIRMED')], market(), counts)
        self.assertEqual(result, [])
        self.assertEqual(counts['themed_confirmation_without_known_first'], 1)

    def test_invalidation_ends_waiting_and_orphan_confirmation(self):
        episodes = make_episodes([event(), event(2, 8, 'INVALIDATED'), event(3, 10, 'CONFIRMED')], market(), Counter())
        self.assertEqual(episodes[0].end_index, 8)
        self.assertIsNone(signal_for(episodes[0], Policy('all', 'formal')))

    def test_strengthening_is_not_historical_confirmation(self):
        episode = make_episodes([event(), event(2, 10, 'STRENGTHENED')], market(), Counter())[0]
        self.assertIsNone(signal_for(episode, Policy('all', 'formal')))

    def test_confirmation_requires_same_anchor(self):
        counts = Counter()
        e = replace(event(2, 10, 'CONFIRMED'), first_price=90)
        episode = make_episodes([event(), e], market(), counts)[0]
        self.assertIsNone(signal_for(episode, Policy('all', 'formal')))
        self.assertEqual(counts['confirmation_anchor_mismatch'], 1)

    def test_same_minute_terminal_prevents_completed_minute_entry(self):
        episode = make_episodes([event(), event(2, 5, 'EXPIRED')], market(), Counter())[0]
        self.assertIsNone(signal_for(episode, Policy('all', 'first')))

    def test_observe_action_does_not_mean_technical_confirmation_absent(self):
        episode = make_episodes([event(), event(2, 10, 'CONFIRMED')], market(), Counter())[0]
        self.assertEqual(signal_for(episode, Policy('all', 'formal')).index, 10)

    def test_adding_later_confirmation_cannot_change_first_entry(self):
        earlier = make_episodes([event()], market(), Counter())[0]
        later = make_episodes([event(), event(2, 10, 'CONFIRMED')], market(), Counter())[0]
        self.assertEqual(signal_for(earlier, Policy('all', 'first')), signal_for(later, Policy('all', 'first')))

    def test_late_confirmation_is_not_mislabeled_never_confirmed(self):
        m = market()
        episodes = make_episodes([event(), event(2, 300, 'CONFIRMED')], m, Counter())
        stats, _ = paired(Study(m, episodes, [], {}, {}, []))
        self.assertEqual(stats['all:1d']['confirmed_outside_entry_window'], 1)
        self.assertEqual(stats['all:1d']['unconfirmed_first_closed'], 0)

    def test_once_confirmation_is_causal_and_needs_observed_window(self):
        m = market()
        p = m.paths['HK.00100']
        p.mean[:20] = np.arange(100., 102., .1)[:20]
        p.high[:20], p.low[:20] = p.mean[:20]+.1, p.mean[:20]-.1
        episode = make_episodes([event()], m, Counter())[0]
        before = signal_for(episode, Policy('all', 'one'))
        self.assertEqual(before.index, 5)
        episode.opportunity.tape.mean[100:] = 500
        build_features(episode.opportunity.tape)
        self.assertEqual(signal_for(episode, Policy('all', 'one')), before)
        episode.end_index = 6
        episode.opportunity.tape.mean[3] = np.nan
        build_features(episode.opportunity.tape)
        self.assertIsNone(signal_for(episode, Policy('all', 'one')))

    def test_horizon_specific_windows_respect_boundaries(self):
        for f in folds():
            for horizon in (1, 3, 5):
                self.assertLessEqual(max(f.train_days(horizon))+horizon-1, f.train_end)
                self.assertLess(f.train_end, f.test_start)
                self.assertLessEqual(max(f.test_days(horizon))+horizon-1, f.test_end)
        self.assertEqual(len(folds()[0].test_days(1)), 10)
        self.assertEqual(len(folds()[0].test_days(5)), 6)

    def test_frozen_grid_and_empty_selection(self):
        self.assertEqual(len(policies('low')+policies('flow'))*len(exits()), 96)
        self.assertIsNone(choose([]))
        self.assertIsNone(choose([{'score': None}]))

    def test_training_eligibility_requires_dates_and_unresolved_limit(self):
        stats = {'closed': 30, 'active_days': 7, 'filled': 30, 'unresolved': 0}
        self.assertIsNone(training_score(stats))
        stats.update(active_days=10, filled=40, unresolved=10)
        self.assertIsNone(training_score(stats))

    def test_selection_does_not_read_test_returns(self):
        a = {'score': .1, 'stats': {'closed': 30}, 'key': 'a', 'test': -100}
        b = {'score': -.1, 'stats': {'closed': 100}, 'key': 'b', 'test': 1000}
        self.assertIs(choose([a, b]), a)


if __name__ == '__main__':
    unittest.main()
