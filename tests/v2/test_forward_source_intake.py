"""Source provenance, explicit ingress and quarantine integration tests."""
from contextlib import closing
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.analysis.minute_entry_study.models import HK
from scripts.analysis.swing_study.forward.intake.export import CODES, snapshot as export_snapshot
from scripts.analysis.swing_study.forward.intake.models import (
    DIAGNOSTIC, MAX_BYTES, SOURCE, DailyRow, MinuteCoverage, SignalRow, Snapshot, TickRow, load,
)
from scripts.analysis.swing_study.forward.intake.normalize import LiveSignalIngress, assess, persisted_signal
from scripts.analysis.swing_study.forward.protocol import freeze
from scripts.analysis.swing_study.forward.runtime.adapter import replay
from scripts.analysis.swing_study.forward.runtime.collector import Collector
from scripts.analysis.swing_study.forward.runtime.models import Config


def at(day='2026-09-25', clock='09:34:30'):
    return datetime.fromisoformat(day+'T'+clock).replace(tzinfo=HK)


def payload(when=None, **changes):
    when = when or at()
    result = {'stock_code': 'HK.00100', 'trade_date': when.date().isoformat(), 'timestamp': when.timestamp(),
        'inflow_stage': 'FIRST', 'last_price': 10., 'inflow_first_price': 10., 'inflow_sequence_no': 1,
        'plate_name': '科技', 'direction': 'RISING', 'is_large_inflow': True, 'window_buy_ratio': .6,
        'window_main_net': 100000., 'legacy_observe_only': True}
    result.update(changes)
    return result


def source_row(when=None, **changes):
    when = when or at()
    return SignalRow(1, when.date().isoformat(), 'HK.00100', 'capital_trend', 'observe',
        when.replace(tzinfo=None).isoformat(), when.astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
        json.dumps(payload(when, **changes)))


class SourceIntakeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='source-intake-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.protocol = freeze(at('2026-09-24', '14:00:00'), 'synthetic-history')
        self.snapshot = Snapshot(at(clock='17:00:00'), '2026-09-24', '2026-09-25', CODES,
            (source_row(),), (), (), (), (), 0, 'a'*64)

    def collector(self, kind='LOCAL_OBSERVATIONS', enabled=True):
        collector = Collector(Config(self.root/(kind+'.sqlite'), enabled=enabled, dataset_kind=kind), self.protocol)
        self.addCleanup(collector.close)
        return collector

    def test_sqlite_utc_creation_time_not_treated_as_hk(self):
        event = persisted_signal(source_row(), self.snapshot.observed_at)
        self.assertEqual(event.received_at, at())
        self.assertTrue(event.source.startswith(DIAGNOSTIC))

    def test_subsecond_emission_and_second_resolution_persistence(self):
        when = at().replace(microsecond=500000)
        row = replace(source_row(when), persisted_text='2026-09-25 01:34:30')
        self.assertEqual(persisted_signal(row, self.snapshot.observed_at).received_at, when)

    def test_delayed_persistence_is_not_backdated(self):
        row = replace(source_row(), persisted_text='2026-09-25 01:35:30')
        self.assertEqual(persisted_signal(row, self.snapshot.observed_at).received_at, at(clock='09:35:30'))

    def test_mismatched_epoch_row_identity_and_future_are_rejected(self):
        for row in (replace(source_row(), emitted_text='2026-09-25T10:00:00'),
                    replace(source_row(), persisted_text='2026-09-25 00:00:00'),
                    replace(source_row(), code='HK.00699'), replace(source_row(), source='other'),
                    replace(source_row(), persisted_text='2026-09-26 01:00:00')):
            with self.subTest(row=row), self.assertRaises(ValueError):
                persisted_signal(row, self.snapshot.observed_at)

    def test_pre_freeze_rows_not_promoted_by_export_date(self):
        report = assess(replace(self.snapshot, signals=(source_row(at('2026-09-24')),)), self.protocol)
        self.assertEqual(report.normalized, ())
        self.assertEqual(report.rejections[0].reason, 'BEFORE_FROZEN_ENTRY_DATE')

    def test_general_alert_is_out_of_scope_not_malformed(self):
        report = assess(replace(self.snapshot, signals=(source_row(inflow_stage='', inflow_sequence_no=0),)), self.protocol)
        self.assertEqual(report.rejections[0].reason, 'GENERAL_ALERT_NOT_INFLOW_SEQUENCE')
        self.assertEqual(report.normalized, ())

    def test_cross_day_persistence_is_not_a_new_first(self):
        row = replace(source_row(), persisted_text='2026-09-26 01:00:00')
        report = assess(replace(self.snapshot, observed_at=at('2026-09-28'), signals=(row,)), self.protocol)
        self.assertEqual(report.rejections[0].reason, 'PERSISTED_ON_DIFFERENT_DAY')

    def test_signal_ids_must_be_unique(self):
        with self.assertRaises(ValueError):
            assess(replace(self.snapshot, signals=(source_row(), source_row())), self.protocol)

    def test_unsupported_source_contract_is_recorded_as_rejection(self):
        row = source_row()
        bad = json.loads(row.detail_json)
        del bad['legacy_observe_only']
        report = assess(replace(self.snapshot, signals=(replace(row, detail_json=json.dumps(bad)),)), self.protocol)
        self.assertEqual(report.rejections[0].reason, 'INVALID_OR_INCOMPLETE_SOURCE_CONTRACT')

    def test_timestamp_diagnostics_never_certify_receipt_or_continuity(self):
        ticks = tuple(TickRow(i, 'HK.00100', '2026-09-25', '2026-09-25 09:34:30',
            int(at().timestamp()*1000)+delta, '2026-09-25 01:34:31', i) for i, delta in enumerate((0, 1000, -1000)))
        report = assess(replace(self.snapshot, ticks=ticks), self.protocol)
        stock = report.stocks[0]
        self.assertEqual((stock.timestamp_equals_exchange_rows, stock.timestamp_after_exchange_rows,
                          stock.timestamp_before_exchange_rows), (1, 1, 1))
        self.assertFalse(report.prospective_ready)
        self.assertIsNone(report.performance_result)
        self.assertIn('TICK_TIMESTAMP_PRODUCER_NOT_IDENTIFIABLE', report.blockers)

    def test_live_ingress_default_off_has_no_side_effects(self):
        ingress = LiveSignalIngress()
        self.assertFalse(ingress.on_signal({}, source_event_id='', received_at=at()))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_live_ingress_rejects_disabled_or_quarantined_collector(self):
        for collector in (None, self.collector(enabled=False), self.collector(DIAGNOSTIC)):
            with self.assertRaises(ValueError):
                LiveSignalIngress(collector, enabled=True)

    def test_live_source_contract_reaches_journal_idempotently(self):
        collector = self.collector()
        ingress = LiveSignalIngress(collector, enabled=True)
        self.assertTrue(ingress.on_signal(payload(), source_event_id='e1', received_at=at()))
        self.assertFalse(ingress.on_signal(payload(), source_event_id='e1', received_at=at()))
        self.assertEqual(collector.events()[0].source, 'LOCAL_CAPITAL_TREND_EXPLICIT_RECEIPT')
        self.assertEqual(collector.tracks[0].code, 'HK.00100')
        collector.close()
        self.assertEqual(self.collector().events()[0].event_id, 'live-legacy:e1')

    def test_live_receipt_cannot_precede_emission_or_be_naive(self):
        ingress = LiveSignalIngress(self.collector(), enabled=True)
        for when in (at()-timedelta(seconds=1), at().replace(tzinfo=None)):
            with self.assertRaises(ValueError):
                ingress.on_signal(payload(), source_event_id='e1', received_at=when)

    def test_general_alert_does_not_create_a_live_first(self):
        collector = self.collector()
        ingress = LiveSignalIngress(collector, enabled=True)
        self.assertFalse(ingress.on_signal(payload(inflow_stage='', inflow_sequence_no=0),
                                          source_event_id='general', received_at=at()))
        self.assertEqual(collector.events(), ())

    def test_untyped_boolean_cannot_enable_ingress_or_signal(self):
        with self.assertRaises(ValueError):
            LiveSignalIngress(enabled='false')
        ingress = LiveSignalIngress(self.collector(), enabled=True)
        with self.assertRaises(ValueError):
            ingress.on_signal(payload(is_large_inflow='false'), source_event_id='e1', received_at=at())

    def test_diagnostic_data_cannot_be_replayed_even_with_default_kind(self):
        report = assess(self.snapshot, self.protocol)
        for kind in (DIAGNOSTIC, 'LOCAL_OBSERVATIONS', 'SYNTHETIC'):
            with self.assertRaises(ValueError):
                replay(self.protocol, report.normalized, '2026-09-25', at(clock='17:00:00'), kind)

    def test_diagnostic_database_cannot_be_reopened_as_live(self):
        collector = self.collector(DIAGNOSTIC)
        for event in assess(self.snapshot, self.protocol).normalized:
            collector.observe(event)
        collector.close()
        config = Config(self.root/(DIAGNOSTIC+'.sqlite'), enabled=True, dataset_kind='LOCAL_OBSERVATIONS')
        with self.assertRaises(ValueError):
            Collector(config, self.protocol)

    def test_diagnostic_sources_cannot_mix_with_live_or_synthetic_journals(self):
        diagnostic = persisted_signal(source_row(), self.snapshot.observed_at)
        for kind in ('LOCAL_OBSERVATIONS', 'SYNTHETIC'):
            collector = self.collector(kind)
            with self.assertRaises(ValueError):
                collector.observe(diagnostic)
            self.assertEqual(collector.events(), ())
        quarantine = self.collector(DIAGNOSTIC)
        with self.assertRaises(ValueError):
            quarantine.observe(replace(diagnostic, source='LOCAL_CAPITAL_TREND_EXPLICIT_RECEIPT'))
        self.assertEqual(quarantine.events(), ())

    def test_snapshot_export_uses_read_transaction_and_focus_scope(self):
        with closing(sqlite3.connect(':memory:')) as connection:
            connection.executescript('''
                CREATE TABLE signal_pipeline(id,trade_date,stock_code,source,final_action,timestamp,created_at,raw_detail);
                CREATE TABLE ticker_data(id,stock_code,trade_date,trade_time,timestamp,created_at,sequence);
                CREATE TABLE ticker_minute(stock_code,trade_date,minute);
                CREATE TABLE kline_data(id,stock_code,time_key,created_at);
                CREATE TABLE subscription_snapshot(type,codes,updated_at);
            ''')
            row = source_row()
            connection.execute('INSERT INTO signal_pipeline VALUES (?,?,?,?,?,?,?,?)', tuple(asdict(row).values()))
            connection.execute("INSERT INTO ticker_minute VALUES ('HK.00100','2026-09-25','09:30')")
            connection.execute("INSERT INTO ticker_minute VALUES ('HK.00100','2026-09-25','12:30')")
            connection.commit()
            result = export_snapshot(connection, at(clock='17:00:00'))
            self.assertEqual(len(result['signals']), 1)
            self.assertEqual(result['minutes'][0][2], 1)
            self.assertFalse(connection.in_transaction)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute('DELETE FROM signal_pipeline')

    def encoded_snapshot(self, **changes):
        data = {'schema': 1, 'kind': 'FORWARD_SOURCE_INTAKE', 'source': SOURCE, 'scope': 'FOCUS_CODES_ONLY',
                'observed_at': self.snapshot.observed_at.isoformat(), 'start_date': self.snapshot.start_date,
                'end_date': self.snapshot.end_date, 'codes': CODES, 'signals': [list(asdict(source_row()).values())],
                'ticks': [], 'minutes': [], 'daily': [], 'columns': {}, 'subscription_snapshot_rows': 0,
                'read_only': True, 'truncated': False}
        data.update(changes)
        return gzip.compress(json.dumps(data).encode())

    def load_bytes(self, raw):
        path = self.root/'source.gz'
        path.write_bytes(raw)
        return load(path)

    def test_bounded_source_loader_preserves_hash_and_contract(self):
        result = self.load_bytes(self.encoded_snapshot())
        self.assertEqual(result.signals, (source_row(),))
        self.assertEqual(len(result.sha256), 64)

    def test_loader_refuses_incomplete_wrong_scope_and_wrong_source(self):
        for changes in ({'read_only': False}, {'truncated': True}, {'source': 'UNKNOWN'},
                        {'codes': ['HK.00700']}, {'end_date': '2026-09-29'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.load_bytes(self.encoded_snapshot(**changes))

    def test_gzip_expansion_is_bounded(self):
        with self.assertRaises(ValueError):
            self.load_bytes(gzip.compress(b' '*(MAX_BYTES+1)))

    def test_valid_daily_or_full_minute_counts_do_not_certify_point_in_time(self):
        snapshot = replace(self.snapshot, daily=(DailyRow(1, 'HK.00100', '2026-09-24', '2026-09-24 08:30:00'),),
                           minutes=(MinuteCoverage('HK.00100', '2026-09-25', 330, '09:30', '15:59'),))
        report = assess(snapshot, self.protocol)
        self.assertIn('DAILY_POINT_IN_TIME_VERSION_NOT_CAPTURED', report.blockers)
        self.assertFalse(report.prospective_ready)


if __name__ == '__main__':
    unittest.main()
