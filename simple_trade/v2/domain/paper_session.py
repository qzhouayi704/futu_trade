"""Explicit, immutable inputs for a local-only intraday paper experiment."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path

from .planning.codec import policy_from_payload
from .planning.models import PaperExitPolicy, PaperPolicy, hk_stock_code, integer, positive
from .serialization import require_aware


HK_ZONE = timezone(timedelta(hours=8))


@dataclass(frozen=True, slots=True)
class PaperSessionInterval:
    opens_at: datetime
    closes_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.opens_at, "opens_at")
        require_aware(self.closes_at, "closes_at")
        if (self.opens_at >= self.closes_at
                or self.opens_at.astimezone(HK_ZONE).date() != self.closes_at.astimezone(HK_ZONE).date()):
            raise ValueError("paper interval must be within one HK date")


@dataclass(frozen=True, slots=True, kw_only=True)
class PaperExperiment:
    experiment_id: str
    strategy_id: str
    strategy_version: str
    stock_codes: tuple[str, ...]
    schedule_source: str
    intervals: tuple[PaperSessionInterval, ...]
    allow_sampled_server_time: bool
    policy: PaperPolicy
    atr_stop_multiple: Decimal
    minimum_stop_fraction: Decimal
    maximum_stop_fraction: Decimal
    pullback_fraction: Decimal
    chase_fraction: Decimal
    entry_ttl_seconds: int
    exit_before_close_seconds: int
    maximum_signal_age_seconds: int
    exit_policy: PaperExitPolicy = PaperExitPolicy.RESEARCH_ATR

    def __post_init__(self) -> None:
        object.__setattr__(self, "exit_policy", PaperExitPolicy(self.exit_policy))
        for key in ("experiment_id", "strategy_id", "strategy_version", "schedule_source"):
            if not isinstance(getattr(self, key), str) or not getattr(self, key).strip():
                raise ValueError(f"{key} is required")
        if self.allow_sampled_server_time is not True:
            raise ValueError("sampled book and server-time approximation must be explicitly accepted")
        codes = tuple(hk_stock_code(code) for code in self.stock_codes)
        if not 1 <= len(codes) <= 20 or len(set(codes)) != len(codes):
            raise ValueError("select 1-20 unique, independently verified HK ordinary stocks")
        object.__setattr__(self, "stock_codes", codes)
        if not 1 <= len(self.intervals) <= 62:
            raise ValueError("explicit paper trading intervals are required")
        intervals = tuple(sorted(self.intervals, key=lambda item: item.opens_at))
        if any(left.closes_at > right.opens_at for left, right in zip(intervals, intervals[1:])):
            raise ValueError("paper trading intervals overlap")
        object.__setattr__(self, "intervals", intervals)
        for key in ("atr_stop_multiple", "minimum_stop_fraction", "maximum_stop_fraction",
                    "pullback_fraction", "chase_fraction"):
            positive(getattr(self, key), key, allow_zero=key in {"pullback_fraction", "chase_fraction"})
        if not (self.pullback_fraction < self.minimum_stop_fraction
                <= self.maximum_stop_fraction < 1 and self.chase_fraction < 1):
            raise ValueError("invalid research price boundaries")
        for key in ("entry_ttl_seconds", "exit_before_close_seconds", "maximum_signal_age_seconds"):
            integer(getattr(self, key), key)
        if self.maximum_signal_age_seconds > 30 or self.entry_ttl_seconds > 1800:
            raise ValueError("paper signal/entry windows are too long")

    def interval_at(self, when: datetime) -> PaperSessionInterval | None:
        require_aware(when, "when")
        return next((item for item in self.intervals if item.opens_at <= when < item.closes_at), None)

    def exit_at(self, when: datetime) -> datetime | None:
        day = when.astimezone(HK_ZONE).date()
        closes = [item.closes_at for item in self.intervals if item.opens_at.astimezone(HK_ZONE).date() == day]
        return max(closes) - timedelta(seconds=self.exit_before_close_seconds) if closes else None


@dataclass(frozen=True, slots=True, kw_only=True)
class PaperSessionConfig:
    path: Path
    account_id: str
    experiment: PaperExperiment
    queue_capacity: int = 1024
    max_commands: int = 250000
    max_bytes: int = 268435456
    min_free_bytes: int = 268435456

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if not self.path.is_absolute():
            raise ValueError("paper session ledger path must be absolute")
        if not self.account_id.startswith("paper:") or not self.account_id[6:].strip():
            raise ValueError("paper session requires a named local paper account")
        for key in ("queue_capacity", "max_commands", "max_bytes", "min_free_bytes"):
            integer(getattr(self, key), key)
        if self.max_bytes < 65536:
            raise ValueError("paper session byte budget too small")

    @classmethod
    def from_env(cls) -> "PaperSessionConfig | None":
        value = os.getenv("V2_PAPER_SESSION_CONFIG", "").strip()
        if not value:
            return None
        return cls.from_file(Path(value))

    @classmethod
    def from_file(cls, path: Path) -> "PaperSessionConfig":
        path = Path(path)
        if not path.is_absolute() or path.stat().st_size > 262144:
            raise ValueError("paper config must be an absolute file of at most 256 KiB")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if payload.pop("schema_version", None) != 1:
            raise ValueError("unsupported paper session configuration")
        experiment = payload.pop("experiment")
        experiment["policy"] = policy_from_payload(experiment["policy"])
        experiment["stock_codes"] = tuple(experiment["stock_codes"])
        experiment["intervals"] = tuple(PaperSessionInterval(
            datetime.fromisoformat(item["opens_at"]), datetime.fromisoformat(item["closes_at"])
        ) for item in experiment["intervals"])
        for key in ("atr_stop_multiple", "minimum_stop_fraction", "maximum_stop_fraction",
                    "pullback_fraction", "chase_fraction"):
            experiment[key] = Decimal(str(experiment[key]))
        return cls(**payload, experiment=PaperExperiment(**experiment))


@dataclass(frozen=True, slots=True)
class PaperSessionStats:
    running: bool
    account_id: str
    experiment_id: str
    queued: int
    processed: int
    dropped: int
    queue_size: int
    active_codes: tuple[str, ...]
    plans: int
    fills: int
    cash: str | None
    equity: str | None
    stale_position_codes: tuple[str, ...]
    as_of: datetime | None
    last_result: str | None
    error: str | None
