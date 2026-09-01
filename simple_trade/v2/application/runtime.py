"""V2 lifecycle, mode boundaries, and thread-safe market ingress."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...database.core.db_manager import DatabaseManager
from ..config.models import V2Config
from ..domain.enums import EventType, RuntimeMode
from ..domain.events import DomainEvent
from ..domain.events import QuoteEvent
from ..domain.events import PositionReconciledEvent
from ..infrastructure.capital_seed_loader import CapitalSeedLoader
from ..infrastructure.futu_market_adapter import FutuAdapterStats, FutuMarketAdapter
from ..infrastructure.feature_reference_loader import FeatureReferenceLoader
from ..infrastructure.sqlite_event_store import SqliteEventStore
from ..infrastructure.sqlite_state_store import SqliteStateStore
from ..infrastructure.sqlite_position_state_store import SqlitePositionStateStore
from ..infrastructure.broker.futu_position_provider import (
    FutuPositionProvider,
    FutuPositionSource,
)
from ..infrastructure.broker.futu_account_provider import FutuAccountProvider
from ..infrastructure.broker.frequency_guard_adapter import FrequencyGuardAdapter
from ..infrastructure.broker.risk_context_provider import BrokerRiskContextProvider
from ..infrastructure.notifications import SqliteNotificationStore, UnifiedNotifier
from ..infrastructure.outcomes import SqliteOutcomeStore
from ..infrastructure.risk import SqliteTradeIntentStore
from .event_bus import EventBus, EventBusStats
from .features.feature_engine import FeatureEngine, FeatureEngineStats
from .market_projector import MarketProjector, MarketProjectorStats
from .runtime_supervisor import RuntimeSupervisor, TaskSnapshot
from .strategy.coordinator import CandidateCoordinator
from .strategy.dual_track import DualTrackReport, DualTrackScoreboard
from .strategy.models import CandidateCoordinatorStats
from .positions.coordinator import PositionCoordinator
from .positions.models import PositionCoordinatorStats
from .notifications import (
    NotificationCoordinator,
    NotificationCoordinatorStats,
    NotificationFormatter,
)
from .risk import ExecutionModeGate, IntentFactory, RiskCoordinator, RiskCoordinatorStats, RiskEngine
from .outcomes import OutcomeCoordinator, OutcomeCoordinatorStats
from ..domain.risk import RiskLimits


@dataclass(frozen=True, slots=True)
class V2RuntimeSnapshot:
    enabled: bool
    started: bool
    mode: RuntimeMode
    strategy_version: str
    event_bus: EventBusStats
    adapter: FutuAdapterStats
    projector: MarketProjectorStats
    features: FeatureEngineStats
    candidates: CandidateCoordinatorStats
    positions: PositionCoordinatorStats
    risk: RiskCoordinatorStats
    notifications: NotificationCoordinatorStats
    outcomes: OutcomeCoordinatorStats
    dual_track: DualTrackReport
    tasks: tuple[TaskSnapshot, ...]


class V2Runtime:
    def __init__(
        self,
        db: "DatabaseManager",
        config: V2Config | None = None,
        *,
        position_source: FutuPositionSource | None = None,
        socket_manager=None,
        wechat_service=None,
        frequency_guard=None,
        execution_port=None,
    ) -> None:
        self.config = config or V2Config.from_env()
        self.event_bus = EventBus(self.config.event_bus_capacity)
        self.supervisor = RuntimeSupervisor()
        self.event_store = SqliteEventStore(db, self.config.write_timeout_seconds)
        self.state_store = SqliteStateStore(db, self.config.write_timeout_seconds)
        self.position_state_store = SqlitePositionStateStore(
            db, self.config.write_timeout_seconds
        )
        self.market_adapter = FutuMarketAdapter(
            strategy_version=self.config.strategy_version,
            schema_version=self.config.event_schema_version,
        )
        self.market_projector = MarketProjector()
        self.feature_engine = FeatureEngine(
            self.market_projector,
            strategy_version=self.config.strategy_version,
            schema_version=self.config.event_schema_version,
        )
        self.capital_seed_loader = CapitalSeedLoader(db)
        self.feature_reference_loader = FeatureReferenceLoader(db)
        self.dual_track = DualTrackScoreboard()
        self.candidate_coordinator = CandidateCoordinator(
            self.event_store,
            self.state_store,
            strategy_version=self.config.strategy_version,
            schema_version=self.config.event_schema_version,
            queue_capacity=max(100, self.config.event_bus_capacity // 5),
            observer=self.dual_track,
        )
        self.position_provider = FutuPositionProvider(position_source)
        self.account_provider = FutuAccountProvider(position_source)
        self.position_coordinator = PositionCoordinator(
            self.event_store,
            self.position_state_store,
            self.candidate_coordinator,
            self.feature_engine,
            strategy_version=self.config.strategy_version,
            schema_version=self.config.event_schema_version,
            queue_capacity=max(32, self.config.event_bus_capacity // 40),
        )
        limits = RiskLimits(
            max_positions=self.config.max_positions,
            max_single_position_ratio=self.config.max_single_position_ratio,
            min_cash_reserve_ratio=self.config.min_cash_reserve_ratio,
        )
        self.execution_gate = ExecutionModeGate(
            enabled=self.config.execution_enabled,
            confirmation=self.config.execution_confirmation,
        )
        self.execution_port = execution_port
        self.risk_context = BrokerRiskContextProvider(
            self.position_provider,
            self.account_provider,
        )
        guard_adapter = FrequencyGuardAdapter(frequency_guard) if frequency_guard else None
        self.risk_coordinator = RiskCoordinator(
            self.risk_context,
            IntentFactory(self.config.mode, limits),
            RiskEngine(limits, guard_adapter),
            SqliteTradeIntentStore(db, self.config.write_timeout_seconds),
            schema_version=self.config.event_schema_version,
            queue_capacity=max(32, self.config.event_bus_capacity // 40),
        )
        self.notification_coordinator = NotificationCoordinator(
            NotificationFormatter(expiry_seconds=self.config.notification_expiry_seconds),
            SqliteNotificationStore(db, self.config.write_timeout_seconds),
            UnifiedNotifier(socket_manager, wechat_service),
            max_attempts=self.config.notification_max_attempts,
            queue_capacity=max(32, self.config.event_bus_capacity // 20),
        )
        self.outcome_coordinator = OutcomeCoordinator(
            SqliteOutcomeStore(db, self.config.write_timeout_seconds),
            strategy_version=self.config.strategy_version,
            queue_capacity=max(128, self.config.event_bus_capacity // 10),
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = False

    async def start(self) -> bool:
        if not self.config.enabled:
            return False
        if self.config.mode in {RuntimeMode.SEMI, RuntimeMode.FULL}:
            self.execution_gate.require(self.config.mode)
            raise RuntimeError("V2 broker execution adapter 尚未启用")
        self._loop = asyncio.get_running_loop()
        self.market_projector.register(self.event_bus)
        self.feature_engine.register(self.event_bus)
        self.candidate_coordinator.register(self.event_bus)
        self.position_coordinator.register(self.event_bus)
        self.outcome_coordinator.register(self.event_bus)
        if self.config.mode is RuntimeMode.ALERT:
            self.risk_coordinator.register(self.event_bus)
            self.notification_coordinator.register(self.event_bus)
        try:
            await self.candidate_coordinator.start(self.supervisor)
            await self.position_coordinator.start(self.supervisor)
            await self.outcome_coordinator.start(self.supervisor)
            if self.config.mode is RuntimeMode.ALERT:
                await self.risk_coordinator.start(self.supervisor)
                await self.notification_coordinator.start(self.supervisor)
            await self.event_bus.start(self.supervisor)
            await self._restore_feature_references()
            await self._restore_capital()
        except Exception:
            await self.notification_coordinator.stop(drain=False)
            self.notification_coordinator.unregister()
            await self.risk_coordinator.stop(drain=False)
            self.risk_coordinator.unregister()
            await self.position_coordinator.stop(drain=False)
            self.position_coordinator.unregister()
            await self.outcome_coordinator.stop(drain=False)
            self.outcome_coordinator.unregister()
            await self.candidate_coordinator.stop(drain=False)
            self.candidate_coordinator.unregister()
            self.feature_engine.unregister()
            self.market_projector.unregister()
            self._loop = None
            raise
        self._started = True
        if self.position_provider.has_source:
            await self._refresh_broker_positions()
            self.supervisor.create_task(
                "v2-position-refresh",
                self._position_refresh_loop(),
                critical=False,
            )
        return True

    async def stop(self) -> None:
        self._started = False
        if self.event_bus.snapshot().running:
            await self.event_bus.join()
            await self.candidate_coordinator.stop(drain=True)
            await self.position_coordinator.stop(drain=True)
            await self.event_bus.join()
            await self.outcome_coordinator.stop(drain=True)
            await self.risk_coordinator.stop(drain=True)
            await self.event_bus.join()
            await self.notification_coordinator.stop(drain=True)
            await self.event_bus.stop(drain=True)
        else:
            await self.candidate_coordinator.stop(drain=True)
            await self.position_coordinator.stop(drain=True)
            await self.outcome_coordinator.stop(drain=True)
            await self.risk_coordinator.stop(drain=True)
            await self.notification_coordinator.stop(drain=True)
        self.notification_coordinator.unregister()
        self.risk_coordinator.unregister()
        self.position_coordinator.unregister()
        self.outcome_coordinator.unregister()
        self.candidate_coordinator.unregister()
        self.feature_engine.unregister()
        self.market_projector.unregister()
        await self.supervisor.stop()
        self._loop = None

    @property
    def started(self) -> bool:
        return self._started

    def ingest_quotes(self, rows: list[dict]) -> None:
        if not self._started:
            return
        received = datetime.now(timezone.utc)
        events: list[DomainEvent] = []
        for row in rows:
            events.extend(self.market_adapter.adapt_quote(row, received_time=received))
        self.feature_engine.stage_quote_universe(
            tuple(event.quote for event in events if isinstance(event, QuoteEvent))
        )
        self._publish_threadsafe(tuple(events))

    def ingest_ticker_records(self, stock_code: str, rows: list[dict]) -> None:
        if not self._started:
            return
        received = datetime.now(timezone.utc)
        events: list[DomainEvent] = []
        for row in rows:
            events.extend(
                self.market_adapter.adapt_ticker(
                    row,
                    stock_code=stock_code,
                    received_time=received,
                )
            )
        self._publish_threadsafe(tuple(events))

    def ingest_order_book(self, stock_code: str, data: object) -> None:
        if not self._started:
            return
        events = self.market_adapter.adapt_order_book(
            stock_code,
            data,
            received_time=datetime.now(timezone.utc),
        )
        self._publish_threadsafe(events)

    def ingest_legacy_signal(self, payload: dict) -> None:
        if self._started:
            self.dual_track.record_legacy_payload(payload)

    def ingest_positions(self, rows: dict | list[dict], quotes: list[dict]) -> None:
        if not self._started:
            return
        reconciliation = self.position_provider.adapt_rows(
            rows,
            quote_rows=quotes,
            as_of=datetime.now(timezone.utc),
        )
        self._publish_threadsafe((self._position_event(reconciliation),))

    def snapshot(self) -> V2RuntimeSnapshot:
        return V2RuntimeSnapshot(
            enabled=self.config.enabled,
            started=self._started,
            mode=self.config.mode,
            strategy_version=self.config.strategy_version,
            event_bus=self.event_bus.snapshot(),
            adapter=self.market_adapter.snapshot(),
            projector=self.market_projector.snapshot(),
            features=self.feature_engine.snapshot(),
            candidates=self.candidate_coordinator.snapshot(),
            positions=self.position_coordinator.snapshot(),
            risk=self.risk_coordinator.snapshot(),
            notifications=self.notification_coordinator.snapshot(),
            outcomes=self.outcome_coordinator.snapshot(),
            dual_track=self.dual_track.report(),
            tasks=self.supervisor.snapshots(),
        )

    def _publish_threadsafe(self, events: tuple[DomainEvent, ...]) -> None:
        loop = self._loop
        if not events or loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._publish_events, events)

    def _publish_events(self, events: tuple[DomainEvent, ...]) -> None:
        for event in events:
            self.event_bus.publish_nowait(event)

    async def _restore_capital(self) -> None:
        try:
            try:
                from zoneinfo import ZoneInfo

                trade_date = datetime.now(ZoneInfo("Asia/Hong_Kong")).date().isoformat()
            except Exception:
                trade_date = datetime.now(timezone.utc).date().isoformat()
            aggregates = await self.capital_seed_loader.load(trade_date)
            self.market_projector.restore_capital(aggregates)
            self.feature_engine.seed_capital(aggregates)
            if aggregates:
                logging.info("V2 restored tick capital snapshots: %s", len(aggregates))
        except Exception as error:
            logging.warning("V2 tick capital restore skipped: %s", error)

    async def _restore_feature_references(self) -> None:
        try:
            bars = await self.feature_reference_loader.load_daily_bars()
            self.feature_engine.seed_daily_bars(bars)
            if bars:
                logging.info("V2 restored daily feature bars: %s", len(bars))
        except Exception as error:
            logging.warning("V2 daily feature reference restore skipped: %s", error)
        try:
            baselines = await self.feature_reference_loader.load_capital_baselines()
            self.feature_engine.seed_capital_baselines(baselines)
            if baselines:
                logging.info("V2 restored capital baselines: %s", len(baselines))
        except Exception as error:
            logging.warning("V2 capital baseline restore skipped: %s", error)

    async def _refresh_broker_positions(self) -> None:
        reconciliation = await self.position_provider.fetch()
        self.event_bus.publish_nowait(self._position_event(reconciliation))

    async def _position_refresh_loop(self) -> None:
        while self._started:
            await asyncio.sleep(60)
            if self._started:
                await self._refresh_broker_positions()

    def _position_event(self, reconciliation) -> PositionReconciledEvent:
        now = datetime.now(timezone.utc)
        return PositionReconciledEvent(
            event_type=EventType.POSITION_RECONCILED,
            stock_code="PORTFOLIO",
            exchange_time=reconciliation.as_of,
            received_time=now,
            source="v2.futu-position-provider",
            schema_version=self.config.event_schema_version,
            strategy_version=self.config.strategy_version,
            reconciliation=reconciliation,
        )
