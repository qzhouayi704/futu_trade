"""Asynchronous shadow coordinator for candidate ranking and state persistence."""

import asyncio
from datetime import datetime
import logging
import threading
from typing import Protocol

from ...domain.candidates import TradeCandidate
from ...domain.decisions import DecisionEvent, StrategyState
from ...domain.enums import CandidateStatus, EventType, StrategyStatus
from ...domain.events import FeatureSnapshotEvent
from ...domain.serialization import to_primitive
from ...infrastructure.sqlite_state_store import StateConflictError
from ..event_bus import EventBus
from ..runtime_supervisor import RuntimeSupervisor
from .candidate_scorer import CandidateScorer
from .decision_builder import build_transition
from .models import CandidateCoordinatorStats
from .portfolio import StrategyPortfolio
from .state_machine import CandidateStateMachine
from .universe import UniversePolicy


class EventStorePort(Protocol):
    async def append(self, event: DecisionEvent) -> bool: ...

    async def append_with_state(
        self,
        event: DecisionEvent,
        state: StrategyState,
        expected_version: int,
    ) -> bool: ...


class StateStorePort(Protocol):
    async def get(self, stock_code: str, strategy_version: str) -> StrategyState | None: ...


class DecisionObserver(Protocol):
    def record_v2(self, event: DecisionEvent) -> None: ...


