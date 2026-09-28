"""Evidence classifications; absent observations never become zero trades."""
from dataclasses import dataclass
from enum import Enum
import math

from scripts.analysis.minute_entry_study.models import INDEX, N, wall_minute


class CoverageGrade(str,Enum):
    COMPLETE = 'ALL_330_MINUTES_OBSERVED'
    DENSE = 'GE95PCT_MAX_GAP_LE5'
    GAPPED = 'GAPPED'
    ABSENT = 'NO_REGULAR_MINUTES'


class Evidence(str,Enum):
    UNKNOWN = 'UNKNOWN_NO_INDEPENDENT_TRADE_EVIDENCE'
    CONFLICT = 'DAILY_VERSIONS_CONFLICT'
    NO_ARCHIVE = 'DAILY_POSITIVE_WITH_NO_ARCHIVE_ROWS'
    EMPTY_DAILY = 'ZERO_DAILY_VOLUME_NOT_PROOF_OF_NO_TRADES'
    LOW_VOLUME = 'ARCHIVED_VOLUME_LT80PCT_OF_DAILY'
    HIGH_VOLUME = 'ARCHIVED_VOLUME_GT105PCT_OF_DAILY'
    VOLUME_CLOSE = 'VOLUME_WITHIN_80_TO105PCT_NOT_COMPLETENESS_PROOF'


@dataclass(frozen=True)
class MinuteCoverage:
    code: str
    day: str
    rows: int
    mask: int
    total_volume: float
    regular_volume: float
    invalid_rows: int

    @property
    def observed(self) -> int:
        return self.mask.bit_count()

    @property
    def max_gap(self) -> int:
        current = maximum = 0
        for index in range(N):
            current = 0 if self.mask & (1<<index) else current+1
            maximum = max(maximum,current)
        return maximum

    @property
    def grade(self) -> CoverageGrade:
        if self.observed == N and not self.invalid_rows:
            return CoverageGrade.COMPLETE
        if self.observed >= math.ceil(N*.95) and self.max_gap <= 5 and not self.invalid_rows:
            return CoverageGrade.DENSE
        return CoverageGrade.GAPPED if self.observed else CoverageGrade.ABSENT


@dataclass(frozen=True)
class DailyEvidence:
    code: str
    day: str
    close: float
    high: float
    low: float
    volume: float
    turnover: float
    downloaded_at: str
    conflict: bool = False


@dataclass(frozen=True)
class AuditRow:
    code: str
    day: str
    observed: int
    coverage_pct: float
    max_gap: int
    grade: str
    archive_version: int
    archive_rows: int
    volume_ratio: float | None
    evidence: str
    historical_membership_proxy: bool
    september_theme_cohort: bool


def parse_mask(minutes: str | None) -> int:
    mask = 0
    for minute in (minutes or '').split(','):
        if len(minute) != 5 or minute[2] != ':':
            continue
        try:
            index = INDEX.get(wall_minute(minute))
        except ValueError:
            continue
        if index is not None:
            mask |= 1<<index
    return mask


def classify(coverage: MinuteCoverage, daily: DailyEvidence | None) -> tuple[Evidence,float | None]:
    if daily is None:
        return Evidence.UNKNOWN,None
    if daily.conflict:
        return Evidence.CONFLICT,None
    if daily.volume <= 0:
        return Evidence.EMPTY_DAILY,None
    ratio = coverage.total_volume/daily.volume
    if coverage.rows == 0:
        return Evidence.NO_ARCHIVE,ratio
    if ratio < .8:
        return Evidence.LOW_VOLUME,ratio
    if ratio > 1.05:
        return Evidence.HIGH_VOLUME,ratio
    return Evidence.VOLUME_CLOSE,ratio


def positive_minutes_missing_archive(raw_rows: list[tuple[str,float]], coverage: MinuteCoverage) -> int:
    mask = parse_mask(','.join(minute for minute,volume in raw_rows if volume > 0))
    return (mask & ~coverage.mask).bit_count()
