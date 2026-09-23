"""Bounded local ledger with an explicit single-run/restart-review boundary."""

from contextlib import closing
from collections.abc import Callable
from datetime import datetime, timezone
import shutil
import sqlite3

from ...domain.paper_session import PaperSessionConfig
from ...domain.planning.codec import decode_account
from ...domain.planning.models import PaperAccount
from .sqlite_account_store import SqlitePaperAccountStore


class SqlitePaperSessionStore(SqlitePaperAccountStore):
    def __init__(self, config: PaperSessionConfig) -> None:
        self.config = config
        self._check_space()
        if config.path.exists() and config.path.stat().st_size > config.max_bytes:
            raise RuntimeError("paper ledger exceeds byte budget")
        super().__init__(config.path, config.account_id, config.experiment.policy)
        with closing(self._connect()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS paper_session_run ("
                         "singleton INTEGER PRIMARY KEY CHECK(singleton=1), configuration TEXT NOT NULL, "
                         "run_id TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT, error TEXT)")
            self._calls = conn.execute("SELECT COUNT(*) FROM paper_commands").fetchone()[0]

    def _connect(self) -> sqlite3.Connection:
        conn = super()._connect()
        size = conn.execute("PRAGMA page_size").fetchone()[0]
        conn.execute(f"PRAGMA max_page_count={self.config.max_bytes // size}")
        return conn

    def _check_space(self) -> None:
        if shutil.disk_usage(self.config.path.parent).free < self.config.min_free_bytes:
            raise RuntimeError("paper ledger stopped to preserve free disk space")

    def begin_run(self, run_id: str, configuration: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT configuration, ended_at, error FROM paper_session_run").fetchone()
            if previous is not None:
                if previous[0] != configuration:
                    raise ValueError("paper experiment configuration is immutable; use a new ledger")
                if not previous[1] or previous[2]:
                    raise RuntimeError("previous paper run is active or incomplete; manual review required")
            row = conn.execute("SELECT state_json FROM paper_account WHERE account_id=?", (self._account_id,)).fetchone()
            account = decode_account(row[0])
            if any(order.active for order in account.orders):
                raise RuntimeError("paper exposure exists across a capture gap; manual review required")
            conn.execute("INSERT OR REPLACE INTO paper_session_run VALUES (1, ?, ?, ?, NULL, NULL)",
                         (configuration, run_id, datetime.now(timezone.utc).isoformat()))

    def finish_run(self, run_id: str, error: str | None) -> None:
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute("UPDATE paper_session_run SET ended_at=?, error=? "
                                  "WHERE singleton=1 AND run_id=? AND ended_at IS NULL",
                                  (datetime.now(timezone.utc).isoformat(), error, run_id))
            if cursor.rowcount != 1:
                raise RuntimeError("paper run ownership changed")

    def apply(self, event_id: str, fingerprint: str,
              operation: Callable[[PaperAccount], str]) -> str:
        self._check_space()
        # Bound even duplicate calls; this is a conservative work budget, not a fill count.
        if self._calls >= self.config.max_commands:
            raise RuntimeError("paper session command budget reached")
        result = super().apply(event_id, fingerprint, operation)
        self._calls += 1
        return result
