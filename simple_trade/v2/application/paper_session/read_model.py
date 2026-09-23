"""Single-flight read-only ledger inspection, isolated from the paper writer."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import time
from typing import Protocol

from ...domain.paper_session import PaperSessionConfig, PaperSessionStats
from ...domain.planning.ledger import PaperLedgerSnapshot, PaperLedgerView


class PaperSessionViewPort(Protocol):
    config: PaperSessionConfig

    def snapshot(self) -> PaperSessionStats: ...


class PaperLedgerReader:
    def __init__(self, session: PaperSessionViewPort | None,
                 inspect: Callable[[Path], PaperLedgerSnapshot]) -> None:
        self.session, self._inspect = session, inspect
        self._task: asyncio.Task[PaperLedgerSnapshot | None] | None = None
        self._started_at = 0.0

    def _read_existing(self) -> PaperLedgerSnapshot | None:
        path = self.session.config.path
        return self._inspect(path) if path.exists() else None

    async def read(self) -> PaperLedgerView:
        if self.session is None:
            return PaperLedgerView("DISABLED", False, None, None)
        if self._task is None or (self._task.done() and time.monotonic() - self._started_at >= 2):
            self._started_at = time.monotonic()
            self._task = asyncio.create_task(asyncio.to_thread(self._read_existing))
            # A disconnected HTTP reader must not leave an unobserved task exception.
            self._task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        ledger = await asyncio.wait_for(asyncio.shield(self._task), timeout=8)
        stats = self.session.snapshot()
        # Hide filesystem/error details; the full exception remains in server logs.
        stats = replace(stats, error=stats.error.split(":", 1)[0] if stats.error else None)
        if ledger is None:
            if stats.cash is not None:
                raise ValueError("initialized paper ledger is missing")
            return PaperLedgerView("ERROR" if stats.error else "NOT_INITIALIZED", False, stats, None)
        if ledger.account_id != stats.account_id or ledger.experiment_id != stats.experiment_id:
            raise ValueError("paper runtime/ledger identity mismatch")
        status = "ERROR" if stats.error or ledger.run_error_code else "RUNNING" if stats.running else "STOPPED"
        return PaperLedgerView(status, False, stats, ledger)
