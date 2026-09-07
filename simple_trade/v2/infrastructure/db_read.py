"""Bounded read-only connections that do not turn database errors into empty data."""

from contextlib import closing
from math import isfinite
from pathlib import Path
import sqlite3
import threading
import time
from typing import Protocol


class ReadDatabasePort(Protocol):
    def execute_query(self, query: str, params: tuple | None = None) -> list: ...


class SqliteReadDatabase:
    _slots = threading.BoundedSemaphore(2)

    def __init__(self, path: str | Path, *, timeout_seconds: float = 5.0):
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("read timeout must be positive")
        self._uri = Path(path).resolve().as_uri() + "?mode=ro"
        self._timeout = timeout_seconds

    def execute_query(self, query: str, params: tuple | None = None) -> list:
        if not self._slots.acquire(timeout=self._timeout):
            raise TimeoutError("V2 read capacity exhausted")
        try:
            deadline = time.monotonic() + self._timeout
            with closing(sqlite3.connect(self._uri, uri=True, timeout=min(self._timeout, 2.0))) as connection:
                connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                return connection.execute(query, params or ()).fetchall()
        finally:
            self._slots.release()


def strict_reader(db: ReadDatabasePort, *, timeout_seconds: float = 5.0) -> ReadDatabasePort:
    path = getattr(db, "database_path", None)
    return SqliteReadDatabase(path, timeout_seconds=timeout_seconds) if isinstance(path, (str, Path)) else db
