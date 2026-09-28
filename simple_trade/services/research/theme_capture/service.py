"""Nonblocking pipeline hook; one bounded IO worker with explicit lifecycle."""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
import time
from uuid import uuid4

from .models import CaptureConfig, CaptureStats, CapturedSignal, Membership, MembershipSource, signal
from .storage import SqliteMembershipSource, ThemeArchive


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Refresh:
    pass


class ThemeCapture:
    def __init__(self, config: CaptureConfig, source: MembershipSource | None = None):
        self.config = config
        self.source = source if source is not None else SqliteMembershipSource(config)
        self._queue: Queue[Refresh | CapturedSignal] = Queue(maxsize=config.queue_size)
        self._lock, self._stop = Lock(), Event()
        self._thread: Thread | None = None
        self._accepting = False
        self._refresh_pending = False
        self._next_refresh = 0.
        self._cache: dict[str, Membership] = {}
        self._persisted = self._dropped = self._source_failures = 0
        self._error: str | None = None

    def start(self) -> None:
        with self._lock:
            if not self.config.enabled or self._thread is not None or self._stop.is_set():
                return
            self._accepting = True
            self._thread = Thread(target=self._run, name='theme-evidence-capture', daemon=True)
            self._thread.start()

    def snapshot(self) -> CaptureStats:
        with self._lock:
            return CaptureStats(bool(self._thread and self._thread.is_alive()), self._persisted,
                                self._dropped, self._source_failures, self._error)

    def request_refresh(self) -> bool:
        with self._lock:
            if not self._accepting or self._refresh_pending or time.monotonic() < self._next_refresh:
                return False
            try:
                self._queue.put_nowait(Refresh())
            except Full:
                self._dropped += 1
                return False
            self._refresh_pending = True
            self._next_refresh = time.monotonic()+self.config.refresh_seconds
            return True

    def on_signal(self, payload: Mapping[str, object], *, received_at: datetime) -> bool:
        # Event-loop side: bounded validation/copy only. Never database IO or a wait.
        with self._lock:
            if not self._accepting:
                return False
            if payload.get('stock_code') not in self.config.codes or not payload.get('inflow_stage'):
                return False
            try:
                row = signal(payload, received_at, self._cache.get(payload['stock_code']))
                self._queue.put_nowait(row)
                return True
            except (KeyError, TypeError, ValueError, OverflowError, OSError, Full):
                self._dropped += 1
                return False

    def _refresh(self, archive: ThemeArchive) -> None:
        rows = None
        for attempt in range(2):
            try:
                rows = self.source.read()
                if ({r.code for r in rows} != set(self.config.codes) or len(rows) != len(self.config.codes)
                        or any(not isinstance(r, Membership) for r in rows)):
                    raise ValueError('membership source returned an incomplete stock scope')
                break
            except Exception as exc:
                rows = None
                with self._lock:
                    self._source_failures += 1
                    self._cache = {}
                logger.warning('Theme source attempt %d failed: %s', attempt+1, type(exc).__name__)
        if rows is None:
            with self._lock:
                self._next_refresh = time.monotonic()+60
            return
        archive.save_memberships(rows)  # durability before publication
        with self._lock:
            first_snapshot = not self._cache
            self._cache = {r.code: r for r in rows}
        if first_snapshot:
            logger.info('Theme capture snapshot committed: codes=%s complete=false', ','.join(self.config.codes))

    def _run(self) -> None:
        archive = None
        item = None
        reported_drops = 0
        try:
            archive = ThemeArchive(self.config, uuid4().hex)
            logger.info('Theme capture ready: codes=%s source_version=%s archive=%s',
                        ','.join(self.config.codes), self.config.source_version, self.config.path)
            while not self._stop.is_set() or not self._queue.empty():
                try:
                    item = self._queue.get(timeout=.1)
                except Empty:
                    continue
                try:
                    if isinstance(item, Refresh):
                        self._refresh(archive)
                    elif archive.save_signal(item):
                        with self._lock:
                            self._persisted += 1
                    stats = self.snapshot()
                    archive.status(stats)
                    if stats.dropped != reported_drops:
                        logger.warning('Theme capture dropped/rejected jobs: %d; original signals unchanged', stats.dropped)
                        reported_drops = stats.dropped
                finally:
                    if isinstance(item, Refresh):
                        with self._lock:
                            self._refresh_pending = False
                    self._queue.task_done()
                item = None
        except Exception as exc:
            with self._lock:
                self._error = type(exc).__name__+': '+str(exc)
                self._accepting = False
                self._cache = {}
                self._dropped += self._queue.qsize()+int(item is not None)
            logger.exception('Theme evidence capture stopped; trading pipeline is unaffected')
        finally:
            with self._lock:
                self._accepting = False
            if archive is not None:
                try:
                    # Any unprocessed job and a failing current write make this session incomplete.
                    status = self.snapshot()
                    status = CaptureStats(False, status.persisted, status.dropped, status.source_failures, status.error)
                    archive.status(status, ended=True)
                except Exception:
                    logger.exception('Theme capture final status could not be persisted; session remains unverified')
                archive.close()

    def close(self, timeout: float = 3.) -> bool:
        with self._lock:
            self._accepting = False
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.error('Theme capture shutdown timed out; archive completion is not certified')
                return False
        return True


def configured_capture(source_path: str, env: Mapping[str, str]) -> ThemeCapture | None:
    """Only explicit enable + paths + allowlist; called by the application, not on import."""
    flag = env.get('RESEARCH_THEME_CAPTURE_ENABLED', '0').strip().lower()
    if flag in ('0', 'false', 'off', ''):
        return None
    if flag not in ('1', 'true', 'on'):
        raise ValueError('invalid RESEARCH_THEME_CAPTURE_ENABLED flag')
    target = env.get('RESEARCH_THEME_CAPTURE_PATH', '').strip()
    if not target:
        raise ValueError('explicit independent theme archive path required')
    config = CaptureConfig(True, Path(source_path), Path(target),
        tuple(c.strip() for c in env.get('RESEARCH_THEME_CAPTURE_CODES', '').split(',') if c.strip()),
        env.get('RESEARCH_THEME_CAPTURE_SOURCE_VERSION', '').strip())
    capture = ThemeCapture(config)
    capture.start()
    return capture
