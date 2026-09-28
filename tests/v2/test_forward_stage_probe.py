"""The separately authorized query must export aggregates, never source records."""
from dataclasses import asdict
from datetime import datetime
import json
import sqlite3
import unittest
from unittest.mock import patch

from scripts.analysis.swing_study.forward.intake.stage_probe import HK, snapshot


class StageProbeTest(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.addCleanup(self.connection.close)
        self.connection.execute('CREATE TABLE signal_pipeline(trade_date,stock_code,source,raw_detail)')
        self.now = datetime(2026, 9, 28, 11, 30, tzinfo=HK)

    def insert(self, day='2026-09-25', code='HK.00100', source='capital_trend', stage='FIRST', raw=None):
        self.connection.execute('INSERT INTO signal_pipeline VALUES (?,?,?,?)',
            (day, code, source, json.dumps({'inflow_stage': stage}) if raw is None else raw))
        self.connection.commit()

    def test_group_counts_distinct_codes_but_no_source_identifiers(self):
        self.insert()
        self.insert()
        self.insert(code='HK.00699')
        self.insert(stage='CONFIRMED')
        result = snapshot(self.connection, self.now)
        self.assertEqual([(r.stage, r.event_count, r.stock_count) for r in result.counts],
                         [('CONFIRMED', 1, 1), ('FIRST', 3, 2)])
        encoded = json.dumps(asdict(result))
        self.assertNotIn('HK.00100', encoded)
        self.assertNotIn('raw_detail', encoded)
        self.assertFalse(result.individual_records_exported)

    def test_only_approved_dates_hk_and_legacy_source(self):
        self.insert()
        self.insert(day='2026-09-23')
        self.insert(day='2026-09-29')
        self.insert(code='US.AAPL')
        self.insert(source='v2')
        result = snapshot(self.connection, self.now)
        self.assertEqual(sum(r.event_count for r in result.counts), 1)
        self.assertEqual((result.start_date, result.end_date), ('2026-09-24', '2026-09-28'))

    def test_missing_invalid_and_unrecognized_stage_are_distinct(self):
        for stage in ('', ' ', None, 1, 'untrusted source text'):
            self.insert(stage=stage)
        self.insert(raw='invalid-json')
        result = snapshot(self.connection, self.now)
        counts = {r.stage: r.event_count for r in result.counts}
        self.assertEqual(counts, {'NO_STAGE': 3, 'INVALID_STAGE_TYPE': 1, 'OTHER_STAGE': 1, 'INVALID_JSON': 1})
        self.assertNotIn('untrusted source text', json.dumps(asdict(result)))

    def test_read_only_guard_and_transaction_closed(self):
        self.insert()
        snapshot(self.connection, self.now)
        self.assertFalse(self.connection.in_transaction)
        with self.assertRaises(sqlite3.OperationalError):
            self.connection.execute('DELETE FROM signal_pipeline')
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM signal_pipeline').fetchone()[0], 1)

    def test_over_limit_fails_without_partial_result(self):
        self.insert()
        self.insert(stage='CONFIRMED')
        with patch('scripts.analysis.swing_study.forward.intake.stage_probe.MAX_GROUPS', 1):
            with self.assertRaises(ValueError):
                snapshot(self.connection, self.now)
        self.assertFalse(self.connection.in_transaction)

    def test_empty_result_is_not_a_claim_about_whole_exchange(self):
        result = snapshot(self.connection, self.now)
        self.assertEqual(result.counts, ())
        self.assertFalse(result.all_listed_stocks_coverage_certified)
        self.assertTrue(result.read_only)

    def test_timestamp_requires_timezone(self):
        with self.assertRaises(ValueError):
            snapshot(self.connection, self.now.replace(tzinfo=None))


if __name__ == '__main__':
    unittest.main()
