"""Asynchronous outcome projection with bounded ingress and throttled writes."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from threading import Lock
from typing import Mapping

from ...domain.decisions import DecisionEvent
from ...domain.enums import EventType
from ...domain.events import QuoteEvent
from ...domain.outcomes import OutcomeRecord
from ...ports.outcome_store import OutcomeStore
from ..event_bus import EventBus
from ..runtime_supervisor import RuntimeSupervisor
from .evaluator import OutcomeEvaluator


@dataclass(frozen=True, slots=True)
class OutcomeCoordinatorStats:
    active: int
    created: int
    evaluated: int
    persisted: int
    dropped: int
    failures: int
    queue_size: int
    queue_capacity: int
    running: bool


class OutcomeCoordinator:
    _STOP = object()
    _FLUSH_INTERVAL = timedelta(seconds=60)

    def __init__(
        self,
        store: OutcomeStore,
        *,
        strategy_version: str,
        queue_capacity: int = 512,
    ) -> None:
        self._store = store
        self._strategy_version = strategy_version
        self._evaluator = OutcomeEvaluator()
        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=queue_capacity)
        self._records: dict[str, OutcomeRecord] = {}
        self._by_stock: dict[str, set[str]] = defaultdict(set)
        self._last_persisted: dict[str, datetime] = {}
        self._worker: asyncio.Task | None = None
        self._bus: EventBus | None = None
        self._running = False
        self._accepting = False
        self._lock = Lock()
        self._created = 0
        self._evaluated = 0
        self._persisted = 0
        self._dropped = 0
        self._failures = 0

    def register(self, bus: EventBus) -> None:
        if self._bus is bus:
            return
        if self._bus is not None:
            raise RuntimeError("OutcomeCoordinator already registered")
        bus.subscribe(EventType.BUY_CONFIRMED, self.on_event)
        bus.subscribe(EventType.CANDIDATE_UPDATED, self.on_event)
        bus.subscribe(EventType.ROTATION_PROPOSED, self.on_event)
        bus.subscribe(EventType.QUOTE_UPDATED, self.on_event)
        self._bus = bus

    def unregister(self) -> None:
        if self._bus is None:
            return
        self._bus.unsubscribe(EventType.BUY_CONFIRMED, self.on_event)
        self._bus.unsubscribe(EventType.CANDIDATE_UPDATED, self.on_event)
        self._bus.unsubscribe(EventType.ROTATION_PROPOSED, self.on_event)
        self._bus.unsubscribe(EventType.QUOTE_UPDATED, self.on_event)
        self._bus = None

    async def start(self, supervisor: RuntimeSupervisor | None = None) -> None:
        if self._running:
            return
        for outcome in await self._store.load_active(self._strategy_version):
            self._index(outcome)
        self._running = True
        self._accepting = True
        coroutine = self._run()
        self._worker = (
            asyncio.create_task(coroutine, name="v2-outcomes")
            if supervisor is None
            else supervisor.create_task("v2-outcomes", coroutine, critical=False)
        )

    async def stop(self, *, drain: bool = True) -> None:
        if not self._running:
            return
        self._accepting = False
        if drain:
            await self._queue.join()
            await self._flush_all()
        else:
            self._discard_pending()
        await self._queue.put(self._STOP)
        if self._worker is not None:
            await asyncio.gather(self._worker, return_exceptions=True)
        self._worker = None
        self._running = False

    def on_event(self, event) -> None:
        if not self._accepting or not isinstance(event, (DecisionEvent, QuoteEvent)):
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            with self._lock:
                self._dropped += 1

    def snapshot(self) -> OutcomeCoordinatorStats:
        with self._lock:
            return OutcomeCoordinatorStats(
                active=len(self._records), created=self._created,
                evaluated=self._evaluated, persisted=self._persisted,
                dropped=self._dropped, failures=self._failures,
                queue_size=self._queue.qsize(), queue_capacity=self._queue.maxsize,
                running=self._running,
            )

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is self._STOP:
                    return
                if isinstance(item, DecisionEvent):
                    await self._create(item)
                elif isinstance(item, QuoteEvent):
                    await self._evaluate(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                with self._lock:
                    self._failures += 1
                logging.exception("V2 outcome projection failed")
            finally:
                self._queue.task_done()

    async def _create(self, event: DecisionEvent) -> None:
        outcome = self._from_decision(event)
        if outcome is None or outcome.decision_event_id in self._records:
            return
        self._index(outcome)
        await self._persist(outcome)
        with self._lock:
            self._created += 1

    async def _evaluate(self, event: QuoteEvent) -> None:
        ids = tuple(self._by_stock.get(event.stock_code, ()))
        for event_id in ids:
            before = self._records[event_id]
            after = self._evaluator.apply_quote(before, event.quote)
            if after == before:
                continue
            self._records[event_id] = after
            with self._lock:
                self._evaluated += 1
            if self._should_persist(before, after):
                await self._persist(after)

    async def _persist(self, outcome: OutcomeRecord) -> None:
        await self._store.upsert(outcome)
        at = outcome.evaluated_at or outcome.signal_time
        self._last_persisted[outcome.decision_event_id] = at
        with self._lock:
            self._persisted += 1

    async def _flush_all(self) -> None:
        for outcome in tuple(self._records.values()):
            await self._persist(outcome)

    def _index(self, outcome: OutcomeRecord) -> None:
        self._records[outcome.decision_event_id] = outcome
        self._by_stock[outcome.stock_code].add(outcome.decision_event_id)
        if outcome.control_stock_code:
            self._by_stock[outcome.control_stock_code].add(outcome.decision_event_id)

    def _should_persist(self, before: OutcomeRecord, after: OutcomeRecord) -> bool:
        critical = (
            before.time_to_1_5_seconds != after.time_to_1_5_seconds
            or before.time_to_3_seconds != after.time_to_3_seconds
            or before.time_to_5_seconds != after.time_to_5_seconds
            or before.close_return_pct != after.close_return_pct
            or before.next_day_return_pct != after.next_day_return_pct
        )
        if critical:
            return True
        last = self._last_persisted.get(after.decision_event_id, after.signal_time)
        return after.evaluated_at is not None and after.evaluated_at - last >= self._FLUSH_INTERVAL

    @staticmethod
    def _from_decision(event: DecisionEvent) -> OutcomeRecord | None:
        payload = event.payload
        if event.event_type in {EventType.BUY_CONFIRMED, EventType.CANDIDATE_UPDATED}:
            if (
                event.event_type is EventType.CANDIDATE_UPDATED
                and event.reason_code != "FIRST_STRONG_INFLOW_WATCH"
            ):
                return None
            feature = payload.get("feature_snapshot")
            quote = feature.get("quote") if isinstance(feature, Mapping) else None
            price = quote.get("last_price") if isinstance(quote, Mapping) else None
            stock_code = event.stock_code
            control_code = None
            control_price = None
        elif event.event_type is EventType.ROTATION_PROPOSED:
            rotation = payload.get("rotation")
            position = payload.get("position")
            if not isinstance(rotation, Mapping):
                return None
            stock_code = rotation.get("buy_stock_code")
            price = rotation.get("estimated_buy_price")
            control_code = event.stock_code
            control_price = position.get("current_price") if isinstance(position, Mapping) else None
        else:
            return None
        try:
            return OutcomeRecord(
                decision_event_id=event.event_id,
                stock_code=str(stock_code),
                strategy_version=event.strategy_version,
                signal_time=event.exchange_time,
                signal_price=float(price),
                control_stock_code=control_code,
                control_signal_price=float(control_price) if control_price is not None else None,
            )
        except (TypeError, ValueError):
            return None

    def _discard_pending(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            else:
                self._queue.task_done()
