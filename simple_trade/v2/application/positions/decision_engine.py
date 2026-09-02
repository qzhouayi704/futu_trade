"""Risk-first deterministic position decision rules."""

from ...domain.enums import DecisionAction, EventType, PositionStatus
from ...domain.features import FeatureSnapshot
from ...domain.positions import PositionDecision, PositionEfficiency, PositionSnapshot, PositionState
from .models import PositionEvaluation
from .structural_exit import StructuralExitPolicy


class PositionDecisionEngine:
    PROFIT_READY_PCT = 3.0

    def __init__(self) -> None:
        self._structural_exit = StructuralExitPolicy()

    def evaluate(
        self,
        position: PositionSnapshot,
        state: PositionState | None,
        efficiency: PositionEfficiency,
        feature: FeatureSnapshot | None,
    ) -> PositionEvaluation:
        if position.active_order_ids:
            return self._hold(
                position,
                state,
                "ACTIVE_ORDER_CONFLICT",
                status=state.status if state is not None else PositionStatus.HOLDING,
            )
        if position.cost_price <= 0 or position.current_price <= 0:
            return self._hold(position, state, "POSITION_PRICE_INVALID")
        structural = self._structural_exit.assess(state, efficiency, feature)
        if structural.exit_reason is not None:
            return self._exit(
                position,
                structural.exit_reason,
                metadata_updates=structural.metadata_updates,
            )
        if structural.strong_outflow:
            return self._hold(
                position,
                state,
                "REPEATED_OUTFLOW_ABSORBED_OR_SUPPORTED",
                metadata_updates=structural.metadata_updates,
            )

        profit_ready = max(efficiency.mfe_pct, state.mfe_pct if state else 0.0) >= self.PROFIT_READY_PCT
        if efficiency.stalled:
            return PositionEvaluation(
                decision=PositionDecision(
                    stock_code=position.stock_code,
                    as_of=position.as_of,
                    status=PositionStatus.STALLED,
                    action=DecisionAction.HOLD,
                    reason_codes=("SUSTAINED_PRICE_AND_FLOW_STALL",),
                    confidence=0.70,
                ),
                event_type=EventType.POSITION_EFFICIENCY_CHANGED,
                target_status=PositionStatus.STALLED,
                persist_immediately=state is None or state.status is not PositionStatus.STALLED,
                metadata_updates=structural.metadata_updates,
            )
        status = PositionStatus.PROFIT_READY if profit_ready else PositionStatus.HOLDING
        reason = "PROFIT_PROTECTION_ARMED" if profit_ready else "POSITION_EFFICIENT"
        return self._hold(
            position,
            state,
            reason,
            status=status,
            metadata_updates=structural.metadata_updates,
        )

    @staticmethod
    def _exit(
        position: PositionSnapshot,
        reason: str,
        *,
        metadata_updates=None,
    ) -> PositionEvaluation:
        return PositionEvaluation(
            decision=PositionDecision(
                stock_code=position.stock_code,
                as_of=position.as_of,
                status=PositionStatus.EXIT_RISK,
                action=DecisionAction.EXIT,
                reason_codes=(reason,),
                confidence=0.90,
            ),
            event_type=EventType.EXIT_RISK_CONFIRMED,
            target_status=PositionStatus.EXIT_RISK,
            persist_immediately=True,
            metadata_updates=metadata_updates or {},
        )

    @staticmethod
    def _hold(
        position: PositionSnapshot,
        state: PositionState | None,
        reason: str,
        *,
        status: PositionStatus = PositionStatus.HOLDING,
        metadata_updates=None,
    ) -> PositionEvaluation:
        return PositionEvaluation(
            decision=PositionDecision(
                stock_code=position.stock_code,
                as_of=position.as_of,
                status=status,
                action=DecisionAction.HOLD,
                reason_codes=(reason,),
                confidence=0.60,
            ),
            event_type=(
                EventType.POSITION_OPENED if state is None else EventType.POSITION_EFFICIENCY_CHANGED
            ),
            target_status=status,
            persist_immediately=state is None or state.status is not status,
            metadata_updates=metadata_updates or {},
        )
