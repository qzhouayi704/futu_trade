"""有界、可观测的进程内事件总线。"""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import inspect
import logging
from typing import Protocol

from ..domain.enums import EventType
from ..domain.events import DomainEvent


EventHandler = Callable[[DomainEvent], Awaitable[None] | None]


class TaskSpawner(Protocol):
    def create_task(
        self,
        name: str,
        coroutine: Awaitable[object],
        *,
        critical: bool = False,
    ) -> asyncio.Task: ...


@dataclass(frozen=True, slots=True)
class EventBusStats:
    published: int
    dropped: int
    processed: int
    handler_failures: int
    queue_size: int
    queue_capacity: int
    running: bool


class EventBus:
    """单 worker 保证确定性顺序；队列满时立即拒绝，不阻塞行情回调。"""

    _STOP = object()

    def __init__(self, capacity: int = 10_000) -> None:
        if capacity <= 0:
            raise ValueError("EventBus capacity 必须大于 0")
        self._capacity = capacity
        self._queue: asyncio.Queue[DomainEvent | object] = asyncio.Queue(maxsize=capacity)
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._worker: asyncio.Task | None = None
        self._running = False
        self._accepting = False
        self._published = 0
        self._dropped = 0
        self._processed = 0
        self._handler_failures = 0

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        handlers = self._handlers[event_type]
        if handler not in handlers:
            handlers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        handlers = self._handlers.get(event_type)
        if handlers and handler in handlers:
            handlers.remove(handler)

    async def start(self, supervisor: TaskSpawner | None = None) -> None:
        if self._running:
            return
        self._running = True
        self._accepting = True
        if supervisor is None:
            self._worker = asyncio.create_task(self._run(), name="v2-event-bus")
        else:
            self._worker = supervisor.create_task(
                "v2-event-bus",
                self._run(),
                critical=True,
            )

    async def publish(self, event: DomainEvent) -> bool:
        return self.publish_nowait(event)

    def publish_nowait(self, event: DomainEvent) -> bool:
        if not isinstance(event, DomainEvent):
            raise TypeError("EventBus 只接受 DomainEvent")
        if not self._accepting:
            self._dropped += 1
            return False
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped += 1
            return False
        self._published += 1
        return True

    async def join(self) -> None:
        await self._queue.join()

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

    def snapshot(self) -> EventBusStats:
        return EventBusStats(
            published=self._published,
            dropped=self._dropped,
            processed=self._processed,
            handler_failures=self._handler_failures,
            queue_size=self._queue.qsize(),
            queue_capacity=self._capacity,
            running=self._running,
        )

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is self._STOP:
                    return
                if not isinstance(item, DomainEvent):
                    logging.error("V2 EventBus 收到非法对象: %s", type(item).__name__)
                    continue
                await self._dispatch(item)
                self._processed += 1
            finally:
                self._queue.task_done()

    async def _dispatch(self, event: DomainEvent) -> None:
        for handler in tuple(self._handlers.get(event.event_type, ())):
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:
                self._handler_failures += 1
                logging.exception(
                    "V2 事件处理失败: type=%s handler=%s event_id=%s",
                    event.event_type.value,
                    getattr(handler, "__name__", type(handler).__name__),
                    event.event_id,
                )

    def _discard_pending(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            else:
                self._dropped += 1
                self._queue.task_done()
