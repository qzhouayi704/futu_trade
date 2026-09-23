from dataclasses import replace
from datetime import timedelta
import unittest

from simple_trade.v2.application.strategy.candidate_scorer import CandidateScorer
from simple_trade.v2.application.strategy.decision_builder import build_transition
from simple_trade.v2.application.strategy.models import UniverseDecision
from simple_trade.v2.application.strategy.portfolio import StrategyPortfolio
from simple_trade.v2.application.strategy.state_machine import CandidateStateMachine
from simple_trade.v2.domain.enums import CapitalMemoryState, DataQuality, EventType, StrategyStatus
from simple_trade.v2.domain.events import FeatureSnapshotEvent
from tests.v2.test_candidate_strategy import NOW, SOFT_INELIGIBLE, capital_memory, snapshot, state, window


def strong_watch(minutes=6):
    when = NOW + timedelta(minutes=minutes)
    memory = replace(capital_memory(as_of=when, state=CapitalMemoryState.ACCUMULATING),
                     day_main_net=1_000_000, recent_15m_buy_events=3)
    item = snapshot(as_of=when, rank=0.668, relative_strength=4,
                    memory=memory, windows=(window(900, buys=3, buy_amount=350_000, span=120),))
    return replace(item, price_position=replace(item.price_position, daily_percentile=0.66))


class StrongTrendObservationTests(unittest.TestCase):
    def setUp(self):
        self.machine = CandidateStateMachine()

    def watch_state(self, item):
        proposal = self.machine.evaluate(item, state(StrategyStatus.SETUP), SOFT_INELIGIBLE)
        return state(StrategyStatus.WATCHING, updated_at=item.computed_at,
                     metadata=proposal.metadata, confirmed_price=proposal.confirmation_price)

    def test_portfolio_watch_is_not_invalidated_by_shared_turnover_rank(self):
        item = strong_watch()
        nominations = StrategyPortfolio().evaluate(item, SOFT_INELIGIBLE, CandidateScorer().score(item))
        nomination = next(n for n in nominations.nominations if n.strategy_id == "strong_trend_reentry")
        self.assertEqual(nomination.stage, "WATCH")
        proposal = self.machine.evaluate(item, state(StrategyStatus.SETUP), SOFT_INELIGIBLE)
        self.assertEqual(proposal.new_status, StrategyStatus.WATCHING)
        self.assertFalse(proposal.alert_eligible)
        self.assertEqual(proposal.reason_code, "STRONG_TREND_SECOND_INFLOW_WATCH")

    def test_soft_rank_does_not_clear_valid_watch_after_grace(self):
        watching = self.watch_state(strong_watch())
        self.assertIsNone(self.machine.evaluate(strong_watch(12), watching, SOFT_INELIGIBLE))

    def test_persisted_watch_keeps_strategy_and_nonformal_permission(self):
        item = strong_watch()
        prior = state(StrategyStatus.SETUP)
        proposal = self.machine.evaluate(item, prior, SOFT_INELIGIBLE)
        score = CandidateScorer().score(item)
        portfolio = StrategyPortfolio().evaluate(item, SOFT_INELIGIBLE, score)
        source = FeatureSnapshotEvent(
            event_type=EventType.FEATURE_SNAPSHOT_READY, stock_code=item.stock_code,
            exchange_time=item.computed_at, received_time=item.computed_at,
            source="test", snapshot=item,
        )
        event, persisted = build_transition(source, prior, proposal, score, SOFT_INELIGIBLE,
                                            portfolio, strategy_version="test", schema_version=1)
        self.assertFalse(persisted.metadata["alert_eligible"])
        self.assertEqual(persisted.metadata["strategy_source"], "strong_trend_reentry")
        self.assertFalse(event.payload["alert_eligible"])
        self.assertEqual(event.payload["lifecycle_strategy_source"], "strong_trend_reentry")

    def test_existing_confirmation_threshold_still_required(self):
        watching = self.watch_state(strong_watch())
        item = strong_watch(7)
        self.assertIsNone(self.machine.evaluate(item, watching, SOFT_INELIGIBLE))
        ready = replace(item, tick_windows=(window(900, buys=3, buy_amount=1_000_000, span=120),))
        confirmed = self.machine.evaluate(ready, watching, SOFT_INELIGIBLE)
        self.assertEqual(confirmed.new_status, StrategyStatus.CONFIRMED)
        self.assertTrue(confirmed.alert_eligible)
        self.assertEqual(confirmed.reason_code, "STRONG_TREND_SECOND_INFLOW_CONFIRMED")

    def test_watch_expiry_and_hard_data_failure_remain_enforced(self):
        watching = self.watch_state(strong_watch())
        expired = self.machine.evaluate(strong_watch(22), watching, SOFT_INELIGIBLE)
        self.assertEqual(expired.reason_code, "FLOW_CONFIRMATION_EXPIRED")
        bad = replace(strong_watch(7), quality=DataQuality.INVALID)
        invalid = self.machine.evaluate(bad, watching, SOFT_INELIGIBLE)
        self.assertEqual(invalid.reason_code, "DATA_QUALITY_INVALID")

    def test_hard_universe_failure_cannot_enter_strong_watch(self):
        hard = UniverseDecision(eligible=False, reason_codes=("NOT_ACTIVE",))
        proposal = self.machine.evaluate(strong_watch(), state(StrategyStatus.SETUP), hard)
        self.assertNotEqual(proposal.new_status, StrategyStatus.WATCHING)

    def test_price_break_still_invalidates_observation(self):
        watching = self.watch_state(strong_watch())
        item = strong_watch(12)
        broken = replace(item, quote=replace(item.quote, last_price=90),
                         tick_windows=(), capital_memory=None,
                         price_acceptance=replace(item.price_acceptance, accepted=False,
                                                  distance_to_vwap_pct=-5))
        invalid = self.machine.evaluate(broken, watching, SOFT_INELIGIBLE)
        self.assertEqual(invalid.reason_code, "PRICE_ACCEPTANCE_BROKEN")
