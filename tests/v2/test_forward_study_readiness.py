"""Prospective registration cannot relabel seen/unfinished history as fresh proof."""
from dataclasses import asdict
from datetime import date, datetime, timedelta
import unittest

from scripts.analysis.minute_entry_study.models import HK
from scripts.analysis.swing_study.forward.protocol import (
    DayEvidence, SourceHash, encoded, evaluate, freeze, from_payload, scheduled_days,
)
from scripts.analysis.swing_study.forward.run import registered_hash


class ForwardReadinessTests(unittest.TestCase):
    def setUp(self):
        self.registered = datetime(2026, 9, 24, 14, tzinfo=HK)
        self.protocol = freeze(self.registered, 'synthetic-history')

    def check(self, days, when):
        return evaluate(self.protocol, when, tuple(DayEvidence(d, 2, 100) for d in days),
                        when, self.protocol.sources)

    def test_two_candidates_and_horizon_matched_controls_are_frozen(self):
        self.assertEqual(self.protocol.earliest_entry_date, '2026-09-25')
        self.assertEqual(self.protocol.seen_through_date, '2026-09-24')
        self.assertEqual(len(self.protocol.arms), 4)
        self.assertEqual(sum(a.role == 'candidate' for a in self.protocol.arms), 2)
        self.assertFalse(self.protocol.live_execution_allowed)
        self.assertFalse(self.protocol.automatic_start)

    def test_seen_day_cannot_become_prospective_after_reexport(self):
        result = self.check(['2026-09-23', '2026-09-24'], datetime(2026, 9, 24, 17, tzinfo=HK))
        self.assertEqual(result.post_freeze_archived_dates, ())
        self.assertEqual(result.latest_closed_archive_date, '2026-09-24')
        self.assertIsNone(result.performance_result)

    def test_intraday_archive_is_not_a_closed_session(self):
        result = self.check(['2026-09-25'], datetime(2026, 9, 25, 14, tzinfo=HK))
        self.assertEqual(result.post_freeze_archived_dates, ())

    def test_post_close_without_archive_is_not_available(self):
        result = self.check([], datetime(2026, 9, 25, 17, tzinfo=HK))
        self.assertIn('NO_POST_FREEZE_CLOSED_ARCHIVE', result.blockers)

    def test_three_and_five_sessions_mature_separately(self):
        result = self.check(['2026-09-25', '2026-09-28', '2026-09-29'], datetime(2026, 9, 29, 17, tzinfo=HK))
        self.assertEqual(result.horizons[0].mature_archived_entry_dates, ('2026-09-25',))
        self.assertEqual(result.horizons[1].mature_archived_entry_dates, ())

    def test_national_day_is_not_counted_as_a_holding_session(self):
        days = scheduled_days(date(2026, 9, 25), date(2026, 10, 2))
        self.assertEqual(len(days), 5)
        self.assertNotIn('2026-10-01', days)
        result = self.check(days, datetime(2026, 10, 2, 17, tzinfo=HK))
        self.assertEqual(result.horizons[1].mature_archived_entry_dates, ('2026-09-25',))
        self.assertFalse(result.actual_stock_path_quality_verified)
        self.assertFalse(result.evaluation_ready)

    def test_missing_intermediate_date_prevents_maturity(self):
        result = self.check(['2026-09-25', '2026-09-29'], datetime(2026, 9, 29, 17, tzinfo=HK))
        self.assertEqual(result.horizons[0].mature_archived_entry_dates, ())

    def test_old_version_and_empty_archive_are_not_accepted(self):
        when = datetime(2026, 9, 29, 17, tzinfo=HK)
        result = evaluate(self.protocol, when, (DayEvidence('2026-09-25', 1, 100),
            DayEvidence('2026-09-28', 2, 0)), when, self.protocol.sources)
        self.assertEqual(result.post_freeze_archived_dates, ())

    def test_source_change_is_reported_not_silently_reregistered(self):
        changed = (SourceHash(self.protocol.sources[0].path, 'changed'), *self.protocol.sources[1:])
        result = evaluate(self.protocol, self.registered, (), self.registered, changed)
        self.assertEqual(result.state, 'FROZEN_SOURCE_CHANGED')
        self.assertFalse(result.evaluation_ready)

    def test_parameter_edit_requires_new_protocol(self):
        payload = asdict(self.protocol)
        payload['arms'][0]['entry']['ratio'] = .7
        with self.assertRaises(ValueError):
            from_payload(payload)

    def test_registration_hash_survives_windows_newline_roundtrip(self):
        unix = encoded(self.protocol)
        windows = unix.replace('\n', '\r\n')
        self.assertEqual(registered_hash(unix.encode()), registered_hash(windows.encode()))

    def test_calendar_scope_is_not_guessed(self):
        with self.assertRaises(ValueError):
            scheduled_days(date(2026, 12, 23), date(2026, 12, 24))

    def test_review_dates_include_weekends_and_holidays(self):
        result = self.check([], self.registered)
        self.assertEqual(result.expected_preliminary_entry_window_end, '2026-10-26')
        self.assertEqual(result.expected_preliminary_five_day_followup_end, '2026-10-30')
        self.assertEqual(result.horizons[0].earliest_scheduled_window_end, '2026-09-29')
        self.assertEqual(result.horizons[1].earliest_scheduled_window_end, '2026-10-02')

    def test_future_snapshot_is_rejected_and_stale_snapshot_marked(self):
        with self.assertRaises(ValueError):
            evaluate(self.protocol, self.registered+timedelta(hours=1), (), self.registered, self.protocol.sources)
        result = evaluate(self.protocol, self.registered, (), self.registered+timedelta(hours=2), self.protocol.sources)
        self.assertIn('READINESS_SNAPSHOT_STALE', result.blockers)


if __name__ == '__main__':
    unittest.main()
