"""Non-blocking candidate market-data subscription coordination."""

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Protocol

from ..domain.decisions import DecisionEvent
from ..domain.enums import EventType, StrategyStatus
from .event_bus import EventBus
from .runtime_supervisor import RuntimeSupervisor


class CandidateSubscriptionPort(Protocol):
    def subscribe_candidate(self, stock_code: str) -> bool: ...

    def protect_candidates(self, stock_codes: tuple[str, ...]) -> None: ...


@dataclass(frozen=True, slots=True)
class CandidateSubscriptionStats:
    requested: int
    completed: int
    failed: int
    deduplicated: int
    queue_size: int
    running: bool


class CandidateSubscriptionCoordinator:
    _STOP = object()

    def __init__(
        self,
        port: CandidateSubscriptionPort | None,
        *,
        queue_capacity: int = 100,
        cooldown_seconds: int = 300,
    ) -> None:
        self._port = port
        self._queue: asyncio.Queue[str | object] = asyncio.Queue(maxsize=queue_capacity)
        self._cooldown_seconds = cooldown_seconds
        self._last_requested: dict[str, float] = {}
        self._bus: EventBus | None = None
        self._worker: asyncio.Task | None = None
        self._running = False
        self._requested = 0
        self._completed = 0
        self._failed = 0
        self._deduplicated = 0

    def register(self, bus: EventBus) -> None:
        if self._bus is bus:
            return
        if self._bus is not None:
            raise RuntimeError("CandidateSubscriptionCoordinator already registered")
        bus.subscribe(EventType.CANDIDATE_ENTERED, self.on_candidate_entered)
        self._bus = bus

    def unregister(self) -> None:
        if self._bus is None:
            return
        self._bus.unsubscribe(EventType.CANDIDATE_ENTERED, self.on_candidate_entered)
        self._bus = None

    async def start(self, supervisor: RuntimeSupervisor | None = None) -> None:
        if self._running or self._port is None:
            return
        self._running = True
        coroutine = self._run()
        if supervisor is None:
            self._worker = asyncio.create_task(coroutine, name="v2-candidate-subscriptions")
        else:
            self._worker = supervisor.create_task(
                "v2-candidate-subscriptions", coroutine, critical=False
            )

    async def stop(self, *, drain: bool = True) -> None:
        if not self._running:
            return
        if drain:
            await self._queue.join()
        else:
            self._discard_pending()
        await self._queue.put(self._STOP)
        if self._worker is not None:
            await asyncio.gather(self._worker, return_exceptions=True)
        self._worker = None
        self._running = False

    def on_candidate_entered(self, event) -> None:
        if (
            not self._running
            or not isinstance(event, DecisionEvent)
            or event.new_state not in {
                StrategyStatus.SETUP.value,
                StrategyStatus.WATCHING.value,
            }
        ):
            return
        self._request(event.stock_code)

    def prime(self, stock_codes: tuple[str, ...]) -> None:
        if self._port is None:
            return
        protect = getattr(self._port, "protect_candidates", None)
        if callable(protect):
            protect(stock_codes)
        for code in stock_codes:
            self._request(code)

    def _request(self, code: str) -> None:
        if not self._running:
            return
        now = time.monotonic()
        if now - self._last_requested.get(code, 0.0) < self._cooldown_seconds:
            self._deduplicated += 1
            return
        try:
            self._queue.put_nowait(code)
        except asyncio.QueueFull:
            self._failed += 1
            logging.warning("V2 candidate subscription queue full: %s", code)
            return
        self._last_requested[code] = now
        self._requested += 1

    def snapshot(self) -> CandidateSubscriptionStats:
        return CandidateSubscriptionStats(
            requested=self._requested,
            completed=self._completed,
            failed=self._failed,
            deduplicated=self._deduplicated,
            queue_size=self._queue.qsize(),
            running=self._running,
        )

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is self._STOP:
                    return
                if isinstance(item, str) and self._port is not None:
                    success = await asyncio.to_thread(self._port.subscribe_candidate, item)
                    if success:
                        self._completed += 1
                    else:
                        self._failed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                self._failed += 1
                logging.exception("V2 candidate subscription failed: %s", item)
            finally:
                self._queue.task_done()

    def _discard_pending(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            else:
                self._failed += 1
                self._queue.task_done()
