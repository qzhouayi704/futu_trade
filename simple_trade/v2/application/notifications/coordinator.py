"""Asynchronous idempotent notification formatting and delivery."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Protocol

from ...domain.decisions import NotificationEvent
from ...domain.enums import EventType, NotificationDeliveryResult
from ...domain.events import RiskAssessedEvent
from ..event_bus import EventBus
from ..runtime_supervisor import RuntimeSupervisor
from .formatter import NotificationFormatter


class NotificationStorePort(Protocol):
    async def claim(self, event: NotificationEvent) -> bool: ...

    async def mark(self, event: NotificationEvent, **kwargs) -> None: ...


class UnifiedNotifierPort(Protocol):
    async def send(
        self, event: NotificationEvent, *, attempt: int
    ) -> NotificationDeliveryResult: ...


@dataclass(frozen=True, slots=True)
class NotificationCoordinatorStats:
    requested: int = 0
    delivered: int = 0
    collapsed: int = 0
    expired: int = 0
    failed: int = 0
    retried: int = 0
    dropped: int = 0
    queue_size: int = 0
    queue_capacity: int = 0
    running: bool = False


class NotificationCoordinator:
    _STOP = object()

    def __init__(
        self,
        formatter: NotificationFormatter,
        store: NotificationStorePort,
        notifier: UnifiedNotifierPort,
        *,
        max_attempts: int,
        queue_capacity: int = 256,
        retry_delays: tuple[float, ...] = (0.0, 1.0, 5.0),
    ) -> None:
        self._formatter = formatter
        self._store = store
        self._notifier = notifier
        self._max_attempts = max_attempts
        self._retry_delays = retry_delays or (0.0,)
        self._queue: asyncio.Queue[NotificationEvent | object] = asyncio.Queue(queue_capacity)
        self._bus: EventBus | None = None
        self._worker: asyncio.Task | None = None
        self._running = self._accepting = False
        self._requested = self._delivered = self._collapsed = 0
        self._expired = self._failed = self._retried = self._dropped = 0

    def register(self, bus: EventBus) -> None:
        if self._bus is not None and self._bus is not bus:
            raise RuntimeError("NotificationCoordinator already registered")
        bus.subscribe(EventType.RISK_APPROVED, self.on_risk)
        bus.subscribe(EventType.RISK_REJECTED, self.on_risk)
        bus.subscribe(EventType.NOTIFICATION_REQUESTED, self.on_notification)
        self._bus = bus

    def unregister(self) -> None:
        if self._bus is not None:
            self._bus.unsubscribe(EventType.RISK_APPROVED, self.on_risk)
            self._bus.unsubscribe(EventType.RISK_REJECTED, self.on_risk)
            self._bus.unsubscribe(EventType.NOTIFICATION_REQUESTED, self.on_notification)
        self._bus = None

    async def start(self, supervisor: RuntimeSupervisor | None = None) -> None:
        if self._running:
            return
        self._running = self._accepting = True
        coroutine = self._run()
        self._worker = (
            asyncio.create_task(coroutine, name="v2-notification-coordinator")
            if supervisor is None
            else supervisor.create_task(
                "v2-notification-coordinator", coroutine, critical=False
            )
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

    def on_risk(self, event) -> None:
        if not isinstance(event, RiskAssessedEvent) or self._bus is None:
            return
        for notification in self._formatter.build(event):
            self._bus.publish_nowait(notification)

    def on_notification(self, event) -> None:
        if not isinstance(event, NotificationEvent) or not self._accepting:
            return
        try:
            self._queue.put_nowait(event)
            self._requested += 1
        except asyncio.QueueFull:
            self._dropped += 1

    def snapshot(self) -> NotificationCoordinatorStats:
        return NotificationCoordinatorStats(
            requested=self._requested,
            delivered=self._delivered,
            collapsed=self._collapsed,
            expired=self._expired,
            failed=self._failed,
            retried=self._retried,
            dropped=self._dropped,
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
                if isinstance(item, NotificationEvent):
                    await self._deliver(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._failed += 1
                logging.exception("V2 notification delivery failed")
            finally:
                self._queue.task_done()

    async def _deliver(self, event: NotificationEvent) -> None:
        if not await self._store.claim(event):
            self._collapsed += 1
            return
        for attempt in range(1, self._max_attempts + 1):
            now = datetime.now(timezone.utc)
            if event.expires_at is not None and now >= event.expires_at:
                await self._store.mark(
                    event, status="EXPIRED", attempts=attempt - 1, error="expired"
                )
                self._expired += 1
                return
            outcome = await self._notifier.send(event, attempt=attempt)
            if outcome is NotificationDeliveryResult.DELIVERED:
                await self._store.mark(
                    event,
                    status="DELIVERED",
                    attempts=attempt,
                    delivered_at=now,
                )
                self._delivered += 1
                return
            if outcome is NotificationDeliveryResult.COLLAPSED:
                await self._store.mark(event, status="COLLAPSED", attempts=attempt)
                self._collapsed += 1
                return
            if attempt < self._max_attempts:
                self._retried += 1
                await self._store.mark(
                    event, status="RETRYING", attempts=attempt, error="channel failed"
                )
                delay = self._retry_delays[min(attempt, len(self._retry_delays) - 1)]
                if delay > 0:
                    await asyncio.sleep(delay)
        await self._store.mark(
            event,
            status="FAILED",
            attempts=self._max_attempts,
            error="max attempts reached",
        )
        self._failed += 1

    def _discard(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            else:
                self._dropped += 1
                self._queue.task_done()
