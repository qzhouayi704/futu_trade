"""Bounded production snapshot DTOs; no strategy or broker calls."""
from dataclasses import dataclass
from datetime import datetime
import gzip
import hashlib
import io
import json
from pathlib import Path

from ..runtime.models import SignalObservation, local


DIAGNOSTIC = 'ARCHIVE_DIAGNOSTIC'
SOURCE = 'PRODUCTION_SQLITE_READ_ONLY'
MAX_BYTES = 8*1024*1024


@dataclass(frozen=True)
class SignalRow:
    row_id: int
    day: str
    code: str
    source: str
    action: str
    emitted_text: str
    persisted_text: str
    detail_json: str


@dataclass(frozen=True)
class TickRow:
    row_id: int
    code: str
    day: str
    trade_time: str | None
    timestamp_ms: int
    persisted_text: str
    sequence: int | None


@dataclass(frozen=True)
class MinuteCoverage:
    code: str
    day: str
    regular_minutes: int
    first_minute: str | None
    last_minute: str | None


@dataclass(frozen=True)
class DailyRow:
    row_id: int
    code: str
    day: str
    persisted_text: str


@dataclass(frozen=True)
class TableColumns:
    table: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Snapshot:
    observed_at: datetime
    start_date: str
    end_date: str
    codes: tuple[str, ...]
    signals: tuple[SignalRow, ...]
    ticks: tuple[TickRow, ...]
    minutes: tuple[MinuteCoverage, ...]
    daily: tuple[DailyRow, ...]
    columns: tuple[TableColumns, ...]
    subscription_snapshot_rows: int
    sha256: str


@dataclass(frozen=True)
class Rejection:
    row_id: int
    code: str
    reason: str


@dataclass(frozen=True)
class StockAudit:
    code: str
    raw_signals: int
    normalized_signals: int
    first_signals: int
    tick_sample_rows: int
    timestamp_equals_exchange_rows: int
    timestamp_after_exchange_rows: int
    timestamp_before_exchange_rows: int
    invalid_tick_times: int
    daily_sample_rows: int


@dataclass(frozen=True)
class IntakeReport:
    observed_at: str
    source_sha256: str
    focus_codes: tuple[str, ...]
    stocks: tuple[StockAudit, ...]
    minute_coverage: tuple[MinuteCoverage, ...]
    rejections: tuple[Rejection, ...]
    blockers: tuple[str, ...]
    normalized: tuple[SignalObservation, ...]
    dataset_kind: str = DIAGNOSTIC
    remote_read_only: bool = True
    prospective_ready: bool = False
    performance_result: None = None
    source_authenticity_independently_certified: bool = False


def load(path: Path) -> Snapshot:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('compressed source exceeds byte bound')
    raw = path.read_bytes()
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        unpacked = stream.read(MAX_BYTES+1)
    if len(unpacked) > MAX_BYTES:
        raise ValueError('expanded source exceeds byte bound')
    data = json.loads(unpacked)
    if (data.get('schema') != 1 or data.get('kind') != 'FORWARD_SOURCE_INTAKE'
            or data.get('source') != SOURCE or data.get('read_only') is not True
            or data.get('scope') != 'FOCUS_CODES_ONLY' or data.get('truncated') is not False):
        raise ValueError('not a complete bounded source-contract snapshot')
    codes = tuple(data['codes'])
    if codes != ('HK.00100', 'HK.00699', 'HK.03317'):
        raise ValueError('unexpected source scope')
    for name, limit in (('signals', 5000), ('ticks', 600), ('minutes', 75), ('daily', 66)):
        if len(data[name]) > limit or any(row[2 if name == 'signals' else 1 if name in ('ticks', 'daily') else 0] not in codes for row in data[name]):
            raise ValueError('source row/scope limit exceeded')
    observed = local(datetime.fromisoformat(data['observed_at']))
    if not '2026-09-24' <= data['start_date'] <= data['end_date'] <= observed.date().isoformat():
        raise ValueError('invalid source date range')
    return Snapshot(observed, data['start_date'], data['end_date'], codes,
        tuple(SignalRow(*r) for r in data['signals']), tuple(TickRow(*r) for r in data['ticks']),
        tuple(MinuteCoverage(*r) for r in data['minutes']), tuple(DailyRow(*r) for r in data['daily']),
        tuple(TableColumns(k, tuple(v)) for k, v in sorted(data['columns'].items())),
        data['subscription_snapshot_rows'], hashlib.sha256(raw).hexdigest())
