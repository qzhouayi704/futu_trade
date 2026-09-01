"""Async position reconciliation, efficiency, risk, and rotation coordinator."""

import asyncio
from dataclasses import replace
from datetime import timedelta
import logging
import threading
from typing import Protocol

from ...domain.decisions import DecisionEvent
from ...domain.enums import DecisionAction, EventType, PositionStatus
from ...domain.events import FeatureSnapshotEvent, PositionReconciledEvent
from ...domain.features import FeatureSnapshot
from ...domain.positions import PositionDecision, PositionSnapshot, PositionState
from ...infrastructure.sqlite_state_store import StateConflictError
from ..event_bus import EventBus
from ..runtime_supervisor import RuntimeSupervisor
from .decision_engine import PositionDecisionEngine
from .efficiency import PositionEfficiencyEngine
from .history import PositionFeatureHistory
from .models import PositionCoordinatorStats
from .rotation import RotationEvaluator
from .state_builder import (
    build_closed_transition,
    build_position_transition,
    evolve_state,
    rotation_evaluation,
    should_persist,
)


class PositionEventStorePort(Protocol):
    async def append_with_position_state(
        self,
        event: DecisionEvent,
        state: PositionState,
        expected_version: int,
    ) -> bool: ...


class PositionStateStorePort(Protocol):
    async def get(self, stock_code: str, strategy_version: str) -> PositionState | None: ...

    async def list_open(self, strategy_version: str) -> tuple[PositionState, ...]: ...


class CandidateReadPort(Protocol):
    def ranked(self, limit: int = 20): ...
class FeatureReadPort(Protocol):
    def latest(self, stock_code: str) -> FeatureSnapshot | None: ...
