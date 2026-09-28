"""Production hook/SQLite tests without booting the app or importing broker SDKs."""
import ast
import asyncio
from contextlib import closing
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import logging
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from typing import Dict, List
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# The production root __init__ imports FastAPI/app configuration. Load this pure
# package under a test-only alias so these tests cannot start the application.
ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT/'simple_trade/services/research/theme_capture'
ALIAS = '_theme_capture_unit'
spec = importlib.util.spec_from_file_location(ALIAS, PACKAGE/'__init__.py', submodule_search_locations=[str(PACKAGE)])
package = importlib.util.module_from_spec(spec)
sys.modules[ALIAS] = package
spec.loader.exec_module(package)
from _theme_capture_unit.models import CaptureConfig, CaptureStats, HK, Member, Membership, signal
from _theme_capture_unit.service import ThemeCapture, configured_capture
from _theme_capture_unit.storage import SqliteMembershipSource, ThemeArchive

from scripts.analysis.swing_study.forward.intake.theme_audit import load_memberships
from scripts.analysis.swing_study.forward.intake.themes import SignalReference, decide


def raw(when=None, code='HK.00175'):
    when = when or datetime.now(HK)
    return {'stock_code': code, 'timestamp': when.timestamp(), 'trade_date': when.date().isoformat(),
            'inflow_stage': 'FIRST', 'inflow_sequence_no': 1, 'plate_name': '新能源车企',
            'direction': 'RISING', 'is_large_inflow': True}


def until(predicate, timeout=3.):
    deadline = time.monotonic()+timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('bounded test wait timed out')
        time.sleep(.005)


class CaptureTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='theme-capture-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root/'source.sqlite'
        with closing(sqlite3.connect(self.source)) as conn:
            conn.executescript('CREATE TABLE stocks(id,code); CREATE TABLE plates(id,plate_code,plate_name); '
                'CREATE TABLE stock_plates(stock_id,plate_id); '
                "INSERT INTO stocks VALUES (1,'HK.00175'),(2,'HK.09999'),(3,'HK.00699'); "
                "INSERT INTO plates VALUES (1,'MOCK.CAR','新能源车企'),(2,'MOCK.AI','人工智能'); "
                'INSERT INTO stock_plates VALUES (1,1),(1,2),(3,2);')
        self.cfg = CaptureConfig(True, self.source, self.root/'archive.sqlite',
                                 ('HK.00175', 'HK.09999'), 'test-build-only', refresh_seconds=1)

    def archive(self, cfg=None, session='session-1'):
        archive = ThemeArchive(cfg or self.cfg, session)
        self.addCleanup(archive.close)
        return archive

    def capture(self, cfg=None, source=None):
        capture = ThemeCapture(cfg or self.cfg, source)
        self.addCleanup(capture.close)
        capture.start()
        return capture

    def test_default_disabled_does_not_start_or_read_or_create(self):
        source = MagicMock()
        capture = self.capture(CaptureConfig(), source)
        self.assertFalse(capture.request_refresh())
        self.assertFalse(capture.on_signal(raw(), received_at=datetime.now(HK)))
        self.assertFalse(capture.snapshot().running)
        source.read.assert_not_called()
        self.assertFalse(self.cfg.path.exists())
        self.assertIsNone(configured_capture('no-file', {}))
        with self.assertRaises(ValueError):
            ThemeArchive(CaptureConfig(), 'disabled')

    def test_enable_requires_paths_allowlist_and_source_version(self):
        env = {'RESEARCH_THEME_CAPTURE_ENABLED': '1'}
        with self.assertRaises(ValueError):
            configured_capture(str(self.source), env)
        for changes in ({'codes': ()}, {'source_version': ''}, {'path': self.source},
                        {'codes': ('US.AAPL',)}, {'queue_size': 0}, {'max_bytes': 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.cfg, **changes)

    def test_source_allowlist_versions_and_no_completeness_promotion(self):
        before = self.source.read_bytes()
        rows = SqliteMembershipSource(self.cfg).read()
        self.assertEqual([r.code for r in rows], list(self.cfg.codes))
        self.assertEqual(len(rows[0].members), 2)
        self.assertEqual(rows[1].members, ())
        self.assertTrue(all(r.complete is False and r.received_at >= r.captured_at for r in rows))
        self.assertTrue(all(r.source_version == 'test-build-only' for r in rows))
        self.assertEqual(self.source.read_bytes(), before)

    def test_source_member_limit_rejects_instead_of_truncating(self):
        with closing(sqlite3.connect(self.source)) as conn:
            conn.executemany('INSERT INTO plates VALUES (?,?,?)', ((n, f'MOCK.{n}', '科技') for n in range(10, 140)))
            conn.executemany('INSERT INTO stock_plates VALUES (?,?)', ((1, n) for n in range(10, 140)))
            conn.commit()
        with self.assertRaises((ValueError, OverflowError)):
            SqliteMembershipSource(self.cfg).read()

    def test_signal_never_binds_future_or_previous_day_snapshot(self):
        membership = SqliteMembershipSource(self.cfg).read()[0]
        when = membership.received_at
        self.assertEqual(signal(raw(when), when, membership).snapshot_id, membership.snapshot_id)
        earlier = when-timedelta(seconds=1)
        self.assertIsNone(signal(raw(earlier), when, membership).snapshot_id)
        later = when+timedelta(days=1)
        self.assertIsNone(signal(raw(later), later, membership).snapshot_id)
        for receipt in (when.replace(tzinfo=None), when-timedelta(seconds=1)):
            with self.assertRaises(ValueError):
                signal(raw(when), receipt, membership)

    def test_foreign_database_rejected_without_modification(self):
        foreign = self.root/'foreign.sqlite'
        with closing(sqlite3.connect(foreign)) as conn:
            conn.execute('CREATE TABLE trading_orders(id)')
        before = foreign.read_bytes()
        with self.assertRaises(ValueError):
            ThemeArchive(replace(self.cfg, path=foreign), 'bad')
        self.assertEqual(foreign.read_bytes(), before)

    def test_archive_restart_preserves_first_receipt_and_detects_conflict(self):
        membership = SqliteMembershipSource(self.cfg).read()[0]
        first = signal(raw(), datetime.now(HK), membership)
        with_archive = ThemeArchive(self.cfg, 'one')
        with_archive.save_memberships((membership,))
        self.assertTrue(with_archive.save_signal(first))
        with_archive.close()
        recovered = self.archive(session='two')
        self.assertFalse(recovered.save_signal(replace(first, received_at=first.received_at+timedelta(seconds=5), snapshot_id=None)))
        saved = json.loads(recovered.connection.execute('SELECT payload FROM signals').fetchone()[0])
        self.assertEqual(saved['received_at'], first.received_at.isoformat())
        self.assertEqual(saved['snapshot_id'], membership.snapshot_id)
        self.assertEqual(recovered.connection.execute('SELECT session_id FROM signals').fetchone()[0], 'one')
        with self.assertRaises(ValueError):
            recovered.save_signal(replace(first, primary_label='changed'))
        self.assertIsNone(recovered.connection.execute("SELECT ended_at FROM sessions WHERE id='one'").fetchone()[0])

    def test_new_session_has_no_recovered_stale_cache(self):
        capture = self.capture()
        capture.request_refresh()
        until(lambda: bool(capture._cache))
        self.assertTrue(capture.close())
        restarted = self.capture()
        payload = raw()
        self.assertTrue(restarted.on_signal(payload, received_at=datetime.now(HK)))
        until(lambda: restarted.snapshot().persisted == 1)
        self.assertTrue(restarted.close())
        with closing(sqlite3.connect(self.cfg.path)) as conn:
            row = json.loads(conn.execute('SELECT payload FROM signals').fetchone()[0])
            self.assertIsNone(row['snapshot_id'])

    def test_archive_capacity_and_uncommitted_reference_fail_closed(self):
        archive = self.archive(replace(self.cfg, max_records=2))
        row = signal(raw(), datetime.now(HK), None)
        with self.assertRaises(ValueError):
            archive.save_signal(replace(row, snapshot_id='never-persisted'))
        self.assertTrue(archive.save_signal(row))
        with self.assertRaises(OverflowError):
            archive.save_memberships(SqliteMembershipSource(self.cfg).read())
        self.assertEqual(archive.connection.execute('SELECT count(*) FROM memberships').fetchone()[0], 0)

    def test_archive_binding_change_rejected(self):
        first = ThemeArchive(self.cfg, 'one')
        first.close()
        before = self.cfg.path.read_bytes()
        with self.assertRaises(ValueError):
            ThemeArchive(replace(self.cfg, source_version='changed'), 'two')
        self.assertEqual(self.cfg.path.read_bytes(), before)

    def test_second_archive_writer_cannot_open_the_active_database(self):
        self.archive()
        with self.assertRaises(sqlite3.OperationalError):
            ThemeArchive(self.cfg, 'concurrent-writer')

    def test_source_lock_timeout_is_bounded(self):
        with closing(sqlite3.connect(self.source)) as lock:
            lock.execute('BEGIN EXCLUSIVE')
            started = time.monotonic()
            with self.assertRaises(sqlite3.OperationalError):
                SqliteMembershipSource(self.cfg).read()
            self.assertLess(time.monotonic()-started, 1.)
            lock.rollback()

    def test_page_capacity_rolls_back_partial_membership_batch(self):
        archive = self.archive(replace(self.cfg, max_bytes=65536))
        members = tuple(Member(str(n), '科'*200) for n in range(128))
        row = replace(SqliteMembershipSource(self.cfg).read()[0], members=members)
        with self.assertRaises(sqlite3.OperationalError):
            archive.save_memberships((row,))
        self.assertEqual(archive.connection.execute('SELECT count(*) FROM memberships').fetchone()[0], 0)
        self.assertEqual(archive.count, 1)

    def test_source_failure_has_bounded_retry_backoff_and_still_records_signal(self):
        source = MagicMock()
        source.read.side_effect = OSError('mock unavailable')
        capture = self.capture(source=source)
        capture.request_refresh()
        until(lambda: capture.snapshot().source_failures == 2)
        self.assertFalse(capture.request_refresh())
        self.assertEqual(source.read.call_count, 2)
        self.assertTrue(capture.on_signal(raw(), received_at=datetime.now(HK)))
        until(lambda: capture.snapshot().persisted == 1)
        self.assertIsNone(capture.snapshot().error)

    def test_incomplete_scope_is_not_published_after_retry_failure(self):
        source = MagicMock()
        source.read.return_value = SqliteMembershipSource(self.cfg).read()[:1]
        capture = self.capture(source=source)
        capture.request_refresh()
        until(lambda: capture.snapshot().source_failures == 2)
        self.assertFalse(capture._cache)
        self.assertIsNone(capture.snapshot().error)

    def test_queue_full_never_waits_and_shutdown_drains(self):
        entered, release = threading.Event(), threading.Event()
        source = MagicMock()
        def blocked():
            entered.set()
            if not release.wait(3):
                raise TimeoutError('test worker release timed out')
            return SqliteMembershipSource(self.cfg).read()
        source.read.side_effect = blocked
        capture = self.capture(replace(self.cfg, queue_size=1), source)
        capture.request_refresh()
        self.assertTrue(entered.wait(2))
        try:
            started = time.monotonic()
            self.assertTrue(capture.on_signal(raw(), received_at=datetime.now(HK)))
            self.assertFalse(capture.on_signal(raw(), received_at=datetime.now(HK)))
            self.assertLess(time.monotonic()-started, .25)
            self.assertEqual(capture.snapshot().dropped, 1)
        finally:
            release.set()
        self.assertTrue(capture.close())
        with closing(sqlite3.connect(self.cfg.path)) as conn:
            row = json.loads(conn.execute('SELECT payload FROM signals').fetchone()[0])
            self.assertIsNone(row['snapshot_id'])  # later refresh completion cannot backfill
            status = json.loads(conn.execute('SELECT stats FROM sessions').fetchone()[0])
            self.assertEqual(status['dropped'], 1)
            self.assertFalse(status['running'])

    def test_write_failure_stops_capture_not_pipeline(self):
        capture = self.capture(replace(self.cfg, max_records=1))
        self.assertTrue(capture.on_signal(raw(), received_at=datetime.now(HK)))
        until(lambda: capture.snapshot().error is not None)
        self.assertFalse(capture.on_signal(raw(), received_at=datetime.now(HK)))
        self.assertTrue(capture.close())
        with closing(sqlite3.connect(self.cfg.path)) as conn:
            status = json.loads(conn.execute('SELECT stats FROM sessions').fetchone()[0])
            self.assertIn('OverflowError', status['error'])

    def test_capture_and_existing_diagnostic_contract_roundtrip(self):
        capture = self.capture()
        capture.request_refresh()
        until(lambda: bool(capture._cache))
        payload = raw()
        capture.on_signal(payload, received_at=datetime.now(HK))
        until(lambda: capture.snapshot().persisted == 1)
        self.assertTrue(capture.close())
        with closing(sqlite3.connect(self.cfg.path)) as conn:
            recorded = json.loads(conn.execute('SELECT payload FROM signals').fetchone()[0])
            self.assertIsNotNone(recorded['snapshot_id'])
            snapshots = [json.loads(row[0]) for row in conn.execute('SELECT payload FROM memberships')]
        path = self.root/'snapshots.json'
        path.write_text(json.dumps({'schema': 1, 'kind': 'THEME_MEMBERSHIP_DIAGNOSTIC', 'snapshots': snapshots}), encoding='utf-8')
        decoded, _ = load_memberships(path)
        decision = decide(SignalReference(recorded['event_id'], recorded['code'],
            datetime.fromisoformat(recorded['emitted_at']), recorded['primary_label']), decoded)
        self.assertEqual(decision.reason, 'MEMBERSHIP_SNAPSHOT_INCOMPLETE')
        self.assertFalse(decision.buy_authorized)

    def test_exact_pipeline_method_to_real_worker_and_archive(self):
        capture = self.capture()
        capture.request_refresh()
        until(lambda: bool(capture._cache))
        obj, quotes, _ = PipelineCaptureHookTest().pipeline(capture)
        asyncio.run(pipeline_method()(obj, quotes, {}))
        until(lambda: capture.snapshot().persisted == 1)
        self.assertTrue(capture.close())
        with closing(sqlite3.connect(self.cfg.path)) as conn:
            recorded = json.loads(conn.execute('SELECT payload FROM signals').fetchone()[0])
        self.assertIsNotNone(recorded['snapshot_id'])
        self.assertEqual(recorded['stage'], 'FIRST')
        self.assertEqual(recorded['receipt_basis'], 'INTERNAL_PIPELINE_RECEIPT_NOT_SDK_TICK')
        obj.socket_manager.emit_to_all.assert_awaited_once()
        obj.container.v2_runtime.ingest_legacy_signal.assert_called_once()
        obj._run_in_executor.assert_awaited_once()

    def test_explicit_factory_assembles_and_stops_capture(self):
        capture = configured_capture(str(self.source), {
            'RESEARCH_THEME_CAPTURE_ENABLED': '1',
            'RESEARCH_THEME_CAPTURE_PATH': str(self.cfg.path),
            'RESEARCH_THEME_CAPTURE_CODES': ','.join(self.cfg.codes),
            'RESEARCH_THEME_CAPTURE_SOURCE_VERSION': 'test-build-only',
        })
        self.addCleanup(capture.close)
        self.assertTrue(capture.request_refresh())
        until(lambda: bool(capture._cache))
        self.assertTrue(capture.close())
        self.assertFalse(capture.request_refresh())
        self.assertFalse(capture.on_signal(raw(), received_at=datetime.now(HK)))

    def test_closed_instance_cannot_restart_or_accept_more_work(self):
        capture = ThemeCapture(self.cfg)
        self.assertTrue(capture.close())
        capture.start()
        self.assertFalse(capture.snapshot().running)
        self.assertFalse(capture.request_refresh())
        self.assertFalse(self.cfg.path.exists())


def pipeline_method():
    """Execute the exact changed async method with mocked surrounding services."""
    path = ROOT/'simple_trade/core/pipeline/quote_pipeline.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'QuotePipeline')
    method = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == '_run_capital_trend_detector')
    module = ast.Module(body=[method], type_ignores=[])
    scope = {'List': List, 'Dict': Dict, 'datetime': datetime, 'timezone': timezone,
             'logging': logging, 'asyncio': asyncio, 'env_flag': lambda _: False}
    exec(compile(module, str(path), 'exec'), scope)
    return scope[method.name]


