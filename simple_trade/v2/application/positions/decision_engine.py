"""Risk-first deterministic position decision rules."""

from ...domain.enums import DecisionAction, EventType, PositionStatus
from ...domain.features import FeatureSnapshot
from ...domain.positions import PositionDecision, PositionEfficiency, PositionSnapshot, PositionState
from .models import PositionEvaluation


class PositionDecisionEngine:
    FIXED_STOP_PCT = -3.0
    PROFIT_READY_PCT = 1.5
    PROFIT_PULLBACK_PCT = -0.8

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
        if efficiency.current_return_pct <= self.FIXED_STOP_PCT:
            return self._exit(position, "FIXED_STOP_LOSS")
        if self._structure_stop(efficiency, feature):
            return self._exit(position, "DAILY_STRUCTURE_STOP")

        strong_outflow = self._strong_outflow(feature)
        price_broken = self._price_broken(efficiency, feature)
        if strong_outflow and price_broken:
            return self._exit(position, "STRONG_OUTFLOW_AND_PRICE_BREAK")
        if strong_outflow:
            return self._hold(position, state, "OUTFLOW_ABSORBED_BY_PRICE")

        profit_ready = max(efficiency.mfe_pct, state.mfe_pct if state else 0.0) >= self.PROFIT_READY_PCT
        if profit_ready and efficiency.drawdown_from_peak_pct <= self.PROFIT_PULLBACK_PCT:
            return PositionEvaluation(
                decision=PositionDecision(
                    stock_code=position.stock_code,
                    as_of=position.as_of,
                    status=PositionStatus.PROFIT_READY,
                    action=DecisionAction.PROTECT_PROFIT,
                    reason_codes=("PROFIT_1_5_THEN_PULLBACK",),
                    confidence=0.80,
                ),
                event_type=EventType.POSITION_EFFICIENCY_CHANGED,
                target_status=PositionStatus.PROFIT_READY,
                persist_immediately=True,
            )
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
            )
        status = PositionStatus.PROFIT_READY if profit_ready else PositionStatus.HOLDING
        return self._hold(position, state, "POSITION_EFFICIENT", status=status)

    @staticmethod
    def _structure_stop(
        efficiency: PositionEfficiency,
        feature: FeatureSnapshot | None,
    ) -> bool:
        return bool(
            feature is not None
            and efficiency.current_return_pct <= -1.5
            and feature.price_position.distance_to_ma20 <= -2.0
        )

    @staticmethod
    def _strong_outflow(feature: FeatureSnapshot | None) -> bool:
        if feature is None:
            return False
        window = next(
            (item for item in feature.tick_windows if item.window_seconds == 900),
            None,
        )
        if window is None:
            return False
        threshold = window.large_order_threshold or 100_000.0
        return bool(
            window.main_net <= -threshold
            or (
                window.independent_sell_events > 0
                and window.sell_amount >= max(threshold, window.buy_amount * 1.2)
            )
        )

    @staticmethod
    def _price_broken(
        efficiency: PositionEfficiency,
        feature: FeatureSnapshot | None,
    ) -> bool:
        if efficiency.drawdown_from_peak_pct <= -1.5:
            return True
        if feature is None:
            return efficiency.current_return_pct < -1.0
        acceptance = feature.price_acceptance
        below_vwap = bool(
            acceptance is not None
            and acceptance.distance_to_vwap_pct is not None
            and acceptance.distance_to_vwap_pct < -0.3
        )
        return below_vwap or feature.price_position.distance_to_ma20 < -1.0

    @staticmethod
    def _exit(position: PositionSnapshot, reason: str) -> PositionEvaluation:
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
        )

    @staticmethod
    def _hold(
        position: PositionSnapshot,
        state: PositionState | None,
        reason: str,
        *,
        status: PositionStatus = PositionStatus.HOLDING,
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
        )
