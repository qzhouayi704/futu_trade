"""Cost-aware replacement comparison for confirmed candidates."""

from datetime import timedelta

from ...domain.candidates import TradeCandidate
from ...domain.enums import CandidateStatus
from ...domain.features import FeatureSnapshot
from ...domain.positions import PositionEfficiency, PositionSnapshot, PositionState, RotationProposal


class RotationEvaluator:
    MIN_HOLD_MINUTES = 30
    MIN_STALL_MINUTES = 15
    ESTIMATED_COST_PCT = 0.35
    COST_SCORE_PER_PERCENT = 20.0
    SAFETY_MARGIN_SCORE = 10.0

    def evaluate(
        self,
        position: PositionSnapshot,
        state: PositionState,
        efficiency: PositionEfficiency,
        candidates: tuple[TradeCandidate, ...],
        candidate_features: dict[str, FeatureSnapshot],
        held_codes: set[str],
    ) -> RotationProposal | None:
        if state.stalled_since is None or position.active_order_ids or position.sellable_quantity <= 0:
            return None
        if position.as_of - state.opened_at < timedelta(minutes=self.MIN_HOLD_MINUTES):
            return None
        if position.as_of - state.stalled_since < timedelta(minutes=self.MIN_STALL_MINUTES):
            return None
        cost_score = self.ESTIMATED_COST_PCT * self.COST_SCORE_PER_PERCENT
        for candidate in candidates:
            if (
                candidate.status is not CandidateStatus.BUY_CONFIRMED
                or candidate.stock_code in held_codes
                or position.as_of - candidate.as_of > timedelta(minutes=3)
            ):
                continue
            feature = candidate_features.get(candidate.stock_code)
            if feature is None or feature.quote.last_price <= 0 or feature.quote.lot_size is None:
                continue
            advantage = (
                candidate.score
                - efficiency.score
                - cost_score
                - self.SAFETY_MARGIN_SCORE
            )
            if advantage <= 0:
                continue
            available_value = position.sellable_quantity * position.current_price
            lot = feature.quote.lot_size
            estimated_quantity = int(available_value / feature.quote.last_price / lot) * lot
            if estimated_quantity <= 0:
                continue
            return RotationProposal(
                as_of=position.as_of,
                sell_stock_code=position.stock_code,
                sellable_quantity=position.sellable_quantity,
                buy_stock_code=candidate.stock_code,
                estimated_buy_quantity=estimated_quantity,
                estimated_buy_price=feature.quote.last_price,
                buy_lot_size=lot,
                held_efficiency_score=efficiency.score,
                candidate_score=candidate.score,
                estimated_cost_pct=self.ESTIMATED_COST_PCT,
                safety_margin_score=self.SAFETY_MARGIN_SCORE,
                net_advantage_score=round(advantage, 4),
                evidence={
                    "held_stalled_since": state.stalled_since,
                    "candidate_confirmed_at": candidate.as_of,
                    "candidate_reason_codes": candidate.reason_codes,
                },
            )
        return None
