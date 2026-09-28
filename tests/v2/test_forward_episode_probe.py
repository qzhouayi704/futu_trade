"""Explicit two-sequence diagnostic scope and read-only guarantees."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import sqlite3
import unittest
from unittest.mock import patch

from scripts.analysis.swing_study.forward.intake.episode_probe import CUTOFF, HK, snapshot


class EpisodeProbeTest(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.addCleanup(self.connection.close)
        self.connection.execute('CREATE TABLE signal_pipeline(id,stock_code,stock_name,trade_date,timestamp,created_at,source,final_action,raw_detail)')
        self.now = datetime(2026, 9, 28, 12, tzinfo=HK)

    def insert(self, identity, code, stage, clock='09:35:00', source='capital_trend', day='2026-09-28'):
        when = datetime.fromisoformat(day+'T'+clock).replace(tzinfo=HK)
        detail = {'stock_code': code, 'trade_date': day, 'inflow_stage': stage,
                  'last_price': 10., 'reason': 'test reason', 'unrelated_private_field': 'DO_NOT_EXPORT'}
        self.connection.execute('INSERT INTO signal_pipeline VALUES (?,?,?,?,?,?,?,?,?)',
            (identity, code, 'test', day, when.replace(tzinfo=None).isoformat(),
             when.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), source, 'observe', json.dumps(detail)))
        self.connection.commit()

    def firsts(self):
        self.insert(1, 'HK.00100', 'FIRST')
        self.insert(2, 'HK.00699', 'FIRST')

    def test_exact_targets_and_stop_at_first_terminal(self):
        self.firsts()
        self.insert(3, 'HK.00100', 'INVALIDATED', '09:36:00')
        self.insert(4, 'HK.00699', 'EXPIRED', '09:50:00')
        self.insert(5, 'HK.00100', 'STRENGTHENED', '09:55:00')
        self.insert(6, 'HK.03317', 'CONFIRMED')
        result = snapshot(self.connection, self.now)
        self.assertEqual([[e.row_id for e in s.events] for s in result.sequences], [[1, 3], [2, 4]])
        self.assertTrue(all(s.terminal_observed for s in result.sequences))
        self.assertNotIn('DO_NOT_EXPORT', json.dumps(asdict(result)))

    def test_new_first_after_original_snapshot_is_excluded(self):
        self.firsts()
        self.insert(3, 'HK.03317', 'FIRST', '11:40:00')
        self.assertEqual(len(snapshot(self.connection, self.now).sequences), 2)

    def test_changed_target_count_rejects_before_export(self):
        self.firsts()
        self.insert(3, 'HK.03317', 'FIRST', '10:00:00')
        with self.assertRaises(ValueError):
            snapshot(self.connection, self.now)
        self.assertFalse(self.connection.in_transaction)

    def test_other_sources_markets_days_and_general_alerts_not_exported(self):
        self.firsts()
        self.insert(3, 'HK.00100', 'FIRST', source='v2')
        self.insert(4, 'US.AAPL', 'FIRST')
        self.insert(5, 'HK.03317', 'FIRST', day='2026-09-25')
        self.insert(6, 'HK.00100', '', '09:40:00')
        result = snapshot(self.connection, self.now)
        self.assertEqual(sum(len(s.events) for s in result.sequences), 2)

    def test_row_limit_fails_without_partial_sequence(self):
        self.firsts()
        self.insert(3, 'HK.00100', 'EXPIRED', '09:50:00')
        with patch('scripts.analysis.swing_study.forward.intake.episode_probe.MAX_SEQUENCE_ROWS', 1):
            with self.assertRaises(ValueError):
                snapshot(self.connection, self.now)

    def test_read_only_and_timestamp_guards(self):
        self.firsts()
        for when in (self.now.replace(tzinfo=None), datetime(2026, 9, 28, 9, tzinfo=HK)):
            with self.assertRaises(ValueError):
                snapshot(self.connection, when)
        snapshot(self.connection, self.now)
        self.assertFalse(self.connection.in_transaction)
        with self.assertRaises(sqlite3.OperationalError):
            self.connection.execute('DELETE FROM signal_pipeline')


if __name__ == '__main__':
    unittest.main()