class CandidateCoordinator:
    _STOP = object()

    def __init__(
        self,
        event_store: EventStorePort,
        state_store: StateStorePort,
        *,
        strategy_version: str,
        schema_version: int = 1,
        queue_capacity: int = 2_000,
        observer: DecisionObserver | None = None,
    ) -> None:
        if queue_capacity <= 0:
            raise ValueError("queue_capacity must be positive")
        self._event_store = event_store
        self._state_store = state_store
        self._strategy_version = strategy_version
        self._schema_version = schema_version
        self._queue: asyncio.Queue[FeatureSnapshotEvent | object] = asyncio.Queue(
            maxsize=queue_capacity
        )
        self._universe = UniversePolicy()
        self._scorer = CandidateScorer()
        self._machine = CandidateStateMachine()
        self._portfolio = StrategyPortfolio()
        self._observer = observer
        self._bus: EventBus | None = None
        self._worker: asyncio.Task | None = None
        self._accepting = False
        self._running = False
        self._states: dict[str, StrategyState] = {}
        self._latest: dict[str, TradeCandidate] = {}
        self._lock = threading.RLock()
        self._queued = 0
        self._dropped = 0
        self._processed = 0
        self._transitions = 0
        self._rejections_persisted = 0
        self._persistence_failures = 0
        self._conflicts = 0
        self._last_rejections: dict[str, tuple[tuple[str, ...], datetime]] = {}

    def register(self, bus: EventBus) -> None:
        if self._bus is bus:
            return
        if self._bus is not None:
            raise RuntimeError("CandidateCoordinator already registered")
        bus.subscribe(EventType.FEATURE_SNAPSHOT_READY, self.on_feature_snapshot)
        self._bus = bus

    def unregister(self) -> None:
        if self._bus is None:
            return
        self._bus.unsubscribe(EventType.FEATURE_SNAPSHOT_READY, self.on_feature_snapshot)
        self._bus = None

    async def start(self, supervisor: RuntimeSupervisor | None = None) -> None:
        if self._running:
            return
        self._running = True
        self._accepting = True
        coroutine = self._run()
        if supervisor is None:
            self._worker = asyncio.create_task(coroutine, name="v2-strategy-candidates")
        else:
            self._worker = supervisor.create_task(
                "v2-strategy-candidates",
                coroutine,
                critical=False,
            )

    async def stop(self, *, drain: bool = True) -> None:
        if not self._running:
            return
        self._accepting = False
        if drain:
            await self._queue.join()
        else:
            self._discard_pending()
        await self._queue.put(self._STOP)
        if self._worker is not None:
            await asyncio.gather(self._worker, return_exceptions=True)
        self._worker = None
        self._running = False

    def on_feature_snapshot(self, event) -> None:
        if not isinstance(event, FeatureSnapshotEvent) or not self._accepting:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            with self._lock:
                self._dropped += 1
        else:
            with self._lock:
                self._queued += 1

    def latest(self, stock_code: str) -> TradeCandidate | None:
        with self._lock:
            return self._latest.get(stock_code.strip().upper())

    def ranked(self, limit: int = 20) -> tuple[TradeCandidate, ...]:
        if limit <= 0:
            return ()
        with self._lock:
            return tuple(
                sorted(
                    self._latest.values(),
                    key=lambda item: (item.score, item.as_of),
                    reverse=True,
                )[:limit]
            )

    def snapshot(self) -> CandidateCoordinatorStats:
        with self._lock:
            return CandidateCoordinatorStats(
                queued=self._queued,
                dropped=self._dropped,
                processed=self._processed,
                transitions=self._transitions,
                rejections_persisted=self._rejections_persisted,
                persistence_failures=self._persistence_failures,
                conflicts=self._conflicts,
                queue_size=self._queue.qsize(),
                queue_capacity=self._queue.maxsize,
                running=self._running,
            )

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is self._STOP:
                    return
                if isinstance(item, FeatureSnapshotEvent):
                    await self._process(item)
                    with self._lock:
                        self._processed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                with self._lock:
                    self._persistence_failures += 1
                logging.exception("V2 candidate snapshot processing failed")
            finally:
                self._queue.task_done()

    async def _process(self, source: FeatureSnapshotEvent) -> None:
        snapshot = source.snapshot
        universe = self._universe.evaluate(snapshot)
        score = self._scorer.score(snapshot)
        portfolio = self._portfolio.evaluate(snapshot, universe, score)
        state = await self._state_for(snapshot.stock_code)
        proposal = self._machine.evaluate(snapshot, state, universe)

        status = state.status if state is not None else StrategyStatus.IDLE
        if proposal is not None:
            event, new_state = build_transition(
                source,
                state,
                proposal,
                score,
                universe,
                portfolio,
                strategy_version=self._strategy_version,
                schema_version=self._schema_version,
            )
            try:
                inserted = await self._event_store.append_with_state(
                    event,
                    new_state,
                    state.version if state is not None else 0,
                )
            except StateConflictError:
                with self._lock:
                    self._conflicts += 1
                    self._states.pop(snapshot.stock_code, None)
                state = await self._state_for(snapshot.stock_code, force_reload=True)
                retry = self._machine.evaluate(snapshot, state, universe)
                if retry is None:
                    proposal = None
                else:
                    event, new_state = build_transition(
                        source,
                        state,
                        retry,
                        score,
                        universe,
                        portfolio,
                        strategy_version=self._strategy_version,
                        schema_version=self._schema_version,
                    )
                    inserted = await self._event_store.append_with_state(
                        event, new_state, state.version if state is not None else 0
                    )
                    proposal = retry
            if proposal is not None and inserted:
                state = new_state
                status = new_state.status
                with self._lock:
                    self._states[snapshot.stock_code] = new_state
                    self._transitions += 1
                if self._observer is not None:
                    self._observer.record_v2(event)
                if self._bus is not None:
                    self._bus.publish_nowait(event)

        if proposal is None and status is StrategyStatus.IDLE:
            await self._persist_rejection(source, universe, score, portfolio)

        idle_reasons = (
            self._machine.setup_blockers(snapshot, universe)
            if status is StrategyStatus.IDLE
            else ()
        )

        candidate = TradeCandidate(
            stock_code=snapshot.stock_code,
            as_of=snapshot.computed_at,
            status=self._candidate_status(status),
            score=portfolio.ranking_score,
            quality=score.quality,
            reason_codes=(
                (proposal.reason_code,)
                if proposal is not None
                else idle_reasons or score.reason_codes or ("NO_TRANSITION",)
            ),
            invalidation_conditions=(
                "15m main flow turns negative or sell amount offsets at least 80% of buys",
                "price falls 1% below watch price or loses VWAP/acceptance",
                "data quality becomes invalid",
            ),
            confirmation_price=(state.confirmed_price if state is not None else None),
            strategy_sources=portfolio.strategy_sources,
            consensus_count=portfolio.consensus_count,
            alert_eligible=(
                proposal.alert_eligible
                if proposal is not None
                else bool(state.metadata.get("alert_eligible", True))
                if state is not None
                else True
            ),
        )
        with self._lock:
            self._latest[snapshot.stock_code] = candidate

    async def _persist_rejection(self, source, universe, score, portfolio) -> None:
        reasons = list(self._machine.setup_blockers(source.snapshot, universe))
        if not reasons:
            reasons.extend(score.reason_codes)
        fingerprint = tuple(dict.fromkeys(reasons))
        if not fingerprint:
            return
        previous = self._last_rejections.get(source.stock_code)
        if previous is not None:
            previous_reasons, previous_at = previous
            elapsed = (source.exchange_time - previous_at).total_seconds()
            if previous_reasons == fingerprint and elapsed < 300:
                return
        event = DecisionEvent(
            event_type=EventType.CANDIDATE_REJECTED,
            stock_code=source.stock_code,
            exchange_time=source.exchange_time,
            received_time=source.received_time,
            source="v2.candidate-coordinator",
            schema_version=self._schema_version,
            strategy_version=self._strategy_version,
            sequence=source.sequence,
            correlation_id=source.correlation_id,
            old_state=StrategyStatus.IDLE.value,
            new_state=StrategyStatus.IDLE.value,
            reason_code=fingerprint[0],
            payload={
                "shadow_only": True,
                "reason_codes": fingerprint,
                "universe": to_primitive(universe),
                "candidate_score": to_primitive(score),
                "strategy_portfolio": to_primitive(portfolio),
                "feature_snapshot": to_primitive(source.snapshot),
            },
        )
        if await self._event_store.append(event):
            self._last_rejections[source.stock_code] = (fingerprint, source.exchange_time)
            with self._lock:
                self._rejections_persisted += 1

    async def _state_for(
        self,
        stock_code: str,
        *,
        force_reload: bool = False,
    ) -> StrategyState | None:
        with self._lock:
            if not force_reload and stock_code in self._states:
                return self._states[stock_code]
        state = await self._state_store.get(stock_code, self._strategy_version)
        if state is not None:
            with self._lock:
                self._states[stock_code] = state
        return state

    @staticmethod
    def _candidate_status(status: StrategyStatus) -> CandidateStatus:
        return {
            StrategyStatus.IDLE: CandidateStatus.OBSERVE,
            StrategyStatus.SETUP: CandidateStatus.SETUP,
            StrategyStatus.WATCHING: CandidateStatus.OBSERVE,
            StrategyStatus.CONFIRMED: CandidateStatus.BUY_CONFIRMED,
            StrategyStatus.INVALIDATED: CandidateStatus.BUY_INVALIDATED,
        }[status]

    def _discard_pending(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            else:
                with self._lock:
                    self._dropped += 1
                self._queue.task_done()
