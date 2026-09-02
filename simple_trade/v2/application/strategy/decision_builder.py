"""Build traceable persisted decision/state pairs from a transition proposal."""

from ...domain.decisions import DecisionEvent, StrategyState
from ...domain.enums import StrategyStatus
from ...domain.events import FeatureSnapshotEvent
from ...domain.serialization import to_primitive
from .models import (
    CandidateScore,
    StrategyPortfolioResult,
    TransitionProposal,
    UniverseDecision,
)


def build_transition(
    source: FeatureSnapshotEvent,
    state: StrategyState | None,
    proposal: TransitionProposal,
    score: CandidateScore,
    universe: UniverseDecision,
    portfolio: StrategyPortfolioResult,
    *,
    strategy_version: str,
    schema_version: int,
) -> tuple[DecisionEvent, StrategyState]:
    old_status = state.status if state is not None else StrategyStatus.IDLE
    proposal_metadata = dict(proposal.metadata)
    if proposal.new_status is StrategyStatus.INVALIDATED:
        proposal_metadata["invalidation_reason"] = proposal.reason_code
    merged_metadata = (
        proposal_metadata
        if proposal.new_status is StrategyStatus.SETUP
        else {**(dict(state.metadata) if state is not None else {}), **proposal_metadata}
    )
    event = DecisionEvent(
        event_type=proposal.event_type,
        stock_code=source.stock_code,
        exchange_time=source.exchange_time,
        received_time=source.received_time,
        source="v2.candidate-coordinator",
        schema_version=schema_version,
        strategy_version=strategy_version,
        sequence=source.sequence,
        correlation_id=source.correlation_id,
        old_state=old_status.value,
        new_state=proposal.new_status.value,
        reason_code=proposal.reason_code,
        payload={
            "shadow_only": True,
            "alert_eligible": proposal.alert_eligible,
            "universe": to_primitive(universe),
            "candidate_score": to_primitive(score),
            "strategy_portfolio": to_primitive(portfolio),
            "feature_snapshot": to_primitive(source.snapshot),
        },
    )
    confirmed_price = (
        proposal.confirmation_price
        if proposal.new_status is StrategyStatus.CONFIRMED
        else None
        if proposal.new_status is StrategyStatus.SETUP
        else state.confirmed_price if state is not None else None
    )
    new_state = StrategyState(
        stock_code=source.stock_code,
        strategy_version=strategy_version,
        status=proposal.new_status,
        version=(state.version if state is not None else 0) + 1,
        last_event_id=event.event_id,
        updated_at=source.exchange_time,
        confirmed_price=confirmed_price,
        peak_price=max(
            source.snapshot.quote.last_price,
            state.peak_price if state is not None and state.peak_price is not None else 0.0,
        ),
        last_sequence=source.sequence,
        metadata=merged_metadata,
    )
    return event, new_state
