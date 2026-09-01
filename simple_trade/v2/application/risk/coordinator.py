"""Async decision-to-intent and risk assessment coordinator."""

import asyncio
from dataclasses import dataclass
import logging
from typing import Protocol

from ...domain.decisions import DecisionEvent
from ...domain.enums import EventType, RiskResult
from ...domain.events import RiskAssessedEvent
from ...domain.orders import RiskDecision, TradeIntent
from ...domain.risk import RiskContext
from ..event_bus import EventBus
from ..runtime_supervisor import RuntimeSupervisor
from .engine import RiskEngine
from .intent_factory import IntentFactory


class RiskContextPort(Protocol):
    async def fetch(self, stock_code: str, when) -> RiskContext: ...


class IntentStorePort(Protocol):
    async def record(self, intent: TradeIntent, risk: RiskDecision) -> bool: ...


@dataclass(frozen=True, slots=True)
class RiskCoordinatorStats:
    assessed: int = 0
    approved: int = 0
    rejected: int = 0
    skipped: int = 0
    dropped: int = 0
    failures: int = 0
    queue_size: int = 0
    queue_capacity: int = 0
    running: bool = False


class RiskCoordinator:
    _STOP = object()
    _EVENT_TYPES = (
        EventType.BUY_CONFIRMED,
        EventType.EXIT_RISK_CONFIRMED,
        EventType.ROTATION_PROPOSED,
        EventType.POSITION_EFFICIENCY_CHANGED,
    )

    def __init__(
        self,
        context: RiskContextPort,
        intent_factory: IntentFactory,
        engine: RiskEngine,
        store: IntentStorePort,
        *,
        schema_version: int,
        queue_capacity: int = 128,
    ) -> None:
        self._context = context
        self._factory = intent_factory
        self._engine = engine
        self._store = store
        self._schema_version = schema_version
        self._queue: asyncio.Queue[DecisionEvent | object] = asyncio.Queue(queue_capacity)
        self._bus: EventBus | None = None
        self._worker: asyncio.Task | None = None
        self._running = False
        self._accepting = False
        self._assessed = self._approved = self._rejected = 0
        self._skipped = self._dropped = self._failures = 0

    def register(self, bus: EventBus) -> None:
        if self._bus is not None and self._bus is not bus:
            raise RuntimeError("RiskCoordinator already registered")
        for event_type in self._EVENT_TYPES:
            bus.subscribe(event_type, self.on_decision)
        self._bus = bus

    def unregister(self) -> None:
        if self._bus is not None:
            for event_type in self._EVENT_TYPES:
                self._bus.unsubscribe(event_type, self.on_decision)
        self._bus = None

    async def start(self, supervisor: RuntimeSupervisor | None = None) -> None:
        if self._running:
            return
        self._running = self._accepting = True
        coroutine = self._run()
        self._worker = (
            asyncio.create_task(coroutine, name="v2-risk-coordinator")
            if supervisor is None
            else supervisor.create_task("v2-risk-coordinator", coroutine, critical=False)
        )

    async def stop(self, *, drain: bool = True) -> None:
        if not self._running:
            return
        self._accepting = False
        if drain:
            await self._queue.join()
        else:
            self._discard()
        await self._queue.put(self._STOP)
        if self._worker is not None:
            await asyncio.gather(self._worker, return_exceptions=True)
        self._worker = None
        self._running = False

    async def join(self) -> None:
        await self._queue.join()

    def on_decision(self, event) -> None:
        if not isinstance(event, DecisionEvent) or not self._accepting:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped += 1

    def snapshot(self) -> RiskCoordinatorStats:
        return RiskCoordinatorStats(
            assessed=self._assessed,
            approved=self._approved,
            rejected=self._rejected,
            skipped=self._skipped,
            dropped=self._dropped,
            failures=self._failures,
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
                if isinstance(item, DecisionEvent):
                    await self._process(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._failures += 1
                logging.exception("V2 risk assessment failed")
            finally:
                self._queue.task_done()

    async def _process(self, source: DecisionEvent) -> None:
        context = await self._context.fetch(source.stock_code, source.exchange_time)
        intent = self._factory.build(source, context)
        if intent is None:
            self._skipped += 1
            return
        risk = self._engine.evaluate(intent, context)
        inserted = await self._store.record(intent, risk)
        if not inserted:
            self._skipped += 1
            return
        assessed = RiskAssessedEvent(
            event_type=(
                EventType.RISK_APPROVED
                if risk.result is RiskResult.APPROVED
                else EventType.RISK_REJECTED
            ),
            stock_code=source.stock_code,
            exchange_time=risk.checked_at,
            received_time=risk.checked_at,
            source="v2.risk-coordinator",
            schema_version=self._schema_version,
            strategy_version=source.strategy_version,
            correlation_id=source.correlation_id,
            source_decision_event_id=source.event_id,
            intent=intent,
            risk=risk,
        )
        if self._bus is not None:
            self._bus.publish_nowait(assessed)
        self._assessed += 1
        self._approved += risk.result is RiskResult.APPROVED
        self._rejected += risk.result is not RiskResult.APPROVED

    def _discard(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            else:
                self._dropped += 1
                self._queue.task_done()
