"""Point-in-time theme diagnostics, isolated from the frozen entry universe."""
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Literal

from ...data import theme_of
from ..runtime.models import local


Status = Literal['MATCHED', 'EXCLUDED', 'UNKNOWN']
Evidence = Literal['PIT_CAPTURE', 'CURRENT_LOOKUP', 'SYNTHETIC']
THEMES = ('AI', '科技', '医药', '芯片', '光伏')
MAX_SNAPSHOTS = 256


def bounded_text(value: str, name: str, limit: int = 200) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'bounded nonempty {name} required')


def stock_code(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r'HK\.\d{5}', value):
        raise ValueError('HK stock code required')


@dataclass(frozen=True)
class SignalReference:
    event_id: str
    code: str
    emitted_at: datetime
    primary_label: str | None

    def __post_init__(self) -> None:
        bounded_text(self.event_id, 'event id')
        stock_code(self.code)
        object.__setattr__(self, 'emitted_at', local(self.emitted_at))
        if self.primary_label is not None and (
                not isinstance(self.primary_label, str) or len(self.primary_label) > 200):
            raise ValueError('bounded primary label required')


@dataclass(frozen=True, order=True)
class PlateMembership:
    plate_code: str
    plate_name: str

    def __post_init__(self) -> None:
        bounded_text(self.plate_code, 'plate code')
        bounded_text(self.plate_name, 'plate name')


@dataclass(frozen=True)
class MembershipSnapshot:
    snapshot_id: str
    code: str
    source: str
    source_version: str
    captured_at: datetime
    received_at: datetime
    complete: bool
    evidence: Evidence
    members: tuple[PlateMembership, ...]

    def __post_init__(self) -> None:
        for name in ('snapshot_id', 'source', 'source_version'):
            bounded_text(getattr(self, name), name)
        stock_code(self.code)
        for name in ('captured_at', 'received_at'):
            object.__setattr__(self, name, local(getattr(self, name)))
        if self.received_at < self.captured_at:
            raise ValueError('receipt cannot precede capture')
        if type(self.complete) is not bool or self.evidence not in ('PIT_CAPTURE', 'CURRENT_LOOKUP', 'SYNTHETIC'):
            raise ValueError('explicit completeness and known evidence kind required')
        if (not isinstance(self.members, tuple) or len(self.members) > 128
                or any(not isinstance(m, PlateMembership) for m in self.members)
                or len({m.plate_code for m in self.members}) != len(self.members)):
            raise ValueError('bounded unique plate membership required')
        object.__setattr__(self, 'members', tuple(sorted(self.members)))


@dataclass(frozen=True)
class ThemeDecision:
    signal: SignalReference
    frozen_primary_theme: str | None
    frozen_primary_reason: str
    status: Status
    reason: str
    explanation: str
    matched_themes: tuple[str, ...]
    snapshot_ids: tuple[str, ...]
    matched_members: tuple[PlateMembership, ...]
    # Even a valid theme match is neither an entry signal nor certified evidence.
    buy_authorized: bool = False
    source_authenticity_independently_certified: bool = False


def validate_snapshots(snapshots: tuple[MembershipSnapshot, ...]) -> None:
    if (not isinstance(snapshots, tuple) or len(snapshots) > MAX_SNAPSHOTS
            or any(not isinstance(s, MembershipSnapshot) for s in snapshots)):
        raise ValueError('bounded typed membership snapshots required')
    seen: dict[str, MembershipSnapshot] = {}
    for snapshot in snapshots:
        prior = seen.get(snapshot.snapshot_id)
        if prior is not None and prior != snapshot:
            raise ValueError('snapshot identity reused with conflicting content')
        seen[snapshot.snapshot_id] = snapshot


def decide(signal: SignalReference, snapshots: tuple[MembershipSnapshot, ...]) -> ThemeDecision:
    """Only labels known at emission; no current-name or company-name inference."""
    validate_snapshots(snapshots)
    frozen = theme_of(signal.primary_label or '')
    primary_reason = ('PRIMARY_LABEL_MISSING' if not signal.primary_label else
                      'PRIMARY_LABEL_MATCH' if frozen else 'PRIMARY_LABEL_NO_MATCH')

    def result(status: Status, reason: str, explanation: str,
               chosen: tuple[MembershipSnapshot, ...] = (),
               themes: tuple[str, ...] = (), members: tuple[PlateMembership, ...] = ()) -> ThemeDecision:
        return ThemeDecision(signal, frozen, primary_reason, status, reason, explanation,
            themes, tuple(sorted({s.snapshot_id for s in chosen})), members)

    same_stock = tuple(s for s in snapshots if s.code == signal.code)
    if not same_stock:
        return result('UNKNOWN', 'MEMBERSHIP_SNAPSHOT_MISSING', '缺少该股事件时多板块成员快照；不等于不属于目标主题。')
    known = tuple(s for s in same_stock if s.received_at <= signal.emitted_at)
    if not known:
        return result('UNKNOWN', 'SNAPSHOT_NOT_YET_KNOWN', '成员快照在信号之后才取得，不能回填历史归属。')
    same_day = tuple(s for s in known if s.captured_at.date() == signal.emitted_at.date())
    if not same_day:
        return result('UNKNOWN', 'NO_SAME_DAY_SNAPSHOT', '只有其他日期的成员快照，未满足同日证据门禁。')
    latest_time = max(s.captured_at for s in same_day)
    latest = tuple(s for s in same_day if s.captured_at == latest_time)
    identities = {(s.members, s.complete, s.evidence, s.source, s.source_version) for s in latest}
    if len(identities) != 1:
        return result('UNKNOWN', 'CONFLICTING_LATEST_SNAPSHOTS', '最近采集时刻有冲突版本，不猜测有效成员。', latest)
    snapshot = latest[0]
    if snapshot.evidence != 'PIT_CAPTURE':
        return result('UNKNOWN', 'NOT_POINT_IN_TIME_EVIDENCE', '当前查询或合成快照不能作为真实事件时归属证据。', latest)
    if not snapshot.complete:
        return result('UNKNOWN', 'MEMBERSHIP_SNAPSHOT_INCOMPLETE', '最近快照未声明完整成员集合，不回退到旧版本。', latest)
    matches = tuple(m for m in snapshot.members if theme_of(m.plate_name))
    themes = tuple(t for t in THEMES if any(theme_of(m.plate_name) == t for m in matches))
    if not themes:
        return result('EXCLUDED', 'NO_TARGET_THEME_IN_COMPLETE_SNAPSHOT',
                      '完整事件时成员快照未命中冻结五主题词表；仅为主题筛选排除。', latest)
    return result('MATCHED', 'TARGET_THEME_MATCH', '事件时成员命中目标主题；尚未判断低位、资金、成交或风控条件。',
                  latest, themes, matches)
