"""Build position decision events and restart-safe analytical state."""

from datetime import datetime

from ...domain.decisions import DecisionEvent
from ...domain.enums import EventType, PositionStatus
from ...domain.events import FeatureSnapshotEvent, PositionReconciledEvent
from ...domain.positions import (
    PositionEfficiency,
    PositionSnapshot,
    PositionState,
    RotationProposal,
)
from ...domain.serialization import to_primitive
from .models import PositionEvaluation


def should_persist(
    as_of,
    state: PositionState | None,
    evaluation: PositionEvaluation,
    interval,
) -> bool:
    if state is None or state.status is not evaluation.target_status:
        return True
    reason = evaluation.decision.reason_codes[0]
    if state.metadata.get("last_reason") != reason:
        return True
    if evaluation.decision.action.value != "HOLD":
        return False
    last = state.metadata.get("last_persisted_at")
    if isinstance(last, str):
        try:
            last = datetime.fromisoformat(last)
        except ValueError:
            last = None
    return not isinstance(last, datetime) or as_of - last >= interval


def evolve_state(
    position: PositionSnapshot,
    prior: PositionState,
    efficiency: PositionEfficiency,
    evaluation: PositionEvaluation,
) -> PositionState:
    return _state_values(
        position,
        prior,
        efficiency,
        evaluation,
        version=prior.version,
        last_event_id=prior.last_event_id,
        last_persisted_at=prior.metadata.get("last_persisted_at"),
    )


def build_position_transition(
    source: FeatureSnapshotEvent | PositionReconciledEvent,
    position: PositionSnapshot,
    prior: PositionState | None,
    efficiency: PositionEfficiency,
    evaluation: PositionEvaluation,
    *,
    strategy_version: str,
    schema_version: int,
) -> tuple[DecisionEvent, PositionState]:
    event = DecisionEvent(
        event_type=evaluation.event_type,
        stock_code=position.stock_code,
        exchange_time=position.as_of,
        received_time=source.received_time,
        source="v2.position-coordinator",
        schema_version=schema_version,
        strategy_version=strategy_version,
        correlation_id=source.correlation_id,
        old_state=prior.status.value if prior is not None else PositionStatus.FLAT.value,
        new_state=evaluation.target_status.value,
        reason_code=evaluation.decision.reason_codes[0],
        payload={
            "shadow_only": True,
            "position": to_primitive(position),
            "efficiency": to_primitive(efficiency),
            "decision": to_primitive(evaluation.decision),
            "rotation": to_primitive(evaluation.rotation) if evaluation.rotation else None,
            "exit_context": to_primitive(evaluation.metadata_updates),
            "mark_source": (
                "feature_snapshot"
                if isinstance(source, FeatureSnapshotEvent)
                else "position_reconciliation"
            ),
            "source_quality": (
                source.snapshot.quality
                if isinstance(source, FeatureSnapshotEvent)
                else source.reconciliation.quality
            ),
        },
    )
    current_prior = bool(
        prior is not None and prior.strategy_version == strategy_version
    )
    placeholder = prior or _initial_state(position, strategy_version, event.event_id)
    state = _state_values(
        position,
        placeholder,
        efficiency,
        evaluation,
        version=(prior.version if current_prior else 0) + 1,
        last_event_id=event.event_id,
        last_persisted_at=position.as_of,
        strategy_version=strategy_version,
    )
    return event, state


def build_closed_transition(
    source: PositionReconciledEvent,
    prior: PositionState,
    *,
    schema_version: int,
) -> tuple[DecisionEvent, PositionState]:
    event = DecisionEvent(
        event_type=EventType.POSITION_CLOSED,
        stock_code=prior.stock_code,
        exchange_time=source.exchange_time,
        received_time=source.received_time,
        source="v2.position-coordinator",
        schema_version=schema_version,
        strategy_version=prior.strategy_version,
        correlation_id=source.correlation_id,
        old_state=prior.status.value,
        new_state=PositionStatus.CLOSED.value,
        reason_code="BROKER_POSITION_CLOSED",
        payload={"shadow_only": True, "broker_authoritative": True},
    )
    return event, PositionState(
        stock_code=prior.stock_code,
        strategy_version=prior.strategy_version,
        status=PositionStatus.CLOSED,
        version=prior.version + 1,
        last_event_id=event.event_id,
        updated_at=source.exchange_time,
        opened_at=prior.opened_at,
        cost_price=prior.cost_price,
        peak_price=prior.peak_price,
        trough_price=prior.trough_price,
        mfe_pct=prior.mfe_pct,
        mae_pct=prior.mae_pct,
        last_high_at=prior.last_high_at,
        stalled_since=None,
        profit_ready_since=prior.profit_ready_since,
        flow_peak=prior.flow_peak,
        metadata={**dict(prior.metadata), "closed_at": source.exchange_time},
    )