class PipelineCaptureHookTest(unittest.TestCase):
    def pipeline(self, capture=None):
        payload = raw()
        alert = SimpleNamespace(direction='RISING', is_strong_push=False, to_dict=lambda: dict(payload))
        detector = MagicMock(enabled=True)
        detector.evaluate.return_value = alert
        accumulator = MagicMock(enabled=True)
        accumulator.snapshot.return_value = {'stock_code': 'HK.00175'}
        v2 = MagicMock(started=True)
        container = SimpleNamespace(capital_trend_detector=detector, tick_capital_accumulator=accumulator,
            baseline_service=None, wechat_alert_service=None, v2_runtime=v2)
        quotes = [{'code': 'HK.00175', 'last_price': 16., 'prev_close': 15.6}]
        obj = SimpleNamespace(container=container, theme_capture=capture, _filter_trading_quotes=lambda _: quotes,
            _capital_inflow_market_gate=SimpleNamespace(evaluate=lambda _: {}),
            legacy_signal_policy=SimpleNamespace(action_enabled=True, observe_only=False),
            socket_manager=SimpleNamespace(emit_to_all=AsyncMock()), _run_in_executor=AsyncMock(),
            _persist_capital_trends=MagicMock())
        return obj, quotes, payload

    def test_callback_precedes_broadcast_and_payload_not_changed(self):
        capture = MagicMock()
        obj, quotes, payload = self.pipeline(capture)
        order = []
        capture.on_signal.side_effect = lambda *a, **kw: order.append('capture')
        async def broadcast(*args):
            order.append('broadcast')
        obj.socket_manager.emit_to_all.side_effect = broadcast
        asyncio.run(pipeline_method()(obj, quotes, {}))
        self.assertEqual(order, ['capture', 'broadcast'])
        capture.request_refresh.assert_called_once()
        captured = capture.on_signal.call_args
        self.assertIsNotNone(captured.kwargs['received_at'].tzinfo)
        self.assertEqual(captured.args[0], {**payload, 'advisory': False, 'legacy_observe_only': False})
        obj.container.v2_runtime.ingest_legacy_signal.assert_called_once()
        obj._run_in_executor.assert_awaited_once()

    def test_capture_exceptions_do_not_suppress_original_paths(self):
        capture = MagicMock()
        capture.request_refresh.side_effect = RuntimeError('mock refresh error')
        capture.on_signal.side_effect = RuntimeError('mock record error')
        obj, quotes, _ = self.pipeline(capture)
        with self.assertLogs(level='ERROR'):
            asyncio.run(pipeline_method()(obj, quotes, {}))
        obj.socket_manager.emit_to_all.assert_awaited_once()
        obj.container.v2_runtime.ingest_legacy_signal.assert_called_once()
        obj._run_in_executor.assert_awaited_once()

    def test_disabled_hook_preserves_behavior(self):
        obj, quotes, _ = self.pipeline()
        asyncio.run(pipeline_method()(obj, quotes, {}))
        obj.socket_manager.emit_to_all.assert_awaited_once()
        obj._run_in_executor.assert_awaited_once()

    def test_application_source_wires_optional_lifecycle_without_enabling(self):
        tree = ast.parse((ROOT/'simple_trade/app.py').read_text(encoding='utf-8'))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        pipeline_calls = [n for n in calls if isinstance(n.func, ast.Name) and n.func.id == 'QuotePipeline']
        self.assertEqual(len(pipeline_calls), 1)
        self.assertIn('theme_capture', {k.arg for k in pipeline_calls[0].keywords})
        self.assertTrue(any(isinstance(n.func, ast.Name) and n.func.id == 'configured_capture' for n in calls))
        self.assertTrue(any(isinstance(n.func, ast.Attribute) and n.func.attr == 'to_thread'
            and any(isinstance(a, ast.Attribute) and a.attr == 'close'
                    and isinstance(a.value, ast.Name) and a.value.id == 'theme_capture' for a in n.args) for n in calls))


if __name__ == '__main__':
    unittest.main()
