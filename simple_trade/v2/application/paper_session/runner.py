"""Single bounded paper worker; SDK and event-bus callbacks never perform I/O."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
import logging
import queue
import threading
from uuid import uuid4

from ...domain.capture import CapturedBook
from ...domain.decisions import DecisionEvent
from ...domain.enums import EventType
from ...domain.events import DomainEvent, FeatureSnapshotEvent
from ...domain.paper_session import PaperSessionConfig, PaperSessionStats
from ...domain.planning.codec import encode
from ...domain.planning.models import PaperAccount, PaperExitPolicy
from ...ports.paper_session import PaperSessionStore
from ..event_bus import EventBus
from .service import PaperSessionService


class PaperSessionRunner:
    SIGNAL_EVENTS = (EventType.BUY_CONFIRMED, EventType.BUY_INVALIDATED, EventType.CANDIDATE_INVALIDATED)

    def __init__(self, config: PaperSessionConfig, store_factory: Callable[[], PaperSessionStore],
                 health: Callable[[], str | None], *,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.config, self._factory, self._health, self._clock = config, store_factory, health, clock
        self._queue: queue.Queue[DecisionEvent | CapturedBook | FeatureSnapshotEvent] = queue.Queue(config.queue_capacity)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = self._started = False
        self._queued = self._processed = self._dropped = 0
        self._error: str | None = None
        self._last_result: str | None = None
        self._account: PaperAccount | None = None
        self._bus: EventBus | None = None

    def register(self, bus: EventBus) -> None:
        if self._bus is not None and self._bus is not bus:
            raise RuntimeError("paper runner already registered")
        for kind in self.SIGNAL_EVENTS:
            bus.subscribe(kind, self.offer_signal)
        if self.config.experiment.exit_policy is PaperExitPolicy.PRODUCTION_RULES:
            bus.subscribe(EventType.FEATURE_SNAPSHOT_READY, self.offer_feature)
        self._bus = bus

    def start(self) -> None:
        if self._started:
            raise RuntimeError("use a new paper runner after stopping")
        self._started = True
        self._thread = threading.Thread(target=self._run, name="v2-paper-session", daemon=True)
        self._thread.start()

    def offer_signal(self, event: DomainEvent) -> None:
        if isinstance(event, DecisionEvent) and event.event_type in self.SIGNAL_EVENTS:
            self._offer(event)

    def offer_book(self, book: CapturedBook) -> None:
        # Books unrelated to the approved experiment cannot consume its disk budget.
        if book.stock_code in self.config.experiment.stock_codes:
            self._offer(book)

    def offer_feature(self, event: DomainEvent) -> None:
        if (self.config.experiment.exit_policy is PaperExitPolicy.PRODUCTION_RULES
                and isinstance(event, FeatureSnapshotEvent)
                and event.stock_code in self.config.experiment.stock_codes):
            self._offer(event)

    def _offer(self, item: DecisionEvent | CapturedBook | FeatureSnapshotEvent) -> None:
        with self._lock:
            if not self._running:
                return
            try:
                self._queue.put_nowait(item)
                self._queued += 1
            except queue.Full:
                self._dropped += 1
                self._fail("PAPER_INPUT_QUEUE_OVERFLOW")

    def _fail(self, reason: str) -> None:
        with self._lock:
            self._error = self._error or reason
            self._running = False
        self._stop.set()

    def _run(self) -> None:
        store, owned = None, False
        item = None
        run_id = uuid4().hex
        try:
            store = self._factory()
            configuration = {**asdict(self.config), "path": str(self.config.path)}
            store.begin_run(run_id, encode(configuration))
            owned = True
            service = PaperSessionService(store, self.config.experiment)
            account = store.read()
            with self._lock:
                self._account = account
                self._running = not self._stop.is_set()
            while not self._stop.is_set():
                problem = self._health()
                if problem:
                    self._fail(problem)
                    break
                try:
                    item = self._queue.get(timeout=0.25)
                except queue.Empty:
                    item = None
                if self._stop.is_set():
                    break
                problem = self._health()
                if problem:
                    self._fail(problem)
                    break
                now = self._clock()
                if isinstance(item, CapturedBook):
                    if item.loss_count or "CONNECTION_CHANGED" in item.reasons:
                        self._fail("PAPER_CAPTURE_DISCONTINUITY")
                        break
                    result = service.book(item, now)
                elif isinstance(item, DecisionEvent):
                    result = service.signal(item, now)
                elif isinstance(item, FeatureSnapshotEvent):
                    result = service.feature(item, now)
                else:
                    due = any((order.entry_remaining and now >= order.plan.setup.valid_until)
                              or (order.held and not order.exit_reason and now >= order.plan.setup.exit_at)
                              for order in self._account.orders)
                    if not due:
                        continue
                    result = service.clock(now)
                account = store.read()
                with self._lock:
                    self._account, self._last_result = account, result
                    self._processed += 1
                item = None
        except Exception as error:
            self._fail(f"PAPER_SESSION_FAILED:{type(error).__name__}:{error}")
            logging.exception("Paper experiment stopped; production alerts remain independent")
        finally:
            with self._lock:
                self._running = False
                pending = self._queue.qsize() + int(item is not None)
                if pending:
                    self._dropped += pending
                    self._error = self._error or "PAPER_STOP_WITH_PENDING_INPUT"
            if owned:
                try:
                    store.finish_run(run_id, self._error)
                except Exception as error:
                    self._fail(f"PAPER_FINAL_CHECKPOINT_FAILED:{type(error).__name__}:{error}")

    def stop(self) -> None:
        if self._bus is not None:
            for kind in self.SIGNAL_EVENTS:
                self._bus.unsubscribe(kind, self.offer_signal)
            self._bus.unsubscribe(EventType.FEATURE_SNAPSHOT_READY, self.offer_feature)
            self._bus = None
        with self._lock:
            self._running = False
        self._stop.set()
        if self._thread is not None:
            self._thread.join(8)
            if self._thread.is_alive():
                self._fail("PAPER_STOP_TIMEOUT")

    def snapshot(self) -> PaperSessionStats:
        with self._lock:
            account = self._account
            return PaperSessionStats(
                self._running, self.config.account_id, self.config.experiment.experiment_id,
                self._queued, self._processed, self._dropped, self._queue.qsize(),
                tuple(order.plan.setup.stock_code for order in account.orders if order.active) if account else (),
                len(account.orders) if account else 0, len(account.fills) if account else 0,
                str(account.cash) if account else None, str(account.equity) if account else None,
                tuple(order.plan.setup.stock_code for order in account.orders if order.held and (
                    order.plan.setup.stock_code not in account.book_times
                    or not 0 <= (self._clock() - account.book_times[order.plan.setup.stock_code]).total_seconds()
                    <= account.policy.max_book_age_seconds
                )) if account else (),
                account.as_of if account else None, self._last_result, self._error,
            )
