"""Immutable capture contracts. No strategy, broker or research-script imports."""
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Protocol


HK = timezone(timedelta(hours=8))
STAGES = frozenset(('FIRST', 'SECOND_WATCH', 'CONFIRMED', 'STRENGTHENED', 'EXPIRED',
                    'INVALIDATED', 'REJECTED', 'TRAIL_EXIT', 'WATCH_TRAIL_EXIT'))


def local(when: datetime) -> datetime:
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError('explicit timezone required')
    return when.astimezone(HK)


def encode(value: object) -> str:
    return json.dumps(asdict(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False, default=lambda x: x.isoformat())


@dataclass(frozen=True)
class CaptureConfig:
    enabled: bool = False
    source_path: Path | None = None
    path: Path | None = None
    codes: tuple[str, ...] = ()
    source_version: str = ''
    queue_size: int = 256
    max_records: int = 100000
    max_bytes: int = 64*1024*1024
    refresh_seconds: float = 30.

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError('explicit boolean enable required')
        if not self.enabled:
            return
        if (not isinstance(self.codes, tuple) or not 1 <= len(self.codes) <= 50
                or len(set(self.codes)) != len(self.codes)
                or any(not isinstance(c, str) or not re.fullmatch(r'HK\.\d{5}', c) for c in self.codes)):
            raise ValueError('explicit bounded HK stock allowlist required')
        if (not isinstance(self.source_version, str) or not self.source_version.strip()
                or len(self.source_version) > 200):
            raise ValueError('explicit bounded source version required')
        if self.source_path is None or self.path is None:
            raise ValueError('source and separate archive paths required')
        source, target = self.source_path.resolve(), self.path.resolve()
        if (source == target or (source.exists() and target.exists() and source.samefile(target))
                or not source.is_file() or not target.parent.is_dir()):
            raise ValueError('existing source and separate explicit archive directory required')
        for value in (self.queue_size, self.max_records, self.max_bytes):
            if type(value) is not int or value < 1:
                raise ValueError('positive integer capacity required')
        if (self.max_bytes < 65536 or not 1 <= self.refresh_seconds <= 3600
                or self.queue_size > 4096 or self.max_records > 1000000):
            raise ValueError('capture bounds exceeded')
        object.__setattr__(self, 'source_path', source)
        object.__setattr__(self, 'path', target)


@dataclass(frozen=True, order=True)
class Member:
    plate_code: str
    plate_name: str

    def __post_init__(self) -> None:
        if any(not isinstance(v, str) or not v.strip() or len(v) > 200
               for v in (self.plate_code, self.plate_name)):
            raise ValueError('bounded member code and name required')


@dataclass(frozen=True)
class Membership:
    snapshot_id: str
    code: str
    source: str
    source_version: str
    captured_at: datetime
    received_at: datetime
    complete: bool
    evidence: str
    members: tuple[Member, ...]

    def __post_init__(self) -> None:
        for value in (self.snapshot_id, self.source, self.source_version):
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ValueError('bounded source identity required')
        if not isinstance(self.code, str) or not re.fullmatch(r'HK\.\d{5}', self.code):
            raise ValueError('HK membership code required')
        for field in ('captured_at', 'received_at'):
            object.__setattr__(self, field, local(getattr(self, field)))
        if (self.received_at < self.captured_at or type(self.complete) is not bool
                or self.evidence != 'PIT_CAPTURE' or not isinstance(self.members, tuple)
                or len(self.members) > 128 or any(not isinstance(m, Member) for m in self.members)
                or len({m.plate_code for m in self.members}) != len(self.members)):
            raise ValueError('invalid membership capture contract')
        object.__setattr__(self, 'members', tuple(sorted(self.members)))


@dataclass(frozen=True)
class CapturedSignal:
    event_id: str
    code: str
    emitted_at: datetime
    received_at: datetime
    stage: str
    sequence: int
    primary_label: str
    snapshot_id: str | None
    reason: str
    receipt_basis: str = 'INTERNAL_PIPELINE_RECEIPT_NOT_SDK_TICK'

    def identity(self) -> tuple[object, ...]:
        return (self.code, self.emitted_at.isoformat(), self.stage, self.sequence, self.primary_label)


def signal(raw: Mapping[str, object], received_at: datetime,
           membership: Membership | None) -> CapturedSignal:
    code, stage, sequence = raw['stock_code'], raw['inflow_stage'], raw['inflow_sequence_no']
    label = raw.get('plate_name', '')
    if (not isinstance(code, str) or not re.fullmatch(r'HK\.\d{5}', code) or stage not in STAGES
            or type(sequence) is not int or sequence < 1 or not isinstance(label, str) or len(label) > 200):
        raise ValueError('invalid signal anchor')
    emitted = datetime.fromtimestamp(float(raw['timestamp']), HK)
    received = local(received_at)
    if emitted > received or raw['trade_date'] != emitted.date().isoformat():
        raise ValueError('signal clock/date mismatch')
    anchor = json.dumps(('capital_trend', code, emitted.isoformat(), stage, sequence))
    event_id = 'capital-theme:'+hashlib.sha256(anchor.encode()).hexdigest()
    reason = 'NO_PRIOR_DURABLE_SNAPSHOT'
    snapshot_id = None
    if membership is not None:
        if (membership.code == code and membership.captured_at.date() == emitted.date()
                and membership.received_at <= emitted):
            snapshot_id = membership.snapshot_id
            reason = 'LOCAL_MEMBERSHIP_CAPTURED_COMPLETENESS_UNVERIFIED'
        else:
            reason = 'SNAPSHOT_NOT_AVAILABLE_FOR_SIGNAL_TIME'
    return CapturedSignal(event_id, code, emitted, received, stage, sequence, label, snapshot_id, reason)


@dataclass(frozen=True)
class CaptureStats:
    running: bool
    persisted: int
    dropped: int
    source_failures: int
    error: str | None


class MembershipSource(Protocol):
    def read(self) -> tuple[Membership, ...]: ...


class ThemeCapturePort(Protocol):
    def request_refresh(self) -> bool: ...
    def on_signal(self, payload: Mapping[str, object], *, received_at: datetime) -> bool: ...
