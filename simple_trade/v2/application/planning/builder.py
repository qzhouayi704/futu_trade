"""Pure long-only plan sizing against the complete reserved paper account."""

from datetime import datetime
from decimal import Decimal

from ...domain.planning.models import (
    EntrySetup, PaperAccount, PlanAssessment, TradePlan, ZERO,
)
from ...domain.serialization import require_aware
from ..strategy.assessments import EntryPlan


class PlanBuilder:
    @staticmethod
    def from_entry_plan(
        proposal: EntryPlan, *, source_event_id: str, strategy_version: str,
        valid_until: datetime, exit_at: datetime, lot_size: int,
    ) -> EntrySetup:
        """The caller must resolve the proposal's horizon using its trading calendar."""
        if proposal.add_conditions or proposal.exit_conditions:
            raise ValueError("conditional add/exit rules require an explicit replay policy")
        return EntrySetup(
            setup_id=proposal.setup_id, source_event_id=source_event_id,
            strategy_id=proposal.strategy_id, strategy_version=strategy_version,
            stock_code=proposal.stock_code, created_at=proposal.as_of,
            valid_until=valid_until, exit_at=exit_at, lot_size=lot_size,
            entry_min=Decimal(str(proposal.entry_price_min)),
            entry_limit=Decimal(str(min(proposal.entry_price_max, proposal.max_chase_price))),
            stop_price=Decimal(str(proposal.invalidation_price)),
            position_fraction=Decimal(str(proposal.initial_position_ratio)),
        )

    @staticmethod
    def assess(account: PaperAccount, setup: EntrySetup, when: datetime) -> PlanAssessment:
        require_aware(when, "when")
        plan_id = setup.plan_id(account.account_id)

        def reject(reason: str) -> PlanAssessment:
            return PlanAssessment(plan_id=plan_id, reason=reason)

        existing = next((order.plan for order in account.orders
                         if order.plan.plan_id == plan_id), None)
        if existing is not None:
            if existing.setup != setup:
                raise ValueError("immutable plan identity reused with different evidence/terms")
            return PlanAssessment(plan_id=plan_id, reason="ALREADY_PLANNED", plan=existing)
        if not setup.created_at <= when < setup.valid_until:
            return reject("ENTRY_WINDOW_CLOSED")
        active = [order for order in account.orders if order.active]
        if any(order.plan.setup.stock_code == setup.stock_code for order in active):
            return reject("STOCK_ALREADY_ALLOCATED")
        if any(order.plan.setup.source_event_id == setup.source_event_id for order in account.orders):
            return reject("SOURCE_EVENT_ALREADY_PLANNED")
        policy = account.policy
        if len(active) >= policy.max_positions:
            return reject("MAX_POSITIONS_REACHED")
        for order in active:
            if order.held:
                marked_at = account.book_times.get(order.plan.setup.stock_code)
                if marked_at is None or not 0 <= (when - marked_at).total_seconds() <= policy.max_book_age_seconds:
                    return reject("ACCOUNT_MARK_STALE")
        equity = account.equity
        cash_budget = max(ZERO, account.cash - account.reserved_cash
                          - equity * policy.cash_reserve_fraction)
        risk_budget = max(ZERO, min(
            equity * policy.risk_fraction,
            equity * policy.portfolio_risk_fraction
            - sum((order.risk(policy) for order in active), ZERO),
        ))
        value_budget = equity * min(policy.position_fraction,
                                    setup.position_fraction or policy.position_fraction)

        def required(quantity: int) -> tuple[Decimal, Decimal]:
            entry = quantity * setup.entry_limit
            exit_value = quantity * setup.stop_price
            return (entry + policy.fee(entry),
                    entry - exit_value + policy.fee(entry) + policy.fee(exit_value))

        upper = int(min(cash_budget, value_budget) / setup.entry_limit) // setup.lot_size
        lower = 0
        # Minimum order fees make direct division insufficient; feasibility is monotone.
        while lower < upper:
            lots = (lower + upper + 1) // 2
            cash, risk = required(lots * setup.lot_size)
            if cash <= cash_budget and risk <= risk_budget:
                lower = lots
            else:
                upper = lots - 1
        quantity = lower * setup.lot_size
        if not quantity:
            return reject("BELOW_ONE_LOT_BUDGET")
        _, risk = required(quantity)
        return PlanAssessment(
            plan_id=plan_id, reason="PAPER_PLAN_APPROVED",
            plan=TradePlan(plan_id=plan_id, setup=setup, quantity=quantity,
                           approved_at=when, initial_risk=risk),
        )
