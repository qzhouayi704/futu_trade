"""Bounded read-only probes; missing databases are never created."""

from contextlib import closing
from dataclasses import asdict
import os
from pathlib import Path
import shutil
import sqlite3
import time

from ...domain.paper_readiness import StorageFacts
from ...domain.paper_session import PaperSessionConfig
from ...domain.planning.codec import decode_account, encode
from ..book_capture.archive import SqliteBookArchive
from .sqlite_account_store import SqlitePaperAccountStore


def paths_alias(left: Path, right: Path) -> bool:
    if left.resolve() == right.resolve():
        return True
    return left.exists() and right.exists() and left.samefile(right)


def probe_storage(path: Path, *, role: str, paper: PaperSessionConfig | None = None) -> StorageFacts:
    path = path.resolve()
    exists = path.exists()
    try:
        if not path.parent.is_dir():
            return StorageFacts(str(path), exists, False, None, None, 0,
                                blocked_reason="PARENT_DIRECTORY_MISSING")
        device = str(path.parent.stat().st_dev)
        free = shutil.disk_usage(path.parent).free
        parent_ready = os.access(path.parent, os.W_OK)
        if not parent_ready:
            return StorageFacts(str(path), exists, False, device, free, 0,
                                blocked_reason="PARENT_DIRECTORY_NOT_WRITABLE")
        if not exists:
            return StorageFacts(str(path), False, True, device, free, 0)
        if not path.is_file():
            return StorageFacts(str(path), True, True, device, free, 0,
                                blocked_reason="DATABASE_PATH_NOT_A_FILE")
        size = path.stat().st_size
        if not os.access(path, os.W_OK):
            return StorageFacts(str(path), True, True, device, free, size,
                                blocked_reason="DATABASE_NOT_WRITABLE")
        count, problem = _inspect_database(path, role, paper)
        return StorageFacts(str(path), True, True, device, free, size, count, problem)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as error:
        return StorageFacts(str(path), exists, False, None, None, 0,
                            blocked_reason=f"PROBE_FAILED:{type(error).__name__}")


def _inspect_database(path: Path, role: str, paper: PaperSessionConfig | None) -> tuple[int, str | None]:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
        deadline = time.monotonic() + 3
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        expected = SqliteBookArchive.APPLICATION_ID if role == "capture" else SqlitePaperAccountStore.APPLICATION_ID
        if conn.execute("PRAGMA application_id").fetchone()[0] != expected:
            return 0, "DATABASE_IDENTITY_MISMATCH"
        if role == "capture":
            count = conn.execute("SELECT COUNT(*) FROM captured_books").fetchone()[0]
            # An existing unclosed capture may still have a writer. Do not bless reuse.
            if conn.execute("SELECT 1 FROM capture_sessions WHERE ended_at IS NULL LIMIT 1").fetchone():
                return count, "CAPTURE_ACTIVE_OR_UNCLEAN"
            return count, None
        if role != "paper" or paper is None:
            raise ValueError("paper probe requires a configuration")
        count = conn.execute("SELECT COUNT(*) FROM paper_commands").fetchone()[0]
        lengths = conn.execute("SELECT LENGTH(CAST(state_json AS BLOB)) FROM paper_account LIMIT 2").fetchall()
        if len(lengths) != 1 or lengths[0][0] > 4 * 1024 ** 2:
            return count, "PAPER_ACCOUNT_STATE_TOO_LARGE_OR_INVALID"
        rows = conn.execute("SELECT account_id, state_json FROM paper_account LIMIT 2").fetchall()
        if len(rows) != 1:
            return count, "PAPER_ACCOUNT_IDENTITY_MISMATCH"
        account = decode_account(rows[0][1])
        if rows[0][0] != paper.account_id or account.account_id != paper.account_id or account.policy != paper.experiment.policy:
            return count, "PAPER_ACCOUNT_IDENTITY_MISMATCH"
        if any(order.active for order in account.orders):
            return count, "PAPER_EXPOSURE_REQUIRES_REVIEW"
        row = conn.execute("SELECT configuration, ended_at, error FROM paper_session_run WHERE singleton=1").fetchone()
        if row is not None:
            expected_config = encode({**asdict(paper), "path": str(paper.path)})
            if row[0] != expected_config:
                return count, "PAPER_CONFIGURATION_CHANGED"
            if not row[1] or row[2]:
                return count, "PAPER_ACTIVE_OR_UNCLEAN"
        return count, None
