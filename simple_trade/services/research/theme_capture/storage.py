"""Bounded read-only source and separate append-only evidence archive."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
import sqlite3
import time
from uuid import uuid4

from .models import CaptureConfig, CaptureStats, CapturedSignal, HK, Member, Membership, encode


class SqliteMembershipSource:
    def __init__(self, config: CaptureConfig):
        self.config = config

    def read(self) -> tuple[Membership, ...]:
        cfg = self.config
        if not cfg.enabled:
            raise ValueError('membership source is disabled')
        with closing(sqlite3.connect(cfg.source_path.as_uri()+'?mode=ro', uri=True, timeout=.1)) as conn:
            conn.execute('PRAGMA query_only=ON')
            deadline = time.monotonic()+.5
            conn.set_progress_handler(lambda: time.monotonic() > deadline, 1000)
            conn.execute('BEGIN')
            marks = ','.join('?' for _ in cfg.codes)
            rows = conn.execute(
                'SELECT s.code,p.plate_code,p.plate_name FROM stocks s '
                'JOIN stock_plates sp ON sp.stock_id=s.id JOIN plates p ON p.id=sp.plate_id '
                f'WHERE s.code IN ({marks}) ORDER BY s.code,p.plate_code LIMIT ?',
                (*cfg.codes, len(cfg.codes)*128+1)).fetchall()
            captured = datetime.now(HK)  # conservative: after the read, never query start/created_at
            conn.rollback()
        if len(rows) > len(cfg.codes)*128:
            raise OverflowError('membership source row limit exceeded')
        result = []
        for code in cfg.codes:
            members = tuple(Member(plate_code, name) for c, plate_code, name in rows if c == code)
            if len(members) > 128 or len({m.plate_code for m in members}) != len(members):
                raise ValueError('duplicate/oversized membership source')
            # Whole local relation query != complete exchange-wide thematic coverage.
            result.append(Membership('local-theme:'+uuid4().hex, code,
                'LOCAL_STOCK_PLATES_NOT_UNIVERSE_CERTIFIED', cfg.source_version,
                captured, datetime.now(HK), False, 'PIT_CAPTURE', members))
        return tuple(result)


class ThemeArchive:
    MAGIC = 'LOCAL_THEME_CAPTURE_V1'
    TABLES = {'metadata', 'sessions', 'memberships', 'signals'}

    def __init__(self, config: CaptureConfig, session_id: str):
        if not config.enabled:
            raise ValueError('archive requires explicit enable')
        self.config, self.session_id = config, session_id
        binding = json.dumps((str(config.source_path), sorted(config.codes), config.source_version))
        self.binding = hashlib.sha256(binding.encode()).hexdigest()
        if config.path.exists():
            with closing(sqlite3.connect(config.path.as_uri()+'?mode=ro', uri=True, timeout=.2)) as conn:
                self._check(conn)
        self.connection = sqlite3.connect(config.path, timeout=.2)
        try:
            conn = self.connection
            # Retain the file lock across commits: exactly one writer, reads after stop.
            conn.execute('PRAGMA locking_mode=EXCLUSIVE')
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('BEGIN EXCLUSIVE')
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables:
                self._check(conn)
            else:
                conn.execute('CREATE TABLE metadata(magic TEXT, binding TEXT)')
                conn.execute('INSERT INTO metadata VALUES (?,?)', (self.MAGIC, self.binding))
                conn.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT, stats TEXT)')
                conn.execute('CREATE TABLE memberships(id TEXT PRIMARY KEY, session_id TEXT, code TEXT, payload TEXT)')
                conn.execute('CREATE TABLE signals(id TEXT PRIMARY KEY, session_id TEXT, code TEXT, snapshot_id TEXT, payload TEXT)')
            page_size = conn.execute('PRAGMA page_size').fetchone()[0]
            if conn.execute('PRAGMA page_count').fetchone()[0]*page_size > config.max_bytes:
                raise OverflowError('archive exceeds configured size')
            conn.execute(f'PRAGMA max_page_count={config.max_bytes//page_size}')
            self.count = sum(conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                             for table in ('memberships', 'signals', 'sessions'))
            self._capacity(1)
            conn.execute('INSERT INTO sessions VALUES (?,?,NULL,?)',
                (session_id, datetime.now(HK).isoformat(), encode(CaptureStats(True, 0, 0, 0, None))))
            conn.commit()
            self.count += 1
        except BaseException:
            self.connection.close()
            raise

    def _check(self, conn: sqlite3.Connection) -> None:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables != self.TABLES or conn.execute('SELECT magic,binding FROM metadata').fetchall() != [(self.MAGIC, self.binding)]:
            raise ValueError('foreign database or changed capture binding')

    def _capacity(self, additional: int) -> None:
        if self.count+additional > self.config.max_records:
            raise OverflowError('theme archive record capacity reached')

    def save_memberships(self, rows: tuple[Membership, ...]) -> None:
        self._capacity(len(rows))
        with self.connection:
            for row in rows:
                self.connection.execute('INSERT INTO memberships VALUES (?,?,?,?)',
                    (row.snapshot_id, self.session_id, row.code, encode(row)))
        self.count += len(rows)

    def save_signal(self, row: CapturedSignal) -> bool:
        old = self.connection.execute('SELECT payload FROM signals WHERE id=?', (row.event_id,)).fetchone()
        if old:
            values = json.loads(old[0])
            identity = tuple(values[k] for k in ('code', 'emitted_at', 'stage', 'sequence', 'primary_label'))
            if identity != row.identity():
                raise ValueError('conflicting signal identity')
            return False  # preserve first receipt and originally bound snapshot on retry
        self._capacity(1)
        if row.snapshot_id and not self.connection.execute('SELECT 1 FROM memberships WHERE id=? AND code=?',
                                                           (row.snapshot_id, row.code)).fetchone():
            raise ValueError('signal references an uncommitted/foreign membership')
        with self.connection:
            self.connection.execute('INSERT INTO signals VALUES (?,?,?,?,?)',
                (row.event_id, self.session_id, row.code, row.snapshot_id, encode(row)))
        self.count += 1
        return True

    def status(self, stats: CaptureStats, *, ended: bool = False) -> None:
        with self.connection:
            self.connection.execute('UPDATE sessions SET stats=?,ended_at=? WHERE id=?',
                (encode(stats), datetime.now(HK).isoformat() if ended else None, self.session_id))

    def close(self) -> None:
        self.connection.close()