def rotation_evaluation(
    position: PositionSnapshot,
    proposal: RotationProposal,
) -> PositionEvaluation:
    from ...domain.enums import DecisionAction, EventType
    from ...domain.positions import PositionDecision

    return PositionEvaluation(
        decision=PositionDecision(
            stock_code=position.stock_code,
            as_of=position.as_of,
            status=PositionStatus.ROTATION_READY,
            action=DecisionAction.ROTATE,
            reason_codes=("CONFIRMED_CANDIDATE_NET_ADVANTAGE",),
            replacement_stock_code=proposal.buy_stock_code,
            confidence=0.75,
        ),
        event_type=EventType.ROTATION_PROPOSED,
        target_status=PositionStatus.ROTATION_READY,
        persist_immediately=True,
        rotation=proposal,
    )


def _initial_state(
    position: PositionSnapshot,
    strategy_version: str,
    event_id: str,
) -> PositionState:
    return PositionState(
        stock_code=position.stock_code,
        strategy_version=strategy_version,
        status=PositionStatus.HOLDING,
        version=1,
        last_event_id=event_id,
        updated_at=position.as_of,
        opened_at=position.as_of,
        cost_price=position.cost_price,
        peak_price=position.current_price,
        trough_price=position.current_price,
        mfe_pct=position.current_return_pct,
        mae_pct=position.current_return_pct,
        last_high_at=position.as_of,
    )


def _state_values(
    position: PositionSnapshot,
    prior: PositionState,
    efficiency: PositionEfficiency,
    evaluation: PositionEvaluation,
    *,
    version: int,
    last_event_id: str,
    last_persisted_at: object,
    strategy_version: str | None = None,
) -> PositionState:
    basis_changed = "COST_BASIS_CHANGED" in efficiency.reason_codes
    new_high = position.current_price > prior.peak_price
    stalled_since = (
        (None if basis_changed else prior.stalled_since) or position.as_of
        if evaluation.target_status in {PositionStatus.STALLED, PositionStatus.ROTATION_READY}
        else None
    )
    profit_ready_since = (
        (None if basis_changed else prior.profit_ready_since) or position.as_of
        if efficiency.mfe_pct >= 3.0
        else None
    )
    metadata = {
        **dict(prior.metadata),
        **dict(evaluation.metadata_updates),
        "last_persisted_at": last_persisted_at,
        "broker_quantity": position.quantity,
        "broker_sellable_quantity": position.sellable_quantity,
        "active_order_ids": position.active_order_ids,
        "last_action": evaluation.decision.action.value,
        "last_reason": evaluation.decision.reason_codes[0],
    }
    return PositionState(
        stock_code=position.stock_code,
        strategy_version=strategy_version or prior.strategy_version,
        status=evaluation.target_status,
        version=version,
        last_event_id=last_event_id,
        updated_at=position.as_of,
        opened_at=position.as_of if basis_changed else prior.opened_at,
        cost_price=position.cost_price or prior.cost_price,
        peak_price=(position.current_price if basis_changed else max(prior.peak_price, position.current_price)),
        trough_price=(position.current_price if basis_changed else min(prior.trough_price, position.current_price)),
        mfe_pct=(efficiency.mfe_pct if basis_changed else max(prior.mfe_pct, efficiency.mfe_pct)),
        mae_pct=(efficiency.mae_pct if basis_changed else min(prior.mae_pct, efficiency.mae_pct)),
        last_high_at=(position.as_of if basis_changed or new_high else prior.last_high_at),
        stalled_since=stalled_since,
        profit_ready_since=profit_ready_since,
        flow_peak=(efficiency.flow_peak if basis_changed else max(prior.flow_peak, efficiency.flow_peak)),
        metadata=metadata,
    )
