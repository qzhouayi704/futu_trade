"""Non-blocking SDK ingress and one bounded, isolated archive writer."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
import queue
import logging
import sqlite3
import threading
import time
from uuid import uuid4

from ...domain.capture import BookCaptureConfig, CapturedBook, CaptureStats
from ...ports.book_capture import BookArchivePort, BookNormalizer


class BookRecorder:
    def __init__(self, config: BookCaptureConfig, archive: BookArchivePort, normalizer: BookNormalizer,
                 *, monotonic=time.monotonic) -> None:
        self.config = config
        self.archive = archive
        self._normalize = normalizer
        self.session_id = uuid4().hex
        self._clock = monotonic
        self._queue: queue.Queue[CapturedBook] = queue.Queue(maxsize=config.queue_capacity)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._running = False
        self._targets: tuple[str, ...] = ()
        self._subscribed: tuple[str, ...] = ()
        self._sampled_at: dict[str, float] = {}
        self._connection_id: str | None = None
        self._last_received: datetime | None = None
        self._received = self._sampled_out = self._dropped = self._invalid = self._persisted = 0
        self._subscription_failures = self._connection_changes = 0
        self._error: str | None = None
        self._committed_sink: Callable[[CapturedBook], None] | None = None

    def set_committed_sink(self, sink: Callable[[CapturedBook], None]) -> None:
        if self._started:
            raise RuntimeError("configure committed sink before capture starts")
        self._committed_sink = sink

    def start(self) -> None:
        if self._started:
            raise RuntimeError("use a new recorder/session after stopping")
        self.archive.start(self.session_id, datetime.now(timezone.utc))
        self._started = self._running = True
        self._thread = threading.Thread(target=self._write_loop, name="v2-book-archive", daemon=True)
        self._thread.start()

    def targets(self, codes: tuple[str, ...]) -> None:
        with self._lock:
            self._targets = tuple(dict.fromkeys(codes))[:self.config.max_stocks]
            self._sampled_at = {code: at for code, at in self._sampled_at.items() if code in self._targets}

    def subscriptions(self, codes: tuple[str, ...], *, failed: bool = False) -> None:
        with self._lock:
            self._subscribed = tuple(codes)
            if failed:
                self._subscription_failures += 1

    def offer(self, raw: Mapping[str, object], received_at: datetime, connection_id: str) -> None:
        code = str(raw.get("code", "")).strip().upper()
        with self._lock:
            if not self._running or code not in self._targets:
                return
            self._received += 1
            self._last_received = received_at
            changed = self._connection_id is not None and self._connection_id != connection_id
            if changed:
                self._connection_changes += 1
                self._sampled_at.clear()
            self._connection_id = connection_id
            now = self._clock()
            if now - self._sampled_at.get(code, float('-inf')) < self.config.sample_interval_seconds:
                self._sampled_out += 1
                return
            self._sampled_at[code] = now
            try:
                book = self._normalize(raw, session_id=self.session_id, sequence=self._received,
                                      connection_id=connection_id, received_at=received_at,
                                      loss_count=self._dropped)
                if changed:
                    book = replace(book, reasons=(*book.reasons, "CONNECTION_CHANGED"))
            except (TypeError, ValueError, OverflowError):
                self._invalid += 1
                self._dropped += 1
                return
            if book.reasons:
                self._invalid += 1
            try:
                self._queue.put_nowait(book)
            except queue.Full:
                self._dropped += 1

    def snapshot(self) -> CaptureStats:
        with self._lock:
            return CaptureStats(self._running, self.session_id, self._targets, self._subscribed,
                                tuple(code for code in self._targets if code not in self._subscribed),
                                self._received, self._sampled_out, self._dropped, self._invalid,
                                self._persisted, self._queue.qsize(), self._subscription_failures,
                                self._connection_changes, self._last_received, self._error)

    def fail(self, error: str) -> None:
        with self._lock:
            self._error = error
            self._running = False
        self._stop.set()

    def stop(self) -> None:
        with self._lock:
            self._running = False
        self._stop.set()
        if self._thread is not None:
            self._thread.join(self.config.io_timeout_seconds)
            if self._thread.is_alive():
                self.fail("ARCHIVE_STOP_TIMEOUT")

    def _write_loop(self) -> None:
        checkpoint = 0.0
        batch: list[CapturedBook] = []
        try:
            while not self._stop.is_set() or not self._queue.empty():
                self._stop.wait(0.5)
                batch: list[CapturedBook] = []
                for _ in range(self.config.batch_size):
                    try:
                        batch.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
                if not batch and self._clock() - checkpoint < 5:
                    continue
                for attempt in range(3):
                    try:
                        status = replace(self.snapshot(), persisted=self._persisted + len(batch))
                        self.archive.write(tuple(batch), status)
                        break
                    except sqlite3.OperationalError as error:
                        if attempt == 2 or not any(word in str(error).lower() for word in ("locked", "busy")):
                            raise
                        time.sleep(0.2)
                with self._lock:
                    self._persisted += len(batch)
                if self._committed_sink is not None:
                    for book in batch:
                        try:
                            self._committed_sink(book)
                        except Exception:
                            logging.exception("Committed book consumer rejected input")
                checkpoint = self._clock()
        except Exception as error:
            with self._lock:
                self._dropped += len(batch) + self._queue.qsize()
            self.fail(f"ARCHIVE_FAILED:{type(error).__name__}:{error}")
        finally:
            with self._lock:
                self._running = False
            try:
                self.archive.write((), self.snapshot(), ended_at=datetime.now(timezone.utc))
            except Exception as error:
                self.fail(f"ARCHIVE_FINAL_CHECKPOINT_FAILED:{type(error).__name__}:{error}")
