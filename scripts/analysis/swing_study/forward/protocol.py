"""Typed preregistration and fail-closed calendar/data readiness checks only."""
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path

from scripts.analysis.minute_entry_study.models import HK
from ..legacy.models import Policy
from ..models import ExitRule, FillCosts


CALENDAR_SOURCE = 'https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_075_2025.pdf'
CALENDAR_START, CALENDAR_END = date(2026, 9, 24), date(2026, 12, 23)
CLOSED = {date(2026, 10, 1), date(2026, 10, 19)}
ROOT = Path(__file__).resolve().parents[4]
SOURCES = (
    'scripts/analysis/minute_entry_study/models.py',
    'scripts/analysis/minute_entry_study/replay.py',
    'scripts/analysis/swing_study/models.py',
    'scripts/analysis/swing_study/data.py',
    'scripts/analysis/swing_study/engine.py',
    'scripts/analysis/swing_study/metrics.py',
    'scripts/analysis/swing_study/legacy/models.py',
    'scripts/analysis/swing_study/legacy/data.py',
    'scripts/analysis/swing_study/legacy/signals.py',
    'scripts/analysis/swing_study/legacy/analytics.py',
    'scripts/analysis/swing_study/forward/protocol.py',
)


def scheduled_days(start: date, end: date) -> tuple[str, ...]:
    if start < CALENDAR_START or end > CALENDAR_END or end < start:
        raise ValueError('outside independently checked full-session calendar window')
    return tuple((start+timedelta(days=n)).isoformat() for n in range((end-start).days+1)
                 if (start+timedelta(days=n)).weekday() < 5 and start+timedelta(days=n) not in CLOSED)


@dataclass(frozen=True)
class SourceHash:
    path: str
    sha256: str


@dataclass(frozen=True)
class Arm:
    name: str
    role: str
    entry: Policy
    exit: ExitRule


@dataclass(frozen=True)
class FrozenProtocol:
    schema: int
    registered_at: str
    seen_through_date: str
    earliest_entry_date: str
    historical_input_sha256: str
    arms: tuple[Arm, ...]
    costs: FillCosts
    sources: tuple[SourceHash, ...]
    calendar_source: str = CALENDAR_SOURCE
    preliminary_review_entry_sessions: int = 20
    research_account_hkd: float = 100000.
    maximum_positions: int = 5
    live_execution_allowed: bool = False
    automatic_start: bool = False
    executor_status: str = 'OFFLINE_PROTOCOL_ONLY_NO_PROSPECTIVE_REPLAY_OR_ONLINE_RUNNER'


@dataclass(frozen=True)
class DayEvidence:
    day: str
    archive_version: int
    minute_rows: int


@dataclass(frozen=True)
class HorizonReadiness:
    sessions: int
    earliest_scheduled_window_end: str
    mature_archived_entry_dates: tuple[str, ...]


@dataclass(frozen=True)
class Readiness:
    checked_at: str
    snapshot_observed_at: str
    state: str
    latest_closed_archive_date: str | None
    post_freeze_archived_dates: tuple[str, ...]
    horizons: tuple[HorizonReadiness, ...]
    expected_preliminary_entry_window_end: str
    expected_preliminary_five_day_followup_end: str
    changed_sources: tuple[str, ...]
    blockers: tuple[str, ...]
    evaluation_ready: bool = False
    performance_result: None = None
    actual_stock_path_quality_verified: bool = False
    prospective_runner_started: bool = False
    live_execution_allowed: bool = False


def source_hashes(root: Path = ROOT) -> tuple[SourceHash, ...]:
    return tuple(SourceHash(path, hashlib.sha256((root/path).read_bytes()).hexdigest()) for path in SOURCES)


def freeze(when: datetime, historical_hash: str) -> FrozenProtocol:
    if when.tzinfo is None:
        raise ValueError('timezone required')
    local = when.astimezone(HK)
    future = scheduled_days(local.date()+timedelta(days=1), CALENDAR_END)
    if len(future) < 24:
        raise ValueError('insufficient calendar scope for preliminary review and follow-up')
    arms = tuple(Arm(f'{role}-{h}d', role, Policy('low', timing, .55), ExitRule(h, 1., 2.))
                 for role, timing in (('candidate', 'one'), ('control', 'formal')) for h in (3, 5))
    return FrozenProtocol(1, local.isoformat(), local.date().isoformat(), future[0], historical_hash,
                          arms, FillCosts(), source_hashes())