class PositionCoordinator:
    _STOP = object()
    PERSIST_INTERVAL = timedelta(seconds=60)
    def __init__(
        self,
        event_store: PositionEventStorePort,
        state_store: PositionStateStorePort,
        candidate_source: CandidateReadPort,
        feature_source: FeatureReadPort,
        *,
        strategy_version: str,
        schema_version: int = 1,
        queue_capacity: int = 256,
    ) -> None:
        if queue_capacity <= 0:
            raise ValueError("queue_capacity must be positive")
        self._event_store = event_store
        self._state_store = state_store
        self._candidates = candidate_source
        self._feature_source = feature_source
        self._strategy_version = strategy_version
        self._schema_version = schema_version
        self._efficiency = PositionEfficiencyEngine()
        self._decisions = PositionDecisionEngine()
        self._rotation = RotationEvaluator()
        self._queue: asyncio.Queue[
            FeatureSnapshotEvent | PositionReconciledEvent | object
        ] = asyncio.Queue(
            maxsize=queue_capacity
        )
        self._history = PositionFeatureHistory()
        self._positions: dict[str, PositionSnapshot] = {}
        self._states: dict[str, PositionState] = {}
        self._latest: dict[str, PositionDecision] = {}
        self._loaded = False
        self._bus: EventBus | None = None
        self._worker: asyncio.Task | None = None
        self._running = False
        self._accepting = False
        self._lock = threading.RLock()
        self._reconciliations = 0
        self._positions_processed = 0
        self._transitions = 0
        self._rotations = 0
        self._exits = 0
        self._closed = 0
        self._dropped = 0
        self._persistence_failures = 0
    def register(self, bus: EventBus) -> None:
        if self._bus is bus:
            return
        if self._bus is not None:
            raise RuntimeError("PositionCoordinator already registered")
        bus.subscribe(EventType.FEATURE_SNAPSHOT_READY, self.on_feature_snapshot)
        bus.subscribe(EventType.POSITION_RECONCILED, self.on_reconciliation)
        self._bus = bus
    def unregister(self) -> None:
        if self._bus is None:
            return
        self._bus.unsubscribe(EventType.FEATURE_SNAPSHOT_READY, self.on_feature_snapshot)
        self._bus.unsubscribe(EventType.POSITION_RECONCILED, self.on_reconciliation)
        self._bus = None
    async def start(self, supervisor: RuntimeSupervisor | None = None) -> None:
        if self._running:
            return
        self._running = True
        self._accepting = True
        coroutine = self._run()
        if supervisor is None:
            self._worker = asyncio.create_task(coroutine, name="v2-position-coordinator")
        else:
            self._worker = supervisor.create_task(
                "v2-position-coordinator", coroutine, critical=False
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

    async def join(self) -> None:
        await self._queue.join()

    def on_feature_snapshot(self, event) -> None:
        if not isinstance(event, FeatureSnapshotEvent):
            return
        self._history.on_feature(event)
        if not self._accepting:
            return
        with self._lock:
            held = event.stock_code in self._positions
        if not held:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            with self._lock:
                self._dropped += 1

    def on_reconciliation(self, event) -> None:
        if not isinstance(event, PositionReconciledEvent) or not self._accepting:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            with self._lock:
                self._dropped += 1

    def latest(self, stock_code: str) -> PositionDecision | None:
        with self._lock:
            return self._latest.get(stock_code.strip().upper())

    def snapshot(self) -> PositionCoordinatorStats:
        with self._lock:
            return PositionCoordinatorStats(
                reconciliations=self._reconciliations,
                positions_processed=self._positions_processed,
                transitions=self._transitions,
                rotations=self._rotations,
                exits=self._exits,
                closed=self._closed,
                dropped=self._dropped,
                persistence_failures=self._persistence_failures,
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
                if isinstance(item, PositionReconciledEvent):
                    await self._process(item)
                elif isinstance(item, FeatureSnapshotEvent):
                    await self._process_feature(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                with self._lock:
                    self._persistence_failures += 1
                logging.exception("V2 position reconciliation failed")
            finally:
                self._queue.task_done()

    async def _process(self, source: PositionReconciledEvent) -> None:
        await self._load_states()
        held_codes = {item.stock_code for item in source.reconciliation.positions}
        with self._lock:
            self._positions.update(
                {item.stock_code: item for item in source.reconciliation.positions}
            )
            if source.reconciliation.authoritative:
                for code in tuple(self._positions):
                    if code not in held_codes:
                        self._positions.pop(code, None)
        for position in source.reconciliation.positions:
            await self._process_position(source, position, held_codes)
        if source.reconciliation.authoritative:
            for code, state in tuple(self._states.items()):
                if state.status is not PositionStatus.CLOSED and code not in held_codes:
                    await self._close_missing(source, state)
        with self._lock:
            self._reconciliations += 1

    async def _process_feature(self, source: FeatureSnapshotEvent) -> None:
        await self._load_states()
        with self._lock:
            position = self._positions.get(source.stock_code)
            state = self._states.get(source.stock_code)
            held_codes = set(self._positions)
        if position is None:
            return
        if state is not None and source.exchange_time < state.updated_at:
            return
        await self._process_position(source, position, held_codes)

    async def _process_position(self, source, position, held_codes: set[str]) -> None:
        state = self._states.get(position.stock_code)
        if state is not None and state.status is PositionStatus.CLOSED:
            state = None
        history_feature, prices, candidate_features = self._history.context(
            position.stock_code
        )
        if isinstance(source, FeatureSnapshotEvent):
            feature = source.snapshot
        else:
            feature = history_feature or self._feature_source.latest(position.stock_code)
            if feature is not None and abs(
                (position.as_of - feature.computed_at).total_seconds()
            ) > 180:
                feature = None
        if feature is not None and feature.quote.last_price > 0:
            position = replace(
                position,
                as_of=max(position.as_of, feature.computed_at),
                current_price=feature.quote.last_price,
                peak_price=max(position.peak_price, feature.quote.last_price),
                lot_size=feature.quote.lot_size or position.lot_size,
            )
        efficiency = self._efficiency.calculate(position, state, feature, prices)
        evaluation = self._decisions.evaluate(position, state, efficiency, feature)
        analytical_state = evolve_state(position, state, efficiency, evaluation) if state else None

        if (
            evaluation.decision.action is DecisionAction.HOLD
            and evaluation.target_status is PositionStatus.STALLED
            and analytical_state is not None
        ):
            proposal = self._rotation.evaluate(
                position,
                analytical_state,
                efficiency,
                self._candidates.ranked(20),
                candidate_features,
                held_codes,
            )
            if proposal is not None:
                evaluation = rotation_evaluation(position, proposal)
                analytical_state = evolve_state(position, state, efficiency, evaluation)

        if should_persist(position.as_of, state, evaluation, self.PERSIST_INTERVAL):
            event, persisted = build_position_transition(
                source,
                position,
                state,
                efficiency,
                evaluation,
                strategy_version=self._strategy_version,
                schema_version=self._schema_version,
            )
            try:
                inserted = await self._event_store.append_with_position_state(
                    event, persisted, state.version if state else 0
                )
            except StateConflictError:
                state = await self._state_store.get(position.stock_code, self._strategy_version)
                with self._lock:
                    if state is not None:
                        self._states[position.stock_code] = state
                return
            if inserted:
                analytical_state = persisted
                self._publish(event)
                with self._lock:
                    self._transitions += 1
                    self._rotations += evaluation.decision.action is DecisionAction.ROTATE
                    self._exits += evaluation.decision.action is DecisionAction.EXIT
        if analytical_state is not None:
            with self._lock:
                self._states[position.stock_code] = analytical_state
                self._latest[position.stock_code] = evaluation.decision
                self._positions_processed += 1

    async def _close_missing(self, source, state: PositionState) -> None:
        event, closed = build_closed_transition(
            source, state, schema_version=self._schema_version
        )
        inserted = await self._event_store.append_with_position_state(
            event, closed, state.version
        )
        if inserted:
            self._publish(event)
            with self._lock:
                self._states[state.stock_code] = closed
                self._latest.pop(state.stock_code, None)
                self._closed += 1
                self._transitions += 1

    async def _load_states(self) -> None:
        if self._loaded:
            return
        states = await self._state_store.list_open(self._strategy_version)
        with self._lock:
            self._states.update({state.stock_code: state for state in states})
            self._loaded = True

    def _publish(self, event: DecisionEvent) -> None:
        if self._bus is not None:
            self._bus.publish_nowait(event)

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
