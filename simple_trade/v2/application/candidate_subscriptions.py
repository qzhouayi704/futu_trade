"""Non-blocking candidate market-data subscription coordination."""

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Protocol

from ...utils.trade_time import market_datetime
from ..domain.candidates import OVERNIGHT_HARD_INVALIDATIONS
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
        self._overnight_protected: tuple[str, ...] = ()
        self._intraday_protected: set[str] = set()
        self._intraday_session_date = ""

    def register(self, bus: EventBus) -> None:
        if self._bus is bus:
            return
        if self._bus is not None:
            raise RuntimeError("CandidateSubscriptionCoordinator already registered")
        bus.subscribe(EventType.CANDIDATE_ENTERED, self.on_candidate_entered)
        bus.subscribe(EventType.CANDIDATE_UPDATED, self.on_candidate_activity)
        bus.subscribe(EventType.BUY_CONFIRMED, self.on_candidate_activity)
        bus.subscribe(EventType.CANDIDATE_INVALIDATED, self.on_candidate_invalidated)
        bus.subscribe(EventType.BUY_INVALIDATED, self.on_candidate_invalidated)
        self._bus = bus

    def unregister(self) -> None:
        if self._bus is None:
            return
        self._bus.unsubscribe(EventType.CANDIDATE_ENTERED, self.on_candidate_entered)
        self._bus.unsubscribe(EventType.CANDIDATE_UPDATED, self.on_candidate_activity)
        self._bus.unsubscribe(EventType.BUY_CONFIRMED, self.on_candidate_activity)
        self._bus.unsubscribe(EventType.CANDIDATE_INVALIDATED, self.on_candidate_invalidated)
        self._bus.unsubscribe(EventType.BUY_INVALIDATED, self.on_candidate_invalidated)
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
        if event.new_state == StrategyStatus.WATCHING.value:
            self._remember_intraday(event)
        self._request(event.stock_code)

    def prime(self, stock_codes: tuple[str, ...]) -> None:
        self._overnight_protected = tuple(dict.fromkeys(stock_codes))
        self._apply_protection()
        for code in stock_codes:
            self._request(code)

    def restore_intraday(self, stock_codes: tuple[str, ...], session_date: str) -> None:
        self.begin_session(session_date)
        self._intraday_protected.update(stock_codes)
        self._apply_protection()
        for code in stock_codes:
            self._request(code)

    def begin_session(self, session_date: str) -> None:
        if session_date == self._intraday_session_date:
            return
        self._intraday_session_date = session_date
        self._intraday_protected.clear()
        self._apply_protection()

    def on_candidate_activity(self, event) -> None:
        if (
            not self._running
            or not isinstance(event, DecisionEvent)
            or event.new_state not in {
                StrategyStatus.WATCHING.value,
                StrategyStatus.CONFIRMED.value,
            }
        ):
            return
        self._remember_intraday(event)
        self._request(event.stock_code)

    def on_candidate_invalidated(self, event) -> None:
        if not isinstance(event, DecisionEvent):
            return
        if event.old_state in {
            StrategyStatus.WATCHING.value,
            StrategyStatus.CONFIRMED.value,
        }:
            self._remember_intraday(event)
        if (
            event.stock_code in self._overnight_protected
            and event.reason_code
            in OVERNIGHT_HARD_INVALIDATIONS | {"OVERNIGHT_PRIORITY_EXPIRED"}
        ):
            self.prime(tuple(
                code for code in self._overnight_protected if code != event.stock_code
            ))

    def _remember_intraday(self, event: DecisionEvent) -> None:
        exchange_time = market_datetime(event.exchange_time, event.stock_code)
        if exchange_time is None:
            return
        session_date = exchange_time.date().isoformat()
        self.begin_session(session_date)
        self._intraday_protected.add(event.stock_code)
        self._apply_protection()

    def _apply_protection(self) -> None:
        if self._port is None:
            return
        protected = tuple(dict.fromkeys((
            *self._overnight_protected,
            *sorted(self._intraday_protected),
        )))
        protect = getattr(self._port, "protect_candidates", None)
        if callable(protect):
            protect(protected)

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
