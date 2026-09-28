"""Bounded single-writer SQLite journal, isolated from production databases."""
from contextlib import contextmanager
import hashlib
import sqlite3
from typing import Iterator

from ..protocol import FrozenProtocol, encoded
from .models import Config, Event, decode, encode, logical_key


class SQLiteJournal:
    def __init__(self, config: Config, protocol: FrozenProtocol):
        if not config.enabled:
            raise ValueError('journal requires explicit local enable')
        self.config = config
        expected = ('CROSS_DAY_RESEARCH_V1', self.fingerprint(protocol), config.dataset_kind)
        if config.path.exists():
            # Inspect read-only before allowing ANY write to an existing database.
            connection = sqlite3.connect(config.path.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)
            try:
                tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables != {'metadata', 'events'} or connection.execute('SELECT magic, protocol_hash, dataset_kind FROM metadata').fetchall() != [expected]:
                    raise ValueError('foreign database or mismatched research binding')
            finally:
                connection.close()
        if not config.path.parent.is_dir():
            raise ValueError('explicit existing output directory required')
        self.connection = sqlite3.connect(config.path, timeout=2, isolation_level=None)
        try:
            self.connection.execute('PRAGMA journal_mode=DELETE')
            self.connection.execute('PRAGMA synchronous=FULL')
            page_size = self.connection.execute('PRAGMA page_size').fetchone()[0]
            pages = config.max_database_bytes//page_size
            if self.connection.execute('PRAGMA page_count').fetchone()[0] > pages:
                raise ValueError('existing database exceeds capacity')
            self.connection.execute(f'PRAGMA max_page_count={pages}')
            with self.transaction():
                self.connection.execute('CREATE TABLE IF NOT EXISTS metadata (magic TEXT, protocol_hash TEXT, dataset_kind TEXT)')
                if not self.connection.execute('SELECT 1 FROM metadata').fetchone():
                    self.connection.execute('INSERT INTO metadata VALUES (?, ?, ?)', expected)
                self.connection.execute('CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, logical_key TEXT UNIQUE NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL)')
            self.count = self.connection.execute('SELECT count(*) FROM events').fetchone()[0]
            if self.count > config.max_events:
                raise ValueError('existing journal exceeds event capacity')
        except BaseException:
            self.connection.close()
            raise

    @staticmethod
    def fingerprint(protocol: FrozenProtocol) -> str:
        return hashlib.sha256(encoded(protocol).encode('utf-8')).hexdigest()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.connection.execute('COMMIT')
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute('ROLLBACK')
            raise

    def events(self) -> tuple[Event, ...]:
        return tuple(decode(row[0]) for row in self.connection.execute('SELECT payload FROM events ORDER BY sequence'))

    def append(self, event: Event) -> bool:
        payload = encode(event)
        with self.transaction():
            count = self.connection.execute('SELECT count(*) FROM events').fetchone()[0]
            if count != self.count:
                raise RuntimeError('concurrent writer detected; reopen and recover state')
            existing = self.connection.execute('SELECT payload FROM events WHERE event_id=? OR logical_key=?',
                                               (event.event_id, logical_key(event))).fetchall()
            if existing:
                if existing == [(payload,)]:
                    return False
                raise ValueError('conflicting duplicate id or immutable observation revision')
            latest = self.connection.execute('SELECT received_at FROM events ORDER BY sequence DESC LIMIT 1').fetchone()
            if latest and event.received_at.isoformat() < latest[0]:
                raise ValueError('out-of-order receipt; journal cannot backdate observations')
            if count >= self.config.max_events:
                raise OverflowError('research event capacity reached; no observation accepted')
            self.connection.execute('INSERT INTO events(event_id, logical_key, received_at, payload) VALUES (?, ?, ?, ?)',
                                    (event.event_id, logical_key(event), event.received_at.isoformat(), payload))
        self.count += 1
        return True

    def close(self) -> None:
        self.connection.close()
