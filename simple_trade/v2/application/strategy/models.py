"""Typed Phase 4 candidate-policy results."""

from dataclasses import dataclass, field
from typing import Mapping

from ...domain.enums import DataQuality, EventType, StrategyStatus
from ...domain.serialization import JsonValue, freeze_json


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseDecision:
    eligible: bool
    reason_codes: tuple[str, ...]


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
class StrategyNomination:
    strategy_id: str
    eligible: bool
    stage: str
    score: float
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("strategy_id cannot be empty")
        if self.stage not in {"REJECTED", "WATCH", "CONFIRMED"}:
            raise ValueError("unsupported nomination stage")
        if not 0 <= self.score <= 100:
            raise ValueError("nomination score must be between 0 and 100")
        if not self.reason_codes:
            raise ValueError("nomination must include reason_codes")


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyPortfolioResult:
    nominations: tuple[StrategyNomination, ...]
    strategy_sources: tuple[str, ...]
    consensus_count: int
    ranking_score: float

    def __post_init__(self) -> None:
        if self.consensus_count != len(self.strategy_sources):
            raise ValueError("consensus_count must match strategy_sources")
        if not 0 <= self.ranking_score <= 100:
            raise ValueError("ranking_score must be between 0 and 100")


@dataclass(frozen=True, slots=True, kw_only=True)
class TransitionProposal:
    new_status: StrategyStatus
    event_type: EventType
    reason_code: str
    confirmation_price: float | None = None
    alert_eligible: bool = True
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason_code.strip():
            raise ValueError("reason_code cannot be empty")
        if not isinstance(self.alert_eligible, bool):
            raise ValueError("alert_eligible must be boolean")
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
