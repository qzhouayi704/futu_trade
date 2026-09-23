"""Coalesced, retryable subscription protection driven by broker reconciliation."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging

from ..domain.enums import EventType
from ..domain.events import PositionReconciledEvent
from ..ports.exposure_subscriptions import ExposureSubscriptionPort
from .event_bus import EventBus
from .runtime_supervisor import RuntimeSupervisor


@dataclass(frozen=True, slots=True)
class ExposureSubscriptionStats:
    protected_codes: tuple[str, ...]
    attempts: int
    completed: int
    failed: int
    timeouts: int
    ignored_reconciliations: int
    running: bool


class ExposureSubscriptionCoordinator:
    def __init__(self, port: ExposureSubscriptionPort | None, *,
                 retry_seconds: float = 30, timeout_seconds: float = 8) -> None:
        if retry_seconds <= 0 or timeout_seconds <= 0:
            raise ValueError("subscription retry and timeout must be positive")
        self._port = port
        self._retry = retry_seconds
        self._timeout = timeout_seconds
        self._bus: EventBus | None = None
        self._worker: asyncio.Task | None = None
        self._inflight: asyncio.Task | None = None
        self._inflight_code: str | None = None
        self._wake = asyncio.Event()
        self._positions: set[str] = set()
        self._orders: set[str] = set()
        self._last_as_of: datetime | None = None
        self._running = False
        self._attempts = self._completed = self._failed = self._timeouts = self._ignored = 0

    def register(self, bus: EventBus) -> None:
        if self._bus is bus:
            return
        if self._bus is not None:
            raise RuntimeError("exposure subscriptions already registered")
        bus.subscribe(EventType.POSITION_RECONCILED, self.on_reconciled)
        self._bus = bus

    def unregister(self) -> None:
        if self._bus is not None:
            self._bus.unsubscribe(EventType.POSITION_RECONCILED, self.on_reconciled)
            self._bus = None

    @property
    def protected_codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._positions | self._orders))

    def on_reconciled(self, event) -> None:
        if not isinstance(event, PositionReconciledEvent):
            return
        value = event.reconciliation
        if not value.authoritative or (self._last_as_of is not None and value.as_of <= self._last_as_of):
            self._ignored += 1
            return
        self._last_as_of = value.as_of
        self._positions = {item.stock_code for item in value.positions if item.quantity > 0}
        orders = {item.stock_code for item in value.active_orders if item.quantity > item.dealt_quantity}
        if any(reason.startswith(("ORDER_QUERY_NOT_AUTHORITATIVE", "ACTIVE_ORDERS_NOT_REFRESHED"))
               for reason in value.reason_codes):
            self._orders.update(orders)
        else:
            self._orders = orders
        # Protect first, synchronously. Candidate cleanup must not race a slow SDK call.
        self._apply_protection()
        self._wake.set()

    def _apply_protection(self) -> None:
        if self._port is not None:
            try:
                self._port.protect_exposure(self.protected_codes)
            except Exception:
                self._failed += 1
                logging.exception("V2 exposure protection update failed")

    async def start(self, supervisor: RuntimeSupervisor | None = None) -> None:
        if self._running or self._port is None:
            return
        self._running = True
        self._worker = (supervisor.create_task("v2-exposure-subscriptions", self._run(), critical=False)
                        if supervisor else asyncio.create_task(self._run(), name="v2-exposure-subscriptions"))
        self._wake.set()

    async def stop(self) -> None:
        self._running = False
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None
        # An SDK call in a thread cannot be killed safely. Keep its identity so a
        # restart does not start another call while the previous one is outstanding.
        if self._inflight is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._inflight), self._timeout)
            except Exception:
                logging.warning("V2 exposure subscription call still pending or failed during stop")

    async def _finish_inflight(self) -> bool:
        if self._inflight is None:
            return True
        try:
            success = await asyncio.wait_for(asyncio.shield(self._inflight), self._timeout)
        except TimeoutError:
            self._timeouts += 1
            return False
        except Exception:
            self._failed += 1
            logging.exception("V2 exposure subscription failed: %s", self._inflight_code)
        else:
            if success:
                self._completed += 1
            else:
                self._failed += 1
        self._inflight = None
        self._inflight_code = None
        return True

    async def _run(self) -> None:
        while self._running:
            try:
                await asyncio.wait_for(self._wake.wait(), self._retry)
            except TimeoutError:
                pass
            self._wake.clear()
            self._apply_protection()
            if not await self._finish_inflight():
                continue
            for code in self.protected_codes:
                if not self._running:
                    return
                if code not in self.protected_codes:
                    continue
                self._attempts += 1
                self._inflight_code = code
                self._inflight = asyncio.create_task(asyncio.to_thread(self._port.subscribe_exposure, code))
                if not await self._finish_inflight():
                    break

    def snapshot(self) -> ExposureSubscriptionStats:
        return ExposureSubscriptionStats(self.protected_codes, self._attempts, self._completed,
                                         self._failed, self._timeouts, self._ignored, self._running)
