"""Typed Phase 4 candidate-policy results."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from ...domain.enums import DataQuality, EventType, StrategyStatus
from ...domain.serialization import JsonValue, freeze_json


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseDecision:
    eligible: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class LegacySignalContext:
    observed_at: datetime
    source: str
    direction: str
    severity: str
    duration_minutes: int
    price_change_pct: float
    net_buy_amount: float
    position: str
    signal_price: float


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateScore:
    total: float
    activity: float
    liquidity: float
    capital_flow: float
    price_acceptance: float
    relative_strength: float
    daily_position: float
    quality: DataQuality
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class TransitionProposal:
    new_status: StrategyStatus
    event_type: EventType
    reason_code: str
    confirmation_price: float | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason_code.strip():
            raise ValueError("reason_code cannot be empty")
        if self.confirmation_price is not None and self.confirmation_price <= 0:
            raise ValueError("confirmation_price must be positive")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))


@dataclass(frozen=True, slots=True)
class CandidateCoordinatorStats:
    queued: int
    dropped: int
    processed: int
    transitions: int
    rejections_persisted: int
    persistence_failures: int
    conflicts: int
    queue_size: int
    queue_capacity: int
    running: bool
