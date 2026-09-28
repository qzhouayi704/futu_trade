"""Local research plumbing, persistence and causal prefix regressions."""
from dataclasses import replace
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from scripts.analysis.minute_entry_study.models import HK, INDEX, N
from scripts.analysis.swing_study.forward.protocol import freeze
from scripts.analysis.swing_study.forward.runtime.adapter import normalize, replay
from scripts.analysis.swing_study.forward.runtime.collector import Collector, verify_frozen
from scripts.analysis.swing_study.forward.runtime.demo import synthetic_events
from scripts.analysis.swing_study.forward.runtime.models import (
    Config, ContinuityObservation, DailyContextObservation, ExposureObservation,
    MinuteObservation, SignalObservation, decode, encode, protocol_days,
)
from scripts.analysis.swing_study.forward.runtime.store import SQLiteJournal
from scripts.analysis.swing_study.forward.runtime.tracker import continuity, select, transition


def at(day: str, clock: str = '16:30:00') -> datetime:
    return datetime.fromisoformat(day+'T'+clock).replace(tzinfo=HK)


class ResearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = freeze(at('2026-09-24', '14:13:09'), 'a'*64)
        cls.events = synthetic_events(cls.protocol, sessions=6, codes=('HK.00100',))
        cls.first = next(e for e in cls.events if isinstance(e, SignalObservation))
        cls.bar = next(e for e in cls.events if isinstance(e, MinuteObservation))
        cls.context = next(e for e in cls.events if isinstance(e, DailyContextObservation))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cross-day-research-')
        self.addCleanup(self.temp.cleanup)
        self.config = Config(Path(self.temp.name)/'research.sqlite', enabled=True, dataset_kind='SYNTHETIC')

    def collector(self, **changes):
        collector = Collector(replace(self.config, **changes), self.protocol)
        self.addCleanup(collector.close)
        return collector

    def report(self, day='2026-09-25', events=None):
        return replay(self.protocol, self.events if events is None else events, day, at(day), 'SYNTHETIC')

    def arm(self, report, name='candidate-3d'):
        return next(a for a in report.arms if a.name == name)

    def audit(self, report, key):
        return next((a.count for a in report.audit if a.name == key), 0)

    def test_codec_roundtrip_all_observation_types(self):
        exposure = ExposureObservation('exposure', self.first.code, at('2026-09-25'), 'test', ('candidate-5d',))
        for event in (*self.events, exposure):
            self.assertEqual(event, decode(encode(event)))

    def test_validation_rejects_naive_unfinished_invalid_and_future_context(self):
        with self.assertRaises(ValueError):
            replace(self.first, received_at=datetime(2026, 9, 25))
        with self.assertRaises(ValueError):
            replace(self.bar, received_at=self.bar.minute_at)
        with self.assertRaises(ValueError):
            replace(self.bar, mean=float('nan'))
        with self.assertRaises(ValueError):
            replace(self.bar, minute_at=at('2026-09-25', '12:30:00'))
        with self.assertRaises(ValueError):
            replace(self.context, received_at=at('2026-09-23', '09:00:00'))
        with self.assertRaises(ValueError):
            replace(self.context, rows=self.context.rows[::-1])

    def test_disabled_does_not_touch_files_or_factory(self):
        with patch('scripts.analysis.swing_study.forward.runtime.collector.verify_frozen') as verify:
            collector = Collector(replace(self.config, enabled=False), self.protocol,
                                  lambda *_: self.fail('disabled opened a journal'))
            self.assertFalse(collector.observe(self.first))
            self.assertEqual(collector.events(), ())
            verify.assert_not_called()
        self.assertFalse(self.config.path.exists())

    def test_frozen_source_change_fails_before_database_creation(self):
        protocol = replace(self.protocol, sources=(replace(self.protocol.sources[0], sha256='bad'), *self.protocol.sources[1:]))
        with self.assertRaises(ValueError):
            Collector(self.config, protocol)
        self.assertFalse(self.config.path.exists())

    def test_foreign_database_is_never_modified(self):
        with closing(sqlite3.connect(self.config.path)) as connection:
            connection.execute('CREATE TABLE production(value TEXT)')
        before = self.config.path.read_bytes()
        with self.assertRaises(ValueError):
            self.collector()
        self.assertEqual(before, self.config.path.read_bytes())

    def test_dataset_and_protocol_binding(self):
        self.collector().close()
        with self.assertRaises(ValueError):
            self.collector(dataset_kind='LOCAL_OBSERVATIONS')
        with self.assertRaises(ValueError):
            Collector(self.config, replace(self.protocol, historical_input_sha256='b'*64))

    def test_restart_restores_lease_and_exposure(self):
        collector = self.collector()
        collector.observe(self.first)
        exposure = ExposureObservation('exposure', self.first.code, at('2026-09-25'), 'test', ('candidate-5d',))
        collector.observe(exposure)
        before = collector.tracks
        collector.close()
        recovered = self.collector()
        self.assertEqual(before, recovered.tracks)
        self.assertEqual(recovered.events(), (self.first, exposure))
        self.assertEqual(recovered.selection(at('2026-10-06'), (), 1).research, ('HK.00100',))

    def test_duplicate_is_idempotent_and_conflict_rejected(self):
        collector = self.collector()
        self.assertTrue(collector.observe(self.first))
        self.assertFalse(collector.observe(self.first))
        with self.assertLogs(level='ERROR'), self.assertRaises(ValueError):
            collector.observe(replace(self.first, sector='医药'))
        self.assertEqual(collector.events(), (self.first,))

    def test_minute_revision_even_new_id_is_rejected(self):
        collector = self.collector()
        collector.observe(self.bar)
        with self.assertLogs(level='ERROR'), self.assertRaises(ValueError):
            collector.observe(replace(self.bar, event_id='revised'))

    def test_out_of_order_receipt_is_rejected(self):
        collector = self.collector()
        collector.observe(self.first)
        with self.assertLogs(level='ERROR'), self.assertRaises(ValueError):
            collector.observe(self.bar)

    def test_quota_failure_does_not_advance_memory(self):
        collector = self.collector(max_events=1)
        collector.observe(self.bar)
        with self.assertLogs(level='ERROR'), self.assertRaises(OverflowError):
            collector.observe(self.first)
        self.assertEqual(collector.tracks, ())
        self.assertEqual(collector.events(), (self.bar,))

    def test_transaction_failure_does_not_advance_memory(self):
        collector = self.collector()
        collector.journal.connection.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with self.assertLogs(level='ERROR'), self.assertRaises(sqlite3.IntegrityError):
            collector.observe(self.first)
        self.assertEqual(collector.tracks, ())
        self.assertEqual(collector.events(), ())
        collector.journal.connection.execute('DROP TRIGGER fail_insert')
        self.assertTrue(collector.observe(self.first))

    def test_concurrent_writer_requires_recovery(self):
        first, second = self.collector(), self.collector()
        first.observe(self.bar)
        with self.assertLogs(level='ERROR'), self.assertRaises(RuntimeError):
            second.observe(self.first)
        self.assertEqual(second.tracks, ())

    def test_five_session_lease_skips_holiday_and_ignores_invalidation(self):
        tracks = transition((), self.first, self.protocol)
        self.assertEqual(tracks[0].until_day, '2026-10-02')
        invalid = replace(self.first, event_id='invalid', stage='INVALIDATED',
                          received_at=at('2026-09-25', '10:00:00'))
        self.assertEqual(tracks, transition(tracks, invalid, self.protocol))
        self.assertTrue(select(tracks, at('2026-10-02'), (), 1).research)
        self.assertTrue(select(tracks, at('2026-10-02', '16:30:01'), (), 1).research)
        flat = ExposureObservation('flat', self.first.code, at('2026-10-02'), 'test', (), '2026-10-02')
        reconciled = transition(tracks, flat, self.protocol)
        self.assertFalse(select(reconciled, at('2026-10-02', '16:30:01'), (), 1).research)

    def test_protected_positions_never_evicted_and_exposure_prioritized(self):
        tracks = transition((), self.first, self.protocol)
        tracks = transition(tracks, replace(self.first, event_id='second', code='HK.00699'), self.protocol)
        tracks = transition(tracks, ExposureObservation('hold', 'HK.00699', at('2026-09-25'), 'test', ('candidate-3d',)), self.protocol)
        chosen = select(tracks, at('2026-09-28'), ('HK.00700',), 2)
        self.assertEqual(chosen.protected, ('HK.00700',))
        self.assertEqual(chosen.research, ('HK.00699',))
        self.assertEqual(chosen.deferred, ('HK.00100',))
        self.assertFalse(chosen.execution_allowed)
        over = select(tracks, at('2026-09-28'), ('HK.00700', 'HK.03317'), 1)
        self.assertEqual(len(over.protected), 2)
        self.assertEqual(over.research, ())
        self.assertTrue(over.over_capacity)

    def test_missing_stale_reconnect_and_drop_evidence(self):
        now = at('2026-09-25', '10:00:00')
        a = ContinuityObservation('a', 'HK.00100', now, 'test', True, True, 'c1', 2, 0.)
        b = replace(a, event_id='b', received_at=now+timedelta(minutes=3), connection_id='c2', dropped_total=1)
        self.assertEqual(continuity((), a.code, now).state, 'UNKNOWN_NO_EVIDENCE')
        self.assertEqual(continuity((a,), a.code, b.received_at).state, 'UNKNOWN_STALE_EVIDENCE')
        status = continuity((a, b), a.code, b.received_at)
        self.assertEqual((status.wall_clock_gaps, status.reconnects, status.reported_drops), (1, 1, 3))
        self.assertTrue(status.zero_volume_reported)
        self.assertFalse(status.complete_tick_capture_certified)

    def test_intraday_weekend_and_crossdate_asof_rejected(self):
        for day, when in (('2026-09-25', at('2026-09-25', '14:00:00')),
                          ('2026-09-26', at('2026-09-26')), ('2026-09-25', at('2026-09-28'))):
            with self.assertRaises(ValueError):
                replay(self.protocol, self.events, day, when)

    def test_four_frozen_arms_and_completed_minute_entry(self):
        report = self.report()
        self.assertEqual(len(report.arms), 4)
        early = self.arm(report).replay.trades[0]
        formal = self.arm(report, 'control-3d').replay.trades[0]
        self.assertEqual((early.signal, early.entry), (4, 6))
        self.assertEqual((formal.signal, formal.entry), (10, 12))
        self.assertFalse(report.strategy_validated)
        self.assertFalse(report.live_execution_allowed)

    def test_open_positions_keep_cash_and_block_next_day_entry(self):
        report = self.report('2026-09-28')
        arm = self.arm(report)
        self.assertEqual(arm.account.cash_hkd, 90000.)
        self.assertEqual(arm.account.open_positions, 1)
        self.assertIsNone(arm.account.return_pct)
        self.assertEqual(arm.replay.blocked_by_position, 1)
        self.assertEqual(len(arm.replay.trades), 1)

    def test_three_and_five_session_clock_exits(self):
        third = self.report('2026-09-29')
        self.assertEqual(self.arm(third).replay.trades[0].exit, 2*N+INDEX[951])
        self.assertIsNone(self.arm(third, 'candidate-5d').replay.trades[0].exit)
        fifth = self.report('2026-10-02')
        self.assertEqual(self.arm(fifth, 'candidate-5d').replay.trades[0].exit, 4*N+INDEX[951])
        self.assertNotIn('2026-10-01', fifth.days)

    def test_missing_exit_remains_pending_and_fills_next_session(self):
        events = tuple(e for e in self.events if not (isinstance(e, MinuteObservation)
            and e.minute_at.date().isoformat() == '2026-09-29' and e.minute_at.hour >= 15))
        third = self.arm(self.report('2026-09-29', events))
        self.assertEqual(third.replay.trades[0].reason, 'PENDING_EXIT_NO_FILL')
        self.assertEqual(third.account.cash_hkd, 90000.)
        fourth = self.arm(self.report('2026-09-30', events))
        self.assertEqual(fourth.replay.trades[0].exit, 3*N)
        self.assertEqual(fourth.account.open_positions, 0)

    def test_missing_whole_session_not_compressed_or_filled(self):
        events = tuple(e for e in self.events if not (isinstance(e, MinuteObservation)
                                                    and e.minute_at.date().isoformat() == '2026-09-28'))
        report = self.report('2026-09-29', events)
        trade = self.arm(report).replay.trades[0]
        self.assertEqual(len(report.days), 3)
        self.assertEqual(trade.missing_whole_days, 1)
        self.assertIsNone(self.arm(report).account.strict_drawdown_pct)

    def test_late_minutes_cannot_be_backfilled_into_signal_or_entry(self):
        delayed = tuple(sorted((replace(e, received_at=e.received_at+timedelta(seconds=1))
            if isinstance(e, MinuteObservation) else e for e in self.events), key=lambda e: (e.received_at, e.event_id)))
        report = self.report(events=delayed)
        self.assertEqual(self.audit(report, 'late_minutes_excluded'), N)
        self.assertEqual(self.arm(report).replay.signals, 0)
        self.assertEqual(self.arm(report, 'control-3d').replay.unfilled, 1)

    def test_late_daily_context_not_used(self):
        events = tuple(sorted((replace(e, received_at=at(e.for_day, '09:30:00'))
            if isinstance(e, DailyContextObservation) else e for e in self.events), key=lambda e: (e.received_at, e.event_id)))
        report = self.report(events=events)
        self.assertEqual(self.arm(report).replay.signals, 0)
        self.assertGreater(self.audit(report, 'missing_or_late_daily_contexts'), 0)

    def test_future_observations_do_not_change_prefix(self):
        day = '2026-09-25'
        prefix = tuple(e for e in self.events if e.received_at <= at(day))
        self.assertEqual(self.report(events=prefix), self.report())

    def test_late_signal_uses_receipt_time_not_emission(self):
        events = tuple(sorted((replace(e, received_at=e.received_at+timedelta(minutes=5))
            if isinstance(e, SignalObservation) and e.stage == 'FIRST' else e for e in self.events),
            key=lambda e: (e.received_at, e.event_id)))
        trade = self.arm(self.report(events=events)).replay.trades[0]
        self.assertEqual(trade.signal, 9)
        self.assertEqual(trade.entry, 11)

    def test_late_theme_not_backfilled_onto_first(self):
        events = tuple(replace(e, sector='') if isinstance(e, SignalObservation) and e.stage == 'FIRST' else e for e in self.events)
        self.assertEqual(self.arm(self.report(events=events)).replay.signals, 0)

    def test_market_arrays_have_no_forward_fill(self):
        study, _ = normalize(self.protocol, (self.context, self.first), '2026-09-28', at('2026-09-28'))
        self.assertEqual(len(study.market.days), 2)
        self.assertTrue(np.isnan(study.market.paths['HK.00100'].mean).all())

    def test_end_to_end_journal_restart_and_replay_exposure_checkpoint(self):
        collector = self.collector()
        day = '2026-09-25'
        for event in self.events:
            if event.received_at <= at(day):
                collector.observe(event)
        before = self.report(events=collector.events())
        for exposure in before.exposures:
            collector.observe(exposure)
        self.assertEqual(len(collector.tracks[0].active_arms), 4)
        collector.close()
        recovered = self.collector()
        # Checkpoint receipt is 16:30; earlier price inputs remain identical.
        restored = self.report(events=recovered.events())
        self.assertEqual(before, restored)
        for exposure in restored.exposures:
            self.assertFalse(recovered.observe(exposure))
        self.assertEqual(collector.tracks, recovered.tracks)

    def test_empty_evidence_never_reports_measured_zero_return(self):
        report = self.report(events=())
        self.assertEqual(report.exposures, ())
        for arm in report.arms:
            self.assertIsNone(arm.account.return_pct)
            self.assertIsNone(arm.account.strict_drawdown_pct)

    def test_strict_input_booleans_reject_string_false(self):
        with self.assertRaises(ValueError):
            replace(self.first, large_inflow='false')
        with self.assertRaises(ValueError):
            replace(self.config, enabled='false')

    def test_daily_snapshot_revision_is_rejected(self):
        collector = self.collector()
        collector.observe(self.context)
        with self.assertLogs(level='ERROR'), self.assertRaises(ValueError):
            collector.observe(replace(self.context, event_id='new-version', version='v2'))

    def test_beyond_calendar_fails_closed_without_committing(self):
        when = at('2026-12-23', '09:34:30')
        late = replace(self.first, event_id='end-calendar', emitted_at=when, received_at=when)
        collector = self.collector()
        with self.assertRaises(ValueError):
            collector.observe(late)
        self.assertEqual(collector.events(), ())

    def test_database_byte_limit_is_enforced_atomically(self):
        collector = self.collector(max_database_bytes=65536)
        rejected = False
        for index in range(100):
            event = replace(self.context, event_id=f'large-{index}', code=f'HK.{index+1:05d}')
            try:
                with patch('scripts.analysis.swing_study.forward.runtime.collector.logging'):
                    collector.observe(event)
            except sqlite3.OperationalError as error:
                self.assertIn('full', str(error))
                rejected = True
                break
        self.assertTrue(rejected)
        self.assertLessEqual(self.config.path.stat().st_size, 65536)
        self.assertEqual(len(collector.events()), index)

    def test_repeated_source_cannot_hide_missing_frozen_source(self):
        sources = (*self.protocol.sources[:-1], self.protocol.sources[0])
        with self.assertRaises(ValueError):
            verify_frozen(replace(self.protocol, sources=sources))

    def test_disconnection_and_counter_reset_remain_visible(self):
        now = at('2026-09-25', '10:00:00')
        a = ContinuityObservation('a', 'HK.00100', now, 'test', False, False, 'c1', 5)
        b = replace(a, event_id='b', received_at=now+timedelta(seconds=30), connected=True,
                    subscribed=True, dropped_total=0)
        status = continuity((a, b), a.code, b.received_at)
        self.assertEqual((status.disconnected_samples, status.counter_resets, status.reported_drops), (1, 1, 5))

    def test_persisted_early_checkpoint_is_not_released_by_midnight(self):
        collector = self.collector()
        for event in self.events:
            if event.received_at <= at('2026-09-25'):
                collector.observe(event)
        report = self.report(events=collector.events())
        for exposure in report.exposures:
            collector.observe(exposure)
        collector.close()
        recovered = self.collector()
        self.assertEqual(recovered.selection(at('2026-10-06'), (), 1).research, ('HK.00100',))
        self.assertIsNone(self.arm(report).replay.trades[0].net)

    def test_missing_replay_checkpoint_keeps_tracking_fail_closed(self):
        collector = self.collector()
        collector.observe(self.first)
        collector.close()
        recovered = self.collector()
        self.assertEqual(recovered.selection(at('2026-10-06'), (), 1).research, ('HK.00100',))

    def test_current_state_selection_rejects_past_timestamp(self):
        collector = self.collector()
        collector.observe(self.first)
        with self.assertRaises(ValueError):
            collector.selection(at('2026-09-25', '09:30:00'), (), 1)


if __name__ == '__main__':
    unittest.main()