def from_payload(payload: dict) -> FrozenProtocol:
    values = dict(payload)
    values['arms'] = tuple(Arm(a['name'], a['role'], Policy(**a['entry']), ExitRule(**a['exit'])) for a in values['arms'])
    values['costs'] = FillCosts(**values['costs'])
    values['sources'] = tuple(SourceHash(**s) for s in values['sources'])
    protocol = FrozenProtocol(**values)
    expected_arms = tuple(Arm(f'{role}-{h}d', role, Policy('low', timing, .55), ExitRule(h, 1., 2.))
                          for role, timing in (('candidate', 'one'), ('control', 'formal')) for h in (3, 5))
    if (protocol.schema != 1 or protocol.live_execution_allowed or protocol.automatic_start
            or protocol.preliminary_review_entry_sessions != 20
            or protocol.arms != expected_arms or protocol.costs != FillCosts()
            or protocol.maximum_positions != 5 or protocol.research_account_hkd != 100000.
            or date.fromisoformat(protocol.earliest_entry_date) <= date.fromisoformat(protocol.seen_through_date)):
        raise ValueError('invalid frozen scope or execution permission')
    return protocol


def evaluate(protocol: FrozenProtocol, observed_at: datetime, evidence: tuple[DayEvidence, ...],
             when: datetime, current_sources: tuple[SourceHash, ...]) -> Readiness:
    if observed_at.tzinfo is None or when.tzinfo is None:
        raise ValueError('timezone required')
    registered = datetime.fromisoformat(protocol.registered_at)
    if registered > when or observed_at > when+timedelta(seconds=60):
        raise ValueError('future registration or snapshot')
    current = {s.path: s.sha256 for s in current_sources}
    changed = tuple(s.path for s in protocol.sources if current.get(s.path) != s.sha256)
    schedule = scheduled_days(date.fromisoformat(protocol.earliest_entry_date), CALENDAR_END)
    available = set()
    for e in evidence:
        day = date.fromisoformat(e.day)
        # Pre-registration dates are never prospective, even if later re-exported.
        if e.day not in schedule:
            continue
        closed_at = datetime.combine(day, time(16, 30), HK)
        if closed_at <= observed_at and e.archive_version == 2 and e.minute_rows > 0:
            available.add(e.day)
    horizons = tuple(HorizonReadiness(h, schedule[h-1], tuple(
        day for i, day in enumerate(schedule) if i+h <= len(schedule)
        and all(d in available for d in schedule[i:i+h]))) for h in (3, 5))
    closed_archives = [e.day for e in evidence if e.archive_version == 2 and e.minute_rows > 0
                       and date.fromisoformat(e.day).weekday() < 5 and date.fromisoformat(e.day) not in CLOSED
                       and datetime.combine(date.fromisoformat(e.day), time(16, 30), HK) <= observed_at]
    blockers = []
    if changed:
        blockers.append('FROZEN_SOURCE_CHANGED_REQUIRES_NEW_PROTOCOL')
    if (when-observed_at).total_seconds() > 3600:
        blockers.append('READINESS_SNAPSHOT_STALE')
    if observed_at.astimezone(HK).date() > CALENDAR_END:
        blockers.append('CHECKED_CALENDAR_WINDOW_EXPIRED')
    if not available:
        blockers.append('NO_POST_FREEZE_CLOSED_ARCHIVE')
    if any(not h.mature_archived_entry_dates for h in horizons):
        blockers.append('MAXIMUM_HOLDING_WINDOW_NOT_MATURE')
    blockers.extend(('STOCK_PATH_AND_POINT_IN_TIME_EVIDENCE_NOT_CERTIFIED',
                     'LEGACY_EARLY_MULTISESSION_ADAPTER_NOT_IMPLEMENTED'))
    return Readiness(when.isoformat(), observed_at.isoformat(),
        'FROZEN_SOURCE_CHANGED' if changed else ('WAITING_FOR_NEW_DATES' if not available else 'AWAITING_QUALITY_AND_ADAPTER'),
        max(closed_archives, default=None), tuple(sorted(available)), horizons,
        schedule[protocol.preliminary_review_entry_sessions-1], schedule[protocol.preliminary_review_entry_sessions+3],
        changed, tuple(blockers))


def encoded(value: FrozenProtocol | Readiness) -> str:
    return json.dumps(asdict(value), ensure_ascii=False, indent=2, allow_nan=False)
