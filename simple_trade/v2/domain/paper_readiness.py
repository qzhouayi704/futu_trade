"""Read-only readiness facts and declared capacity assumptions, not trade authority."""

from dataclasses import dataclass
from datetime import datetime

from .planning.models import integer


@dataclass(frozen=True, slots=True)
class ReviewAcknowledgements:
    schedule: bool = False
    securities: bool = False
    costs: bool = False
    parameters: bool = False

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in (self.schedule, self.securities, self.costs, self.parameters)):
            raise ValueError("review acknowledgements must be boolean")


@dataclass(frozen=True, slots=True)
class CapacityAssumptions:
    capture_bytes_per_record: int
    paper_bytes_per_command: int
    source: str
    extra_commands: int = 1000

    def __post_init__(self) -> None:
        integer(self.capture_bytes_per_record, "capture_bytes_per_record")
        integer(self.paper_bytes_per_command, "paper_bytes_per_command")
        integer(self.extra_commands, "extra_commands")
        if not self.source.strip():
            raise ValueError("capacity assumption source is required")


@dataclass(frozen=True, slots=True)
class ReadinessIssue:
    code: str
    level: str
    message: str


@dataclass(frozen=True, slots=True)
class StorageFacts:
    path: str
    exists: bool
    parent_ready: bool
    device: str | None
    free_bytes: int | None
    file_bytes: int
    records: int = 0
    blocked_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CapacityProjection:
    remaining_schedule_seconds: float
    capture_records: int
    paper_commands: int
    capture_growth_bytes: int | None
    paper_growth_bytes: int | None
    source: str | None


@dataclass(frozen=True, slots=True)
class PaperReadinessReport:
    checked_at: datetime
    account_id: str
    experiment_id: str
    expected_strategy_version: str
    ready_for_paper_trial: bool
    execution_allowed: bool
    projection: CapacityProjection
    storage: tuple[StorageFacts, ...]
    issues: tuple[ReadinessIssue, ...]
