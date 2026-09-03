import concurrent.futures
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import asyncio
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from simple_trade.v2.application.runtime import V2Runtime
from simple_trade.v2.config.models import V2Config
from simple_trade.v2.domain.decisions import DecisionEvent, NotificationEvent, StrategyState
from simple_trade.v2.domain.enums import (
    EventType,
    IntentType,
    NotificationChannel,
    OrderSide,
    PositionStatus,
    RiskResult,
    RuntimeMode,
    StrategyStatus,
)
from simple_trade.v2.domain.orders import OrderLeg, RiskDecision, TradeIntent
from simple_trade.v2.domain.positions import PositionState
from simple_trade.v2.infrastructure.sqlite_event_store import SqliteEventStore
from simple_trade.v2.infrastructure.sqlite_position_state_store import SqlitePositionStateStore
from simple_trade.v2.infrastructure.sqlite_state_store import StateConflictError
from simple_trade.v2.infrastructure.capital_seed_loader import CapitalSeedLoader
from simple_trade.v2.infrastructure.notifications import SqliteNotificationStore
from simple_trade.v2.infrastructure.risk import SqliteTradeIntentStore


ROOT = Path(__file__).resolve().parents[2]


def load_business_tables_class():
    path = ROOT / "simple_trade" / "database" / "models" / "business_tables.py"
    spec = importlib.util.spec_from_file_location("v2_test_business_tables", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load schema module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BusinessTables


BusinessTables = load_business_tables_class()
V2_TABLE_SQL = (
    BusinessTables.V2_DECISION_EVENTS_TABLE,
    BusinessTables.V2_STRATEGY_STATES_TABLE,
    BusinessTables.V2_POSITION_STATES_TABLE,
    BusinessTables.V2_TRADE_INTENTS_TABLE,
    BusinessTables.V2_NOTIFICATION_LOG_TABLE,
    BusinessTables.V2_OUTCOMES_TABLE,
    BusinessTables.TICK_CAPITAL_FLOW_TABLE,
    BusinessTables.TICKER_DATA_TABLE,
)


class InlineWriteQueue:
    is_running = True
    pending_count = 0

    def submit(self, operation, *args):
        future: concurrent.futures.Future = concurrent.futures.Future()
        try:
            future.set_result(operation(*args))
        except BaseException as error:
            future.set_exception(error)
        return future


class SqliteTestDatabase:
    def __init__(self, path: Path) -> None:
        self.path = str(path)
        self.write_queue = InlineWriteQueue()
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                for statement in V2_TABLE_SQL:
                    connection.execute(statement)
                for statement in BusinessTables.V2_INDEXES:
                    connection.execute(statement)

    @contextmanager
    def transaction(self):
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                cursor = connection.cursor()
                try:
                    yield cursor
                finally:
                    cursor.close()

    def execute_query(self, query: str, params: tuple | None = None) -> list:
        with closing(sqlite3.connect(self.path)) as connection:
            cursor = connection.execute(query, params or ())
            try:
                return cursor.fetchall()
            finally:
                cursor.close()


def make_event(event_id: str, strategy_version: str = "strategy-v1") -> DecisionEvent:
    now = datetime.now(timezone.utc)
    return DecisionEvent(
        event_id=event_id,
        event_type=EventType.BUY_CONFIRMED,
        stock_code="HK.00100",
        exchange_time=now,
        received_time=now,
        source="test",
        strategy_version=strategy_version,
        reason_code="FLOW_CONFIRMED",
        old_state=StrategyStatus.WATCHING.value,
        new_state=StrategyStatus.CONFIRMED.value,
        payload={"score": 82.5},
    )


def make_state(event: DecisionEvent, version: int) -> StrategyState:
    return StrategyState(
        stock_code=event.stock_code,
        strategy_version=event.strategy_version,
        status=StrategyStatus.CONFIRMED,
        version=version,
        last_event_id=event.event_id,
        updated_at=event.exchange_time,
        confirmed_price=356.6,
        metadata={"reason": "FLOW_CONFIRMED"},
    )


class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = SqliteTestDatabase(Path(self.temp.name) / "v2.db")
        self.store = SqliteEventStore(self.db, write_timeout=1)

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    async def test_append_is_idempotent_and_round_trips(self) -> None:
        event = make_event("event-1")
        self.assertTrue(await self.store.append(event))
        self.assertFalse(await self.store.append(event))

        loaded = await self.store.load(event.stock_code, event.strategy_version)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].event_id, event.event_id)
        self.assertEqual(loaded[0].payload["score"], 82.5)

    async def test_all_v2_tables_and_indexes_initialize(self) -> None:
        tables = {
            row[0]
            for row in self.db.execute_query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'v2_%'"
            )
        }
        self.assertEqual(
            tables,
            {
                "v2_decision_events",
                "v2_strategy_states",
                "v2_position_states",
                "v2_trade_intents",
                "v2_notification_log",
                "v2_outcomes",
            },
        )
        indexes = {
            row[0]
            for row in self.db.execute_query(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_v2_%'"
            )
        }
        self.assertEqual(len(indexes), len(BusinessTables.V2_INDEXES))

    async def test_event_and_state_are_atomic_on_conflict(self) -> None:
        first = make_event("event-1")
        self.assertTrue(await self.store.append_with_state(first, make_state(first, 1), 0))

        conflicting = make_event("event-2")
        with self.assertRaises(StateConflictError):
            await self.store.append_with_state(
                conflicting,
                make_state(conflicting, 2),
                expected_version=0,
            )

        loaded = await self.store.load(first.stock_code, first.strategy_version)
        self.assertEqual([event.event_id for event in loaded], ["event-1"])

    async def test_position_event_and_analytics_state_are_atomic(self) -> None:
        now = datetime.now(timezone.utc)
        event = DecisionEvent(
            event_id="position-event-1",
            event_type=EventType.POSITION_OPENED,
            stock_code="HK.00100",
            exchange_time=now,
            received_time=now,
            source="test",
            strategy_version="strategy-v1",
            old_state="FLAT",
            new_state="HOLDING",
            reason_code="BROKER_POSITION_OPENED",
        )
        state = PositionState(
            stock_code="HK.00100", strategy_version="strategy-v1",
            status=PositionStatus.HOLDING, version=1,
            last_event_id=event.event_id, updated_at=now, opened_at=now,
            cost_price=100, peak_price=101, trough_price=99,
            mfe_pct=1, mae_pct=-1, last_high_at=now,
        )
        self.assertTrue(await self.store.append_with_position_state(event, state, 0))

        loaded = await SqlitePositionStateStore(self.db, write_timeout=1).get(
            "HK.00100", "strategy-v1"
        )
        self.assertEqual(loaded.status, PositionStatus.HOLDING)
        self.assertEqual(loaded.mfe_pct, 1)

    async def test_trade_intent_and_notification_log_are_idempotent(self) -> None:
        source = make_event("risk-source-1")
        await self.store.append(source)
        intent = TradeIntent(
            source_event_id=source.event_id,
            intent_type=IntentType.BUY,
            created_at=source.exchange_time,
            mode=RuntimeMode.ALERT,
            buy_leg=OrderLeg(
                stock_code=source.stock_code,
                side=OrderSide.BUY,
                quantity=100,
                reference_price=10,
                lot_size=100,
            ),
        )
        risk = RiskDecision(
            intent_id=intent.intent_id,
            result=RiskResult.APPROVED,
            checked_at=source.exchange_time,
            reason_codes=("RISK_CHECKS_PASSED",),
        )
        intent_store = SqliteTradeIntentStore(self.db, write_timeout=1)
        self.assertTrue(await intent_store.record(intent, risk))
        self.assertFalse(await intent_store.record(intent, risk))

        notification = NotificationEvent(
            event_type=EventType.NOTIFICATION_REQUESTED,
            stock_code=source.stock_code,
            exchange_time=source.exchange_time,
            received_time=source.received_time,
            source="test",
            strategy_version=source.strategy_version,
            decision_event_id=source.event_id,
            channel=NotificationChannel.WEBSOCKET,
            idempotency_key="risk-source-1:websocket",
            title="V2 buy",
            message="approved",
            expires_at=source.exchange_time + timedelta(minutes=5),
        )
        notification_store = SqliteNotificationStore(self.db, write_timeout=1)
        self.assertTrue(await notification_store.claim(notification))
        self.assertFalse(await notification_store.claim(notification))
        await notification_store.mark(
            notification,
            status="DELIVERED",
            attempts=1,
            delivered_at=source.exchange_time,
        )
        row = self.db.execute_query(
            "SELECT status, attempt_count FROM v2_notification_log WHERE idempotency_key=?",
            (notification.idempotency_key,),
        )[0]
        self.assertEqual(row, ("DELIVERED", 1))

    async def test_capital_seed_loader_preserves_daily_cumulative_values(self) -> None:
        with self.db.transaction() as cursor:
            cursor.execute(
                "INSERT INTO tick_capital_flow "
                "(stock_code, trade_date, timestamp, cum_main_net, window_main_net, "
                "super_large_buy, super_large_sell, large_buy, large_sell, "
                "big_order_buy_ratio, cum_peak, cum_trough, big_buy_count, "
                "big_sell_count, last_seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "HK.00100",
                    "2026-08-31",
                    "2026-08-31 10:00:00",
                    8_000_000,
                    1_500_000,
                    5_000_000,
                    500_000,
                    4_000_000,
                    500_000,
                    0.9,
                    9_000_000,
                    -500_000,
                    5,
                    1,
                    88,
                ),
            )
        aggregates = await CapitalSeedLoader(self.db).load("2026-08-31")

        self.assertEqual(len(aggregates), 1)
        self.assertEqual(aggregates[0].cumulative_main_net, 8_000_000)
        self.assertEqual(aggregates[0].cumulative_peak, 9_000_000)
        self.assertEqual(aggregates[0].big_buy_count, 5)
        self.assertEqual(aggregates[0].last_sequence, 88)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = SqliteTestDatabase(Path(self.temp.name) / "runtime.db")

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    async def test_disabled_runtime_does_not_start_tasks(self) -> None:
        runtime = V2Runtime(self.db, V2Config(enabled=False))
        self.assertFalse(await runtime.start())
        self.assertFalse(runtime.snapshot().started)
        self.assertEqual(runtime.snapshot().tasks, ())
        await runtime.stop()

    async def test_shadow_runtime_starts_and_stops(self) -> None:
        runtime = V2Runtime(self.db, V2Config(enabled=True, mode=RuntimeMode.SHADOW))
        self.assertTrue(await runtime.start())
        self.assertTrue(runtime.snapshot().started)
        self.assertEqual(runtime.snapshot().tasks[0].name, "v2-event-bus")
        await runtime.stop()
        self.assertFalse(runtime.snapshot().started)

    async def test_ticker_replay_is_not_overwritten_by_legacy_capital_seed(self) -> None:
        hk = timezone(timedelta(hours=8))
        now = datetime.now(hk)
        trade_date = now.date().isoformat()
        trade_time = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        timestamp = int(now.timestamp() * 1000)
        with self.db.transaction() as cursor:
            cursor.execute(
                "INSERT INTO ticker_data "
                "(stock_code, price, volume, turnover, direction, timestamp, "
                "trade_date, sequence, trade_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "HK.00100", 100, 5_000, 500_000, "BUY", timestamp,
                    trade_date, 1, trade_time,
                ),
            )
            cursor.execute(
                "INSERT INTO tick_capital_flow "
                "(stock_code, trade_date, timestamp, cum_main_net, window_main_net, "
                "cum_peak, cum_trough, big_buy_count, big_sell_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "HK.00100", trade_date, now.isoformat(), -900_000, -900_000,
                    0, -900_000, 0, 1,
                ),
            )

        runtime = V2Runtime(self.db, V2Config(enabled=True, mode=RuntimeMode.SHADOW))
        await runtime.start()
        try:
            memory = runtime.feature_engine.capital.memory("HK.00100", now)
            self.assertEqual(memory.day_main_net, 500_000)
            self.assertEqual(memory.recent_15m_buy_events, 1)
        finally:
            await runtime.stop()

    async def test_ticker_ingress_is_safe_from_sdk_thread(self) -> None:
        runtime = V2Runtime(self.db, V2Config(enabled=True, mode=RuntimeMode.SHADOW))
        await runtime.start()
        try:
            worker = threading.Thread(
                target=runtime.ingest_ticker_records,
                args=(
                    "HK.00100",
                    [
                        {
                            "time": "2026-08-31 10:00:00",
                            "price": 356.6,
                            "volume": 100,
                            "ticker_direction": "BUY",
                            "sequence": 1,
                        }
                    ],
                ),
            )
            worker.start()
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())
            await asyncio.sleep(0.05)
            await runtime.event_bus.join()

            projection = runtime.market_projector.get("HK.00100")
            self.assertIsNotNone(projection)
            self.assertEqual(projection.last_tick.price, 356.6)
        finally:
            await runtime.stop()

    async def test_legacy_rally_is_published_as_structured_market_event(self) -> None:
        runtime = V2Runtime(self.db, V2Config(enabled=True, mode=RuntimeMode.SHADOW))
        event = runtime._legacy_signal_event({
            "stock_code": "HK.02706",
            "timestamp": "2026-09-01T10:57:00+08:00",
            "strategy_id": "absorption_scanner",
            "signal_type": "BUY",
            "alert_type": "rally",
            "duration_minutes": 6,
            "price_change_pct": 1.7,
            "cum_net_buy": 220.0,
            "position": "low",
            "price": 11.2,
        })

        self.assertEqual(event.event_type, EventType.LEGACY_SIGNAL_RECEIVED)
        self.assertEqual(event.payload["net_buy_amount"], 2_200_000)
        self.assertEqual(event.payload["signal_source"], "absorption_scanner")

    async def test_alert_mode_starts_without_execution(self) -> None:
        class ExecutionSpy:
            calls = 0

            async def submit(self, command):
                self.calls += 1

        spy = ExecutionSpy()
        runtime = V2Runtime(
            self.db,
            V2Config(
                enabled=True,
                mode=RuntimeMode.ALERT,
                notification_max_attempts=1,
            ),
            execution_port=spy,
        )
        self.assertTrue(await runtime.start())
        self.assertTrue(runtime.snapshot().risk.running)
        self.assertTrue(runtime.snapshot().notifications.running)
        await runtime.stop()
        self.assertEqual(spy.calls, 0)

    async def test_semi_mode_requires_explicit_execution_gate(self) -> None:
        runtime = V2Runtime(self.db, V2Config(enabled=True, mode=RuntimeMode.SEMI))
        with self.assertRaisesRegex(PermissionError, "execution blocked"):
            await runtime.start()
        self.assertEqual(runtime.snapshot().tasks, ())


if __name__ == "__main__":
    unittest.main()
