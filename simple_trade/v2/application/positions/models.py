"""Typed outputs and observability for the Phase 5 position engine."""

from dataclasses import dataclass

from ...domain.enums import DecisionAction, EventType, PositionStatus
from ...domain.positions import PositionDecision, PositionState, RotationProposal


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionEvaluation:
    decision: PositionDecision
    event_type: EventType
    target_status: PositionStatus
    persist_immediately: bool
    rotation: RotationProposal | None = None

    def __post_init__(self) -> None:
        if self.decision.status is not self.target_status:
            raise ValueError("decision.status must equal target_status")
        if self.decision.action is DecisionAction.ROTATE and self.rotation is None:
            raise ValueError("ROTATE evaluation must include rotation proposal")


@dataclass(frozen=True, slots=True)
class PositionCoordinatorStats:
    reconciliations: int
    positions_processed: int
    transitions: int
    rotations: int
    exits: int
    closed: int
    dropped: int
    persistence_failures: int
    queue_size: int
    queue_capacity: int
    running: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class StateEvolution:
    state: PositionState
    status_changed: bool
