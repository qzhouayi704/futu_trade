"""Evaluate shared production exits against independently filled paper holdings."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import math

from ...domain.enums import DataQuality, DecisionAction, PositionStatus
from ...domain.events import FeatureSnapshotEvent
from ...domain.features import FeatureSnapshot
from ...domain.paper_session import PaperExperiment
from ...domain.planning.models import PaperAccount, PaperExitPolicy, PaperOrder
from ...domain.positions import PositionDecision, PositionSnapshot, PositionState
from ..planning.paper_engine import PaperEngine
from ..positions.decision_engine import PositionDecisionEngine
from ..positions.efficiency import PositionEfficiencyEngine
from ..positions.state_builder import evolve_state


@dataclass(frozen=True, slots=True)
class PaperPositionResult:
    reason: str
    decisions: tuple[PositionDecision, ...] = ()


class PaperPositionFollower:
    def __init__(self, experiment: PaperExperiment) -> None:
        self._experiment = experiment
        self._efficiency = PositionEfficiencyEngine()
        self._decisions = PositionDecisionEngine()

    def evaluate(self, account: PaperAccount, event: FeatureSnapshotEvent, when: datetime) -> PaperPositionResult:
        experiment, feature = self._experiment, event.snapshot
        if experiment.exit_policy is not PaperExitPolicy.PRODUCTION_RULES:
            return PaperPositionResult("PRODUCTION_EXIT_MODE_DISABLED")
        if event.strategy_version != experiment.strategy_version or event.stock_code not in experiment.stock_codes:
            return PaperPositionResult("POSITION_FEATURE_STRATEGY_MISMATCH")
        if experiment.interval_at(when) is None:
            return PaperPositionResult("TRADING_INTERVAL_UNAVAILABLE_OR_CLOSED")
        if (not feature.quote.quality is DataQuality.GOOD
                or not math.isfinite(feature.quote.last_price) or feature.quote.last_price <= 0):
            return PaperPositionResult("POSITION_QUOTE_INVALID")
        if (not event.exchange_time <= event.received_time <= when
                or not feature.quote.exchange_time <= event.exchange_time
                or not self._fresh(feature.quote.exchange_time, when)
                or not self._fresh(event.exchange_time, when)):
            return PaperPositionResult("POSITION_FEATURE_STALE_OR_FUTURE")
        orders = [order for order in account.orders
                  if order.plan.setup.stock_code == event.stock_code and order.held and not order.exit_reason]
        if not orders:
            return PaperPositionResult("NO_PAPER_POSITION_TO_EVALUATE")
        decisions = []
        for order in orders:
            fills = [fill for fill in account.fills if fill.plan_id == order.plan.plan_id and fill.side == "BUY"]
            if (feature.quote.exchange_time < max(fill.exchange_time for fill in fills)
                    or (order.position_state is not None and event.exchange_time <= order.position_state.updated_at)):
                return PaperPositionResult("POSITION_FEATURE_NOT_NEWER")
            decisions.append(self._evaluate_order(account, order, event, when, min(fill.exchange_time for fill in fills)))
        return PaperPositionResult("PRODUCTION_POSITION_EVALUATED", tuple(decisions))

    def _evaluate_order(self, account: PaperAccount, order: PaperOrder, event: FeatureSnapshotEvent,
                        when: datetime, opened_at: datetime) -> PositionDecision:
        feature = event.snapshot
        cost = float(order.buy_notional / order.bought)
        prior = order.position_state
        if prior is None:
            prior = PositionState(
                stock_code=event.stock_code, strategy_version=order.plan.setup.strategy_version,
                status=PositionStatus.HOLDING, version=1, last_event_id=event.event_id,
                updated_at=opened_at, opened_at=opened_at, cost_price=cost,
                peak_price=cost, trough_price=cost, mfe_pct=0.0, mae_pct=0.0, last_high_at=opened_at,
            )
        elif prior.cost_price != cost:
            # Partial buys change the cost basis, not the already observed price path.
            prior = replace(prior, cost_price=cost,
                            mfe_pct=(prior.peak_price / cost - 1) * 100,
                            mae_pct=(prior.trough_price / cost - 1) * 100)
        position = PositionSnapshot(
            stock_code=event.stock_code, as_of=event.exchange_time, quantity=order.held,
            sellable_quantity=order.held, cost_price=cost, current_price=feature.quote.last_price,
            peak_price=prior.peak_price, lot_size=order.plan.setup.lot_size,
        )
        prices = tuple(point for point in order.price_history
                       if point[0] >= event.exchange_time - timedelta(hours=1))
        prices += ((event.exchange_time, position.current_price),)
        if len(prices) > 2048:
            raise RuntimeError("PAPER_POSITION_HISTORY_BUDGET_EXCEEDED")
        complete = self._exit_evidence_complete(feature, when)
        evidence = feature if complete else None
        efficiency = self._efficiency.calculate(position, prior, evidence, prices)
        evaluation = self._decisions.evaluate(position, prior, efficiency, evidence, allow_additions=False)
        if not complete and evaluation.decision.reason_codes[0] not in {"HARD_STOP_3_PCT", "TAKE_PROFIT_5_PCT"}:
            # Missing flow evidence must not be interpreted as confirmed loss of support.
            evaluation = replace(evaluation, decision=replace(
                evaluation.decision, action=DecisionAction.HOLD, status=prior.status,
                reason_codes=("PRODUCTION_EXIT_EVIDENCE_INCOMPLETE",), confidence=0.0,
            ), target_status=prior.status, metadata_updates={})
        state = evolve_state(position, prior, efficiency, evaluation)
        order.position_state = replace(state, version=prior.version + 1, last_event_id=event.event_id)
        order.price_history = prices
        if evaluation.decision.action is DecisionAction.EXIT:
            PaperEngine.request_exit(account, order, evaluation.decision.reason_codes[0], when)
        return evaluation.decision

    def _fresh(self, stamp: datetime, when: datetime) -> bool:
        return 0 <= (when - stamp).total_seconds() <= self._experiment.maximum_signal_age_seconds

    def _exit_evidence_complete(self, feature: FeatureSnapshot, when: datetime) -> bool:
        acceptance = feature.price_acceptance
        if (acceptance is None or acceptance.quality is not DataQuality.GOOD
                or acceptance.vwap is None or acceptance.distance_to_vwap_pct is None
                or not math.isfinite(acceptance.vwap) or not math.isfinite(acceptance.distance_to_vwap_pct)
                or acceptance.as_of > feature.computed_at or not self._fresh(acceptance.as_of, when)):
            return False
        windows = [item for item in feature.tick_windows if item.window_seconds in {900, 1800, 3600}]
        if not any(item.window_seconds == 900 for item in windows):
            return False
        for item in windows:
            if (item.quality is not DataQuality.GOOD or item.as_of > feature.computed_at
                    or not self._fresh(item.as_of, when)
                    or any(stamp is not None and stamp > item.as_of for stamp in (
                        item.first_independent_buy_at, item.last_independent_buy_at,
                        item.first_independent_sell_at, item.last_independent_sell_at))):
                return False
        memory = feature.capital_memory
        return memory is None or (memory.quality is DataQuality.GOOD
                                  and memory.as_of <= feature.computed_at and self._fresh(memory.as_of, when))
