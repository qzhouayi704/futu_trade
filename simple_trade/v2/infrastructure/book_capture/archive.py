"""Capacity-bounded capture database. Never writes to a trading database."""

from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import shutil
import time

from ...domain.capture import BookCaptureConfig, CapturedBook, CaptureStats
from ...domain.planning.codec import encode


class CaptureCapacityError(RuntimeError):
    pass


class SqliteBookArchive:
    APPLICATION_ID = 0x42435031

    def __init__(self, config: BookCaptureConfig) -> None:
        self.config = config

    def _connect(self):
        return sqlite3.connect(str(self.config.path), timeout=1.0)

    def start(self, session_id: str, when: datetime) -> None:
        self._check_space()
        with closing(self._connect()) as conn:
            app_id = conn.execute("PRAGMA application_id").fetchone()[0]
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if app_id != self.APPLICATION_ID and (app_id != 0 or tables):
                raise ValueError("refusing to use a non-capture database")
            if self.config.path.stat().st_size > self.config.max_bytes:
                raise CaptureCapacityError("existing archive exceeds configured byte limit")
            conn.execute("PRAGMA journal_mode=DELETE")
            self._limit_pages(conn)
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(f"PRAGMA application_id={self.APPLICATION_ID}")
                conn.execute("CREATE TABLE IF NOT EXISTS capture_sessions ("
                             "session_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT, "
                             "config_json TEXT NOT NULL, status_json TEXT NOT NULL)")
                conn.execute("CREATE TABLE IF NOT EXISTS captured_books ("
                             "event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, sequence INTEGER NOT NULL, "
                             "stock_code TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL, "
                             "UNIQUE(session_id, sequence))")
                conn.execute("CREATE INDEX IF NOT EXISTS ix_captured_stock_time "
                             "ON captured_books(stock_code, received_at)")
                config = {**asdict(self.config), "path": str(self.config.path), "schema_version": 1}
                conn.execute("INSERT INTO capture_sessions VALUES (?, ?, NULL, ?, ?)",
                             (session_id, when.isoformat(), encode(config), encode({"state": "RUNNING"})))

    def _limit_pages(self, conn) -> None:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        conn.execute(f"PRAGMA max_page_count={self.config.max_bytes // page_size}")

    def _check_space(self) -> None:
        if shutil.disk_usage(self.config.path.parent).free < self.config.min_free_bytes:
            raise CaptureCapacityError("capture stopped to preserve minimum free disk space")

    def write(self, books: tuple[CapturedBook, ...], stats: CaptureStats,
              *, ended_at: datetime | None = None) -> None:
        if books:
            self._check_space()
        with closing(self._connect()) as conn:
            if conn.execute("PRAGMA application_id").fetchone()[0] != self.APPLICATION_ID:
                raise ValueError("capture database identity changed")
            self._limit_pages(conn)
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute("SELECT 1 FROM capture_sessions WHERE session_id=?", (stats.session_id,)).fetchone() is None:
                    raise ValueError("unknown capture session")
                count = conn.execute("SELECT COUNT(*) FROM captured_books").fetchone()[0]
                for book in books:
                    if book.session_id != stats.session_id:
                        raise ValueError("capture book belongs to another session")
                    payload = encode(book)
                    old = conn.execute("SELECT payload FROM captured_books WHERE event_id=?",
                                       (book.event_id,)).fetchone()
                    if old is not None:
                        if old[0] != payload:
                            raise ValueError("capture identity reused with different content")
                        continue
                    if count >= self.config.max_records:
                        raise CaptureCapacityError("capture record limit reached")
                    conn.execute("INSERT INTO captured_books VALUES (?, ?, ?, ?, ?, ?)",
                                 (book.event_id, book.session_id, book.sequence, book.stock_code,
                                  book.received_at.isoformat(), payload))
                    count += 1
                conn.execute("UPDATE capture_sessions SET status_json=?, ended_at=? WHERE session_id=?",
                             (encode(stats), ended_at.isoformat() if ended_at else None, stats.session_id))


def read_archive(path: Path) -> dict:
    """Bounded read-only overview; does not claim an unclosed session is complete."""
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
        deadline = time.monotonic() + 5
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        conn.execute("PRAGMA query_only=ON")
        if conn.execute("PRAGMA application_id").fetchone()[0] != SqliteBookArchive.APPLICATION_ID:
            raise ValueError("not a capture archive")
        sessions = conn.execute("SELECT session_id, started_at, ended_at, status_json FROM capture_sessions "
                                "ORDER BY started_at DESC LIMIT 100").fetchall()
        codes = conn.execute("SELECT stock_code, COUNT(*), MIN(received_at), MAX(received_at) "
                             "FROM captured_books GROUP BY stock_code LIMIT 1000").fetchall()
        return {"schema_version": 1, "sampled_best_book_only": True,
                "sessions": [{"session_id": sid, "started_at": start, "ended_at": end,
                              "closed_cleanly": bool(end) and not json.loads(stats).get("error"),
                              "stats": json.loads(stats)} for sid, start, end, stats in sessions],
                "stocks": [{"code": code, "records": n, "first": first, "last": last}
                           for code, n, first, last in codes]}


def decode_book(payload: str) -> CapturedBook:
    value = json.loads(payload)
    for field in ("received_at", "bid_time", "ask_time"):
        if value[field] is not None:
            value[field] = datetime.fromisoformat(value[field])
    for field in ("bid", "ask"):
        if value[field] is not None:
            value[field] = Decimal(value[field])
    value["reasons"] = tuple(value["reasons"])
    return CapturedBook(**value)
