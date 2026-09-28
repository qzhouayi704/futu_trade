"""Real application imports/ASGI lifespan; no live services or listening sockets."""
import asyncio
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import importlib
import importlib.abc
import importlib.machinery
import json
import logging
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import traceback
import warnings
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse
from urllib.request import url2pathname


ROOT = Path(__file__).resolve().parents[2]


class ImportBoundary(importlib.abc.MetaPathFinder):
    """Patch only config/log IO after their real module code has been imported."""
    def __init__(self, owner):
        self.owner = owner

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in ('simple_trade.config.config', 'simple_trade.utils.logger'):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        original = spec.loader
        owner = self.owner

        class Loader(importlib.abc.Loader):
            def create_module(self, module_spec):
                return original.create_module(module_spec)

            def exec_module(self, module):
                original.exec_module(module)
                if fullname.endswith('config.config'):
                    module.ConfigManager.load_config = classmethod(
                        lambda cls, config_path=None: module.Config(database_path=str(owner.source_path), auto_trade=False))
                else:
                    setup = module.setup_logging
                    module.setup_logging = lambda **kwargs: setup(
                        **{**kwargs, 'log_file': str(owner.root/'logs'/'backend.log')})

        spec.loader = Loader()
        return spec


@unittest.skipUnless(os.environ.get('THEME_CAPTURE_ISOLATED_SMOKE') == '1',
                     'run separately with scripts/run_theme_capture_smoke.sh test')
class ThemeCaptureLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if 'simple_trade' in sys.modules:
            raise RuntimeError('run lifecycle smoke in its own process before any application imports')
        cls.temp = tempfile.TemporaryDirectory(prefix='theme-lifecycle-')
        cls.root = Path(cls.temp.name).resolve()
        cls.source_path = cls.root/'initial.sqlite'
        cls.addClassCleanup(cls.temp.cleanup)
        cls.loop = asyncio.new_event_loop()  # create Windows internal socketpair before network guard
        cls.addClassCleanup(cls.loop.close)
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        original_cwd = Path.cwd()
        os.chdir(cls.root)
        cls.stack.callback(os.chdir, original_cwd)
        cls.violations = []
        safe_env = {k: v for k, v in os.environ.items() if k.upper() in
                    ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT', 'USERPROFILE', 'HOME')}
        safe_env.update(APPDATA=str(cls.root/'sdk-logs'), V2_ENABLED='0', FUTU_AUTO_TRADE='0',
                        RESEARCH_THEME_CAPTURE_ENABLED='0', CAPITAL_TICK_ACCUMULATOR_ENABLED='0',
                        CAPITAL_TREND_ALERT_ENABLED='0', LEGACY_SIGNAL_MODE='observe')
        cls.stack.enter_context(patch.dict(os.environ, safe_env, clear=True))
        # Linux Futu imports require the existing HOME value. Keep it unchanged,
        # but redirect actual SDK file logging into the fixture, as on Windows.
        (cls.root/'sdk-logs').mkdir()
        original_file_handler = logging.FileHandler.__init__

        def fixture_file_handler(handler, filename, *args, **kwargs):
            target = Path(filename).resolve()
            if not target.is_relative_to(cls.root):
                target = cls.root/'sdk-logs'/target.name
            original_file_handler(handler, target, *args, **kwargs)

        cls.stack.enter_context(patch.object(logging.FileHandler, '__init__', fixture_file_handler))
        cls.stack.enter_context(warnings.catch_warnings())
        warnings.simplefilter('ignore', DeprecationWarning)
        # urllib3 otherwise probes IPv6 by binding ::1 during import. Disable the
        # capability probe; the bind/connect guards remain strict and unchanged.
        cls.stack.enter_context(patch('socket.has_ipv6', False))
        for name in ('connect', 'connect_ex', 'bind'):
            cls.stack.enter_context(patch.object(socket.socket, name, cls.reject_network))
        cls.stack.enter_context(patch('socket.getaddrinfo', cls.reject_network))
        cls.stack.enter_context(patch('socket.create_connection', cls.reject_network))
        # Resolve the SDK's local crypto library before the blanket process guard:
        # Linux locates libgmp using read-only ldconfig. No broker module is loaded.
        importlib.import_module('Crypto.PublicKey.RSA')
        cls.stack.enter_context(patch('subprocess.check_output', return_value=b'isolated-smoke-fixture'))
        cls.stack.enter_context(patch('subprocess.Popen', side_effect=AssertionError('subprocess forbidden in smoke')))
        original_connect = sqlite3.connect

        def temporary_database_only(database, *args, **kwargs):
            name = str(database)
            if name != ':memory:':
                value = url2pathname(urlparse(name).path) if name.startswith('file:') else name
                if not Path(value).resolve().is_relative_to(cls.root):
                    cls.violations.append('database_outside_fixture')
                    raise AssertionError('database outside temporary fixture refused')
            return original_connect(database, *args, **kwargs)

        cls.stack.enter_context(patch('sqlite3.connect', temporary_database_only))
        finder = ImportBoundary(cls)
        sys.meta_path.insert(0, finder)
        cls.stack.callback(sys.meta_path.remove, finder)
        # Normal package import, including __init__, app, real router definitions and SDK imports.
        cls.app_module = importlib.import_module('simple_trade.app')
        cls.httpx = importlib.import_module('httpx')
        cls.capture_module = importlib.import_module('simple_trade.services.research.theme_capture.service')
        cls.db_type = importlib.import_module('tests.v2.test_stores_and_runtime').SqliteTestDatabase
        cls.stack.enter_context(patch.object(cls.app_module, 'print_status'))

    @classmethod
    def reject_network(cls, *args, **kwargs):
        cls.violations.append('network_attempt\n'+''.join(traceback.format_stack(limit=7)))
        raise AssertionError('network connection/listener forbidden in lifecycle smoke')

    @classmethod
    def tearDownClass(cls):
        cls.loop.run_until_complete(cls.loop.shutdown_asyncgens())
        cls.loop.run_until_complete(cls.loop.shutdown_default_executor())
        for logger in (logging.getLogger(), logging.getLogger('FTFileLog'), logging.getLogger('FTConsoleLog')):
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()

    def setUp(self):
        self.case_dir = self.root/self._testMethodName
        self.case_dir.mkdir()
        type(self).source_path = self.case_dir/'source.sqlite'
        self.db = self.db_type(self.source_path)
        self.db.database_path = self.db.path
        with closing(sqlite3.connect(self.db.path)) as conn:
            conn.executescript("CREATE TABLE stocks(id,code); CREATE TABLE plates(id,plate_code,plate_name); "
                "CREATE TABLE stock_plates(stock_id,plate_id); INSERT INTO stocks VALUES(1,'HK.00175'); "
                "INSERT INTO plates VALUES(1,'MOCK.AI','人工智能'); INSERT INTO stock_plates VALUES(1,1);")
        self.target = self.case_dir/'capture.sqlite'
        self.socket = SimpleNamespace(emit_to_all=AsyncMock())
        self.container = SimpleNamespace(
            config=self.app_module.ConfigManager.load_config(), db_manager=self.db,
            async_initialize_all=AsyncMock(), cleanup=MagicMock(),
            subscription_manager=MagicMock(), subscription_helper=MagicMock(),
            stock_data_service=MagicMock(), alert_service=MagicMock(), kline_service=MagicMock(),
            signal_tracker=MagicMock(), futu_client=MagicMock(), wechat_alert_service=None,
        )
        self.state = MagicMock()
        self.state.is_running.return_value = False
        self.state.get_stock_pool.return_value = {'stocks': []}
        self.pusher = SimpleNamespace(start=AsyncMock(return_value={'success': True}), stop=AsyncMock())
        self.captured_services = []
        self.background_tasks = []

    def tearDown(self):
        self.app_module.dependencies.reset()
        self.assertEqual(self.violations, [], 'forbidden boundary calls occurred')
        self.assertFalse(any(t.name == 'theme-evidence-capture' and t.is_alive() for t in threading.enumerate()))
        self.assertTrue(all(t.done() for t in self.background_tasks))

    async def eventually(self, predicate):
        for _ in range(300):
            if predicate():
                return
            await asyncio.sleep(.01)
        self.fail('bounded lifecycle wait timed out')

    def boundaries(self, *, enabled=False, bad_path=False, startup_error=False, normal_start=False):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            'RESEARCH_THEME_CAPTURE_ENABLED': '1' if enabled else '0',
            'RESEARCH_THEME_CAPTURE_PATH': str(self.source_path if bad_path else self.target),
            'RESEARCH_THEME_CAPTURE_CODES': 'HK.00175',
            'RESEARCH_THEME_CAPTURE_SOURCE_VERSION': 'isolated-lifecycle-fixture',
        }))
        stack.enter_context(patch.object(self.app_module, 'ServiceContainer', return_value=self.container))
        stack.enter_context(patch.object(self.app_module, 'get_state_manager', return_value=self.state))
        stack.enter_context(patch('simple_trade.websocket.get_socket_manager', return_value=self.socket))
        stack.enter_context(patch('simple_trade.services.core.AsyncQuotePusher', return_value=self.pusher))
        initialization = AsyncMock(side_effect=RuntimeError('fixture startup failure')) if startup_error else AsyncMock(return_value=normal_start)
        stack.enter_context(patch.object(self.app_module, 'initialize_system_data', initialization))
        real_factory = self.capture_module.configured_capture

        def factory(*args):
            capture = real_factory(*args)
            if capture is not None:
                self.captured_services.append(capture)
            return capture

        stack.enter_context(patch.object(self.capture_module, 'configured_capture', factory))
        real_create_task = asyncio.create_task

        async def idle_background():
            await asyncio.Event().wait()

        def background_boundary(coro, *, name=None, **kwargs):
            if name and name != 'quote_pusher_startup':
                coro.close()  # unrelated market/subscription schedulers must never run
                coro = idle_background()
            task = real_create_task(coro, name=name, **kwargs)
            if name:
                self.background_tasks.append(task)
            return task

        stack.enter_context(patch('asyncio.create_task', background_boundary))

    async def health(self):
        transport = self.httpx.ASGITransport(app=self.app_module.fastapi_app)
        async with self.httpx.AsyncClient(transport=transport, base_url='http://asgi-fixture') as client:
            response = await client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'framework': 'fastapi'})

    def test_startup_preserves_completed_klines_outside_trading_hours(self):
        initialization = importlib.import_module('simple_trade.core.initialization')
        helper = importlib.import_module('simple_trade.utils.market_helper')
        cases = (
            (datetime(2026, 9, 28, 13, 30), True),
            (datetime(2026, 9, 28, 17, 30), False),
            (datetime(2026, 9, 27, 13, 30), False),
            (datetime(2026, 9, 28, 2, 0), False),
        )
        for now, should_clean in cases:
            with self.subTest(now=now), ExitStack() as stack:
                container = MagicMock()
                container.futu_client.is_available.return_value = True
                container.stock_pool_service.init_stock_pool.return_value = {
                    'success': True, 'plates_count': 1, 'stocks_count': 1}
                state = MagicMock()
                state.get_stock_pool.return_value = {'initialized': True}
                state.is_running.return_value = True
                clock = stack.enter_context(patch.object(helper, 'datetime', wraps=datetime))
                clock.now.return_value = now
                stack.enter_context(patch.object(helper.MarketTimeHelper, 'is_trading_day', return_value=True))
                stack.enter_context(patch.object(initialization, '_sync_positions_on_startup', AsyncMock()))
                stack.enter_context(patch.object(initialization, '_pre_warm_price_position', AsyncMock()))
                self.assertTrue(self.loop.run_until_complete(initialization.initialize_system_data(container, state)))
                self.assertEqual(container.kline_service.clean_today_incomplete_kline.call_count, int(should_clean))
                container.subscription_helper.unsubscribe_all.assert_not_called()

    def test_default_off_real_asgi_start_stop_has_no_archive(self):
        self.boundaries(normal_start=True)
        async def run():
            async with self.app_module.fastapi_app.router.lifespan_context(self.app_module.fastapi_app):
                await self.eventually(lambda: self.pusher.start.await_count == 1)
                await self.health()
                self.assertIsNone(self.container.quote_pipeline.theme_capture)
                self.assertFalse(self.target.exists())
            self.pusher.stop.assert_awaited_once()
        self.loop.run_until_complete(run())
        self.container.cleanup.assert_called_once()
        self.assertEqual(self.captured_services, [])

    def test_enabled_fixture_runs_real_capture_and_closes_cleanly(self):
        self.boundaries(enabled=True)
        async def run():
            async with self.app_module.fastapi_app.router.lifespan_context(self.app_module.fastapi_app):
                capture = self.container.quote_pipeline.theme_capture
                self.assertIsInstance(capture, self.capture_module.ThemeCapture)
                capture.request_refresh()
                await self.eventually(lambda: bool(capture._cache))
                now = datetime.now(timezone.utc)
                payload = {'stock_code': 'HK.00175', 'timestamp': now.timestamp()}
                # Signal trade_date is Hong Kong local, independent of the test host timezone.
                from simple_trade.services.research.theme_capture.models import HK
                payload.update(trade_date=now.astimezone(HK).date().isoformat(), inflow_stage='FIRST',
                               inflow_sequence_no=1, plate_name='新能源车企')
                self.assertTrue(capture.on_signal(payload, received_at=now))
                await self.health()
            self.assertFalse(capture.snapshot().running)
        self.loop.run_until_complete(run())
        with closing(sqlite3.connect(self.target)) as conn:
            rows = conn.execute('SELECT ended_at,stats FROM sessions').fetchall()
            record = json.loads(conn.execute('SELECT payload FROM signals').fetchone()[0])
            self.assertEqual(len(rows), 1)
            self.assertIsNotNone(rows[0][0])
            self.assertIsNone(json.loads(rows[0][1])['error'])
            self.assertIsNotNone(record['snapshot_id'])

    def test_invalid_capture_configuration_does_not_break_health(self):
        self.boundaries(enabled=True, bad_path=True)
        async def run():
            async with self.app_module.fastapi_app.router.lifespan_context(self.app_module.fastapi_app):
                self.assertIsNone(self.container.quote_pipeline.theme_capture)
                await self.health()
        with self.assertLogs(level='ERROR'):
            self.loop.run_until_complete(run())
        self.assertFalse(self.target.exists())

    def test_startup_failure_still_closes_capture(self):
        self.boundaries(enabled=True, startup_error=True)
        async def run():
            with self.assertRaisesRegex(RuntimeError, 'fixture startup failure'):
                async with self.app_module.fastapi_app.router.lifespan_context(self.app_module.fastapi_app):
                    self.fail('startup must not yield')
        with self.assertLogs(level='ERROR'):
            self.loop.run_until_complete(run())
        self.assertEqual(len(self.captured_services), 1)
        self.assertFalse(self.captured_services[0].snapshot().running)
        self.container.cleanup.assert_called_once()

    def test_producer_final_signal_is_drained_before_capture_closes(self):
        self.boundaries(enabled=True, normal_start=True)
        received = []
        async def stop_producer():
            from simple_trade.services.research.theme_capture.models import HK
            now = datetime.now(HK)
            accepted = self.container.quote_pipeline.theme_capture.on_signal({
                'stock_code': 'HK.00175', 'timestamp': now.timestamp(), 'trade_date': now.date().isoformat(),
                'inflow_stage': 'EXPIRED', 'inflow_sequence_no': 1, 'plate_name': '新能源车企'}, received_at=now)
            received.append(accepted)
        self.pusher.stop.side_effect = stop_producer
        async def run():
            async with self.app_module.fastapi_app.router.lifespan_context(self.app_module.fastapi_app):
                await self.eventually(lambda: self.pusher.start.await_count == 1)
                await self.health()
        self.loop.run_until_complete(run())
        self.assertEqual(received, [True])
        with closing(sqlite3.connect(self.target)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM signals').fetchone()[0], 1)

    def test_producer_stop_failure_still_drains_capture_and_cleans_container(self):
        self.boundaries(enabled=True, normal_start=True)
        self.pusher.stop.side_effect = RuntimeError('fixture producer stop failed')
        async def run():
            async with self.app_module.fastapi_app.router.lifespan_context(self.app_module.fastapi_app):
                await self.eventually(lambda: self.pusher.start.await_count == 1)
                await self.health()
        with self.assertLogs(level='ERROR'):
            self.loop.run_until_complete(run())
        self.container.cleanup.assert_called_once()
        self.assertEqual(len(self.captured_services), 1)
        self.assertFalse(self.captured_services[0].snapshot().running)

    def test_real_quote_pipeline_callback_uses_configured_capture(self):
        self.boundaries(enabled=True)
        async def run():
            async with self.app_module.fastapi_app.router.lifespan_context(self.app_module.fastapi_app):
                pipeline = self.container.quote_pipeline
                pipeline.theme_capture.request_refresh()
                await self.eventually(lambda: bool(pipeline.theme_capture._cache))
                from simple_trade.services.research.theme_capture.models import HK
                now = datetime.now(HK)
                payload = {'stock_code': 'HK.00175', 'timestamp': now.timestamp(), 'trade_date': now.date().isoformat(),
                    'inflow_stage': 'FIRST', 'inflow_sequence_no': 1, 'plate_name': '新能源车企',
                    'direction': 'RISING', 'is_large_inflow': True}
                alert = SimpleNamespace(direction='RISING', is_strong_push=False, to_dict=lambda: dict(payload))
                self.container.capital_trend_detector = SimpleNamespace(enabled=True, evaluate=lambda *a, **kw: alert)
                self.container.tick_capital_accumulator = SimpleNamespace(enabled=True, snapshot=lambda code: {'stock_code': code})
                self.container.baseline_service = None
                quotes = [{'code': 'HK.00175', 'last_price': 16., 'prev_close': 15.6}]
                pipeline._filter_trading_quotes = lambda _: quotes
                pipeline._capital_inflow_market_gate.evaluate = lambda _: {}
                with patch.object(pipeline, '_run_in_executor', new_callable=AsyncMock) as persistence:
                    await pipeline._run_capital_trend_detector(quotes, {})
                    persistence.assert_awaited_once()
                await self.health()
            self.assertFalse(pipeline.theme_capture.snapshot().running)
        self.loop.run_until_complete(run())
        with closing(sqlite3.connect(self.target)) as conn:
            record = json.loads(conn.execute('SELECT payload FROM signals').fetchone()[0])
        self.assertIsNotNone(record['snapshot_id'])


if __name__ == '__main__':
    unittest.main()
