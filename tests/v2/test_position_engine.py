import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from simple_trade.v2.application.positions.decision_engine import PositionDecisionEngine
from simple_trade.v2.application.positions.efficiency import PositionEfficiencyEngine
from simple_trade.v2.application.positions.rotation import RotationEvaluator
from simple_trade.v2.application.positions.structural_exit import StructuralExitPolicy
from simple_trade.v2.domain.candidates import TradeCandidate
from simple_trade.v2.domain.enums import (
    CapitalMemoryState,
    CandidateStatus,
    DataQuality,
    DecisionAction,
    PositionStatus,
)
from simple_trade.v2.domain.positions import PositionSnapshot, PositionState
from tests.v2.test_candidate_strategy import (
    capital_memory,
    snapshot as feature_snapshot,
    window,
)


NOW = datetime(2026, 8, 31, 11, 0, tzinfo=timezone(timedelta(hours=8)))


def position(price: float = 101, *, active_orders=()) -> PositionSnapshot:
    return PositionSnapshot(
        stock_code="HK.00100", stock_name="MINIMAX-W", as_of=NOW,
        quantity=1000, sellable_quantity=1000, cost_price=100,
        current_price=price, peak_price=price, lot_size=100,
        active_order_ids=active_orders,
    )


def state(
    *,
    status: PositionStatus = PositionStatus.HOLDING,
    peak: float = 103,
    mfe: float = 3,
    stalled_minutes: int | None = None,
) -> PositionState:
    return PositionState(
        stock_code="HK.00100", strategy_version="test-v2", status=status,
        version=2, last_event_id="prior", updated_at=NOW - timedelta(minutes=1),
        opened_at=NOW - timedelta(minutes=90), cost_price=100, peak_price=peak,
        trough_price=99, mfe_pct=mfe, mae_pct=-1,
        last_high_at=NOW - timedelta(minutes=30),
        stalled_since=(NOW - timedelta(minutes=stalled_minutes)
                       if stalled_minutes is not None else None),
        flow_peak=1_000_000,
        metadata={"last_persisted_at": NOW - timedelta(minutes=1)},
    )


def prices(flat: bool = True):
    return tuple(
        (NOW - timedelta(minutes=30 - index * 5), 101 + (0.02 * index if flat else index))
        for index in range(7)
    )


class PositionEngineTests(unittest.TestCase):
    @staticmethod
    def _add_feature(*, five_minute_sell_pressure: bool = False):
        window_15m = window(
            900,
            buys=3,
            sells=0,
            buy_amount=1_500_000,
            sell_amount=100_000,
            span=600,
            active_buy_amount=8_000_000,
            active_sell_amount=3_000_000,
        )
        window_5m = window(
            300,
            buys=0 if five_minute_sell_pressure else 1,
            sells=2 if five_minute_sell_pressure else 0,
            buy_amount=100_000 if five_minute_sell_pressure else 500_000,
            sell_amount=900_000 if five_minute_sell_pressure else 100_000,
            span=240,
            active_buy_amount=2_000_000,
            active_sell_amount=5_000_000 if five_minute_sell_pressure else 1_000_000,
        )
        memory = replace(
            capital_memory(state=CapitalMemoryState.ACCUMULATING),
            score=82,
            day_main_net=5_000_000,
            decayed_main_net=4_000_000,
            recent_15m_main_net=1_400_000,
            recent_15m_buy_events=3,
            recent_15m_sell_events=0,
        )
        return feature_snapshot(
            as_of=NOW,
            price=101,
            windows=(window_5m, window_15m),
            memory=memory,
        )

    def test_profitable_position_with_fresh_multi_inflow_confirms_one_add(self) -> None:
        feature = self._add_feature()
        efficiency = replace(
            PositionEfficiencyEngine().calculate(
                position(101), state(peak=101.4, mfe=1.4), feature, prices()
            ),
            current_return_pct=1.0,
            drawdown_from_peak_pct=-0.4,
            slope_15m_pct=0.35,
            score=78,
            stalled=False,
        )

        result = PositionDecisionEngine().evaluate(
            position(101), state(peak=101.4, mfe=1.4), efficiency, feature
        )

        self.assertIs(result.decision.action, DecisionAction.ADD)
        self.assertEqual(result.event_type.value, "POSITION_ADD_CONFIRMED")
        self.assertEqual(result.metadata_updates["suggested_add_ratio"], 0.10)
        self.assertEqual(result.metadata_updates["suggested_target_ratio"], 0.25)

    def test_five_minute_outflow_vetoes_add_even_when_15m_is_strong(self) -> None:
        feature = self._add_feature(five_minute_sell_pressure=True)
        efficiency = replace(
            PositionEfficiencyEngine().calculate(
                position(101), state(peak=101.4, mfe=1.4), feature, prices()
            ),
            current_return_pct=1.0,
            drawdown_from_peak_pct=-0.4,
            slope_15m_pct=0.35,
            score=78,
            stalled=False,
        )

        result = PositionDecisionEngine().evaluate(
            position(101), state(peak=101.4, mfe=1.4), efficiency, feature
        )

        self.assertIs(result.decision.action, DecisionAction.HOLD)
        self.assertNotEqual(result.event_type.value, "POSITION_ADD_CONFIRMED")

    def test_losing_or_already_prompted_position_never_adds(self) -> None:
        feature = self._add_feature()
        base = replace(
            PositionEfficiencyEngine().calculate(
                position(101), state(peak=101.4, mfe=1.4), feature, prices()
            ),
            current_return_pct=1.0,
            drawdown_from_peak_pct=-0.4,
            slope_15m_pct=0.35,
            score=78,
            stalled=False,
        )
        prompted_state = replace(
            state(peak=101.4, mfe=1.4),
            metadata={"add_prompt_count": 1},
        )

        prompted = PositionDecisionEngine().evaluate(
            position(101), prompted_state, base, feature
        )
        losing = PositionDecisionEngine().evaluate(
            position(99), state(peak=101.4, mfe=1.4),
            replace(base, current_return_pct=-1.0), feature,
        )

        self.assertIs(prompted.decision.action, DecisionAction.HOLD)
        self.assertIs(losing.decision.action, DecisionAction.HOLD)

    def test_medium_term_distribution_survives_empty_15m_window(self) -> None:
        empty_15m = window(900)
        outflow_30m = window(
            1800, buys=1, sells=7, buy_amount=500_000,
            sell_amount=5_000_000, span=900,
        )
        memory = replace(
            capital_memory(state=CapitalMemoryState.DISTRIBUTING),
            score=18,
            decayed_buy_amount=1_000_000,
            decayed_sell_amount=6_000_000,
            decayed_main_net=-5_000_000,
            decayed_buy_events=1.0,
            decayed_sell_events=7.0,
            reason_codes=("CAPITAL_MEMORY_DISTRIBUTING",),
        )
        feature = feature_snapshot(
            as_of=NOW, windows=(empty_15m, outflow_30m), memory=memory
        )

        efficiency = PositionEfficiencyEngine().calculate(
            position(102), state(peak=103), feature, prices()
        )
        decision = PositionDecisionEngine().evaluate(
            position(102), state(peak=103), efficiency, feature
        )

        self.assertEqual(efficiency.flow_current, -5_000_000)
        self.assertEqual(efficiency.flow_drawdown_ratio, 1)
        self.assertLess(efficiency.score, 65)
        self.assertEqual(
            decision.decision.reason_codes,
            ("REPEATED_OUTFLOW_ABSORBED_OR_SUPPORTED",),
        )

    def test_medium_term_distribution_exits_after_vwap_structure_break(self) -> None:
        medium = window(
            1800, buys=1, sells=7, buy_amount=500_000,
            sell_amount=5_000_000, span=900,
        )
        memory = replace(
            capital_memory(state=CapitalMemoryState.DISTRIBUTING),
            score=18,
            decayed_buy_amount=1_000_000,
            decayed_sell_amount=6_000_000,
            decayed_main_net=-5_000_000,
            decayed_buy_events=1.0,
            decayed_sell_events=7.0,
            reason_codes=("CAPITAL_MEMORY_DISTRIBUTING",),
        )
        feature = feature_snapshot(
            as_of=NOW, windows=(window(900), medium), accepted=False, memory=memory
        )
        base = PositionEfficiencyEngine().calculate(
            position(102), state(peak=103), feature, prices()
        )
        metadata = {}
        assessment = None
        for minute in range(5):
            observed_at = NOW + timedelta(minutes=minute)
            observed = replace(
                feature,
                computed_at=observed_at,
                price_acceptance=replace(feature.price_acceptance, as_of=observed_at),
            )
            assessment = StructuralExitPolicy().assess(
                replace(state(peak=103), metadata=metadata),
                replace(base, as_of=observed_at),
                observed,
            )
            metadata = dict(assessment.metadata_updates)

        self.assertIsNotNone(assessment)
        self.assertTrue(assessment.strong_outflow)
        self.assertEqual(
            assessment.exit_reason,
            "REPEATED_OUTFLOW_AND_STRUCTURE_BREAK",
        )

    def test_efficiency_tracks_mfe_mae_flow_decay_and_sustained_stall(self) -> None:
        feature = feature_snapshot(
            as_of=NOW,
            windows=(window(900, buys=1, buy_amount=400_000),),
        )
        result = PositionEfficiencyEngine().calculate(
            position(), state(), feature, prices(flat=True)
        )

        self.assertEqual(result.mfe_pct, 3)
        self.assertEqual(result.mae_pct, -1)
        self.assertGreater(result.flow_drawdown_ratio, 0.5)
        self.assertTrue(result.stalled)
        self.assertLessEqual(result.range_15m_pct, 0.8)

    def test_repeated_outflow_requires_price_break_for_exit(self) -> None:
        outflow = window(
            900, buys=1, sells=2, buy_amount=200_000, sell_amount=900_000, span=300
        )
        stable_feature = feature_snapshot(as_of=NOW, windows=(outflow,), accepted=True)
        stable_efficiency = PositionEfficiencyEngine().calculate(
            position(102.5), state(peak=103), stable_feature, prices()
        )
        stable = PositionDecisionEngine().evaluate(
            position(102.5), state(peak=103), stable_efficiency, stable_feature
        )
        self.assertIs(stable.decision.action, DecisionAction.HOLD)

        repeated = window(
            900, buys=1, sells=3, buy_amount=200_000, sell_amount=1_200_000, span=300
        )
        repeated_feature = feature_snapshot(
            as_of=NOW, windows=(repeated,), accepted=True
        )
        broken_efficiency = replace(
            stable_efficiency, drawdown_from_peak_pct=-2.0
        )
        broken = PositionDecisionEngine().evaluate(
            position(100.5), state(peak=103), broken_efficiency, repeated_feature
        )
        self.assertIs(broken.decision.action, DecisionAction.EXIT)
        self.assertEqual(
            broken.decision.reason_codes,
            ("REPEATED_OUTFLOW_AND_STRUCTURE_BREAK",),
        )

    def test_fast_decline_under_active_sell_pressure_does_not_look_efficient(self) -> None:
        pressured = window(
            900,
            buys=2,
            sells=2,
            buy_amount=10_300_000,
            sell_amount=12_000_000,
            active_buy_amount=19_100_000,
            active_sell_amount=40_770_000,
        )
        feature = feature_snapshot(as_of=NOW, windows=(pressured,), accepted=False)
        efficiency = replace(
            PositionEfficiencyEngine().calculate(
                position(101.04), state(peak=102.98, mfe=2.98), feature, prices()
            ),
            slope_15m_pct=-0.70,
            drawdown_from_peak_pct=-1.89,
            flow_current=-1_700_000,
            score=28.2,
            stalled=False,
        )
        metadata = {
            "exit_vwap_below_minutes": 9,
            "exit_last_vwap_minute": (NOW - timedelta(minutes=1)).isoformat(),
        }
        result = PositionDecisionEngine().evaluate(
            position(101.04), replace(state(peak=102.98, mfe=2.98), metadata=metadata),
            efficiency, feature,
        )

        self.assertIs(result.decision.action, DecisionAction.EXIT)
        self.assertEqual(
            result.decision.reason_codes,
            ("SUSTAINED_DOWNTREND_AND_VWAP_BREAK",),
        )

    def test_sell_pressure_waits_while_recent_support_is_fresh(self) -> None:
        support_time = NOW - timedelta(minutes=5)
        pressured = replace(
            window(
                900,
                buys=1,
                sells=1,
                buy_amount=5_200_000,
                sell_amount=6_500_000,
                active_buy_amount=19_100_000,
                active_sell_amount=40_770_000,
            ),
            first_independent_buy_at=support_time,
            last_independent_buy_at=support_time,
            first_independent_sell_at=NOW - timedelta(minutes=10),
            last_independent_sell_at=NOW - timedelta(minutes=10),
        )
        feature = feature_snapshot(as_of=NOW, windows=(pressured,), accepted=False)
        efficiency = replace(
            PositionEfficiencyEngine().calculate(
                position(101.04), state(peak=102.98, mfe=2.98), feature, prices()
            ),
            slope_15m_pct=-0.70,
            drawdown_from_peak_pct=-1.89,
            flow_current=-1_300_000,
            score=28.2,
            stalled=False,
        )
        metadata = {
            "exit_vwap_below_minutes": 9,
            "exit_last_vwap_minute": (NOW - timedelta(minutes=1)).isoformat(),
        }
        result = PositionDecisionEngine().evaluate(
            position(101.04), replace(state(peak=102.98, mfe=2.98), metadata=metadata),
            efficiency, feature,
        )

        self.assertIs(result.decision.action, DecisionAction.HOLD)
        self.assertIs(result.decision.status, PositionStatus.STALLED)
        self.assertEqual(
            result.decision.reason_codes,
            ("DOWNTREND_UNDER_SELL_PRESSURE",),
        )

    def test_premarket_time_is_not_counted_as_stalled_trading_time(self) -> None:
        as_of = NOW.replace(hour=10, minute=0)
        overnight = replace(
            state(),
            opened_at=NOW - timedelta(days=1),
            last_high_at=as_of.replace(hour=9, minute=1),
        )
        result = PositionEfficiencyEngine().calculate(
            replace(position(), as_of=as_of),
            overnight,
            feature_snapshot(as_of=as_of, windows=(window(900),)),
            (
                (as_of - timedelta(minutes=15), 101.0),
                (as_of, 101.0),
            ),
        )

        self.assertEqual(result.minutes_since_high, 30)

    def test_utc_reconciliation_uses_hong_kong_trading_session(self) -> None:
        hk_as_of = NOW.replace(hour=10, minute=30)
        utc_as_of = hk_as_of.astimezone(timezone.utc)
        overnight = replace(
            state(),
            opened_at=(hk_as_of - timedelta(days=1)).astimezone(timezone.utc),
            last_high_at=hk_as_of.replace(hour=9, minute=30).astimezone(timezone.utc),
        )
        result = PositionEfficiencyEngine().calculate(
            replace(position(), as_of=utc_as_of),
            overnight,
            feature_snapshot(as_of=hk_as_of, windows=(window(900),)),
            (
                (utc_as_of - timedelta(minutes=15), 101.0),
                (utc_as_of, 101.0),
            ),
        )

        self.assertEqual(result.minutes_since_high, 60)
        self.assertTrue(result.stalled)

    def test_trailing_protection_precedes_stall_rotation(self) -> None:
        feature = feature_snapshot(as_of=NOW)
        efficiency = PositionEfficiencyEngine().calculate(
            position(102), state(peak=103, mfe=3, stalled_minutes=20), feature, prices()
        )
        efficiency = replace(
            efficiency, drawdown_from_peak_pct=-1.6, stalled=True, mfe_pct=3
        )
        result = PositionDecisionEngine().evaluate(
            position(102), state(peak=103, mfe=3, stalled_minutes=20), efficiency, feature
        )

        self.assertIs(result.decision.action, DecisionAction.EXIT)
        self.assertEqual(result.decision.reason_codes, ("TRAIL_AFTER_SUPPORT_LOST",))

    def test_recent_inflow_support_blocks_trailing_exit(self) -> None:
        inflow = window(900, buys=3, buy_amount=1_500_000, span=600)
        inflow = replace(
            inflow,
            as_of=NOW,
            first_independent_buy_at=NOW - timedelta(minutes=10),
            last_independent_buy_at=NOW,
        )
        feature = feature_snapshot(as_of=NOW, windows=(inflow,), accepted=True)
        efficiency = PositionEfficiencyEngine().calculate(
            position(101), state(peak=103, mfe=3), feature, prices()
        )
        efficiency = replace(efficiency, drawdown_from_peak_pct=-2.0, mfe_pct=3)

        result = PositionDecisionEngine().evaluate(
            position(101), state(peak=103, mfe=3), efficiency, feature
        )

        self.assertIs(result.decision.action, DecisionAction.HOLD)
        self.assertEqual(
            result.metadata_updates["exit_last_support_at"],
            NOW.isoformat(),
        )

    def test_structural_exit_hard_boundaries_and_vwap_minutes(self) -> None:
        policy = StructuralExitPolicy()
        feature = feature_snapshot(as_of=NOW)
        base = PositionEfficiencyEngine().calculate(
            position(101), state(peak=103, mfe=3), feature, prices()
        )
        self.assertEqual(
            policy.assess(None, replace(base, current_return_pct=-3.0), feature).exit_reason,
            "HARD_STOP_3_PCT",
        )
        self.assertEqual(
            policy.assess(None, replace(base, current_return_pct=5.0), feature).exit_reason,
            "TAKE_PROFIT_5_PCT",
        )

        metadata = {}
        for minute in range(5):
            observed_at = NOW + timedelta(minutes=minute)
            below = replace(
                feature,
                computed_at=observed_at,
                price_acceptance=replace(
                    feature.price_acceptance,
                    as_of=observed_at,
                    distance_to_vwap_pct=-0.1,
                ),
            )
            assessment = policy.assess(
                replace(state(), metadata=metadata),
                replace(base, as_of=observed_at, mfe_pct=1, drawdown_from_peak_pct=-0.2),
                below,
            )
            metadata = dict(assessment.metadata_updates)
        self.assertEqual(metadata["exit_vwap_below_minutes"], 5)

    def test_buy_after_repeated_outflow_starts_support_grace(self) -> None:
        mixed = window(
            900,
            buys=1,
            sells=3,
            buy_amount=300_000,
            sell_amount=1_200_000,
            span=600,
        )
        mixed = replace(
            mixed,
            as_of=NOW,
            first_independent_sell_at=NOW - timedelta(minutes=10),
            last_independent_sell_at=NOW - timedelta(minutes=5),
            first_independent_buy_at=NOW,
            last_independent_buy_at=NOW,
        )
        feature = feature_snapshot(as_of=NOW, windows=(mixed,), accepted=True)
        base = PositionEfficiencyEngine().calculate(
            position(101), state(peak=103, mfe=3), feature, prices()
        )

        assessment = StructuralExitPolicy().assess(
            state(),
            replace(base, drawdown_from_peak_pct=-2.0, mfe_pct=3),
            feature,
        )

        self.assertTrue(assessment.strong_outflow)
        self.assertTrue(assessment.fresh_support)
        self.assertIsNone(assessment.exit_reason)

    def test_rotation_requires_confirmed_fresh_candidate_and_net_advantage(self) -> None:
        held_state = state(status=PositionStatus.STALLED, stalled_minutes=20)
        held_efficiency = PositionEfficiencyEngine().calculate(
            position(), held_state, feature_snapshot(as_of=NOW), prices()
        )
        held_efficiency = replace(held_efficiency, score=35, stalled=True)
        candidate = TradeCandidate(
            stock_code="HK.00200", as_of=NOW - timedelta(minutes=1),
            status=CandidateStatus.BUY_CONFIRMED, score=80, quality=DataQuality.GOOD,
            reason_codes=("FAST_CONFIRMED",), invalidation_conditions=("FLOW_FLIP",),
            confirmation_price=50,
        )
        feature = feature_snapshot(as_of=NOW)
        candidate_quote = replace(
            feature.quote, stock_code="HK.00200", last_price=50, lot_size=100
        )
        candidate_feature = replace(
            feature, stock_code="HK.00200", quote=candidate_quote,
            tick_windows=(),
        )

        proposal = RotationEvaluator().evaluate(
            position(), held_state, held_efficiency, (candidate,),
            {"HK.00200": candidate_feature}, {"HK.00100"},
        )
        self.assertIsNotNone(proposal)
        self.assertGreater(proposal.net_advantage_score, 0)
        self.assertEqual(proposal.sell_stock_code, "HK.00100")
        self.assertEqual(proposal.buy_stock_code, "HK.00200")

        unconfirmed = replace(candidate, status=CandidateStatus.SETUP)
        self.assertIsNone(RotationEvaluator().evaluate(
            position(), held_state, held_efficiency, (unconfirmed,),
            {"HK.00200": candidate_feature}, {"HK.00100"},
        ))

    def test_active_order_blocks_new_exit_or_rotation_decision(self) -> None:
        feature = feature_snapshot(as_of=NOW)
        efficiency = PositionEfficiencyEngine().calculate(
            position(96, active_orders=("sell-1",)), state(), feature, prices()
        )
        result = PositionDecisionEngine().evaluate(
            position(96, active_orders=("sell-1",)), state(), efficiency, feature
        )
        self.assertIs(result.decision.action, DecisionAction.HOLD)
        self.assertEqual(result.decision.reason_codes, ("ACTIVE_ORDER_CONFLICT",))

    def test_material_cost_basis_change_resets_path_metrics(self) -> None:
        changed = replace(position(101), cost_price=110)
        result = PositionEfficiencyEngine().calculate(
            changed, state(peak=130, mfe=30), feature_snapshot(as_of=NOW), prices()
        )

        self.assertIn("COST_BASIS_CHANGED", result.reason_codes)
        self.assertLess(result.mfe_pct, 1)
        self.assertGreater(result.mae_pct, -10)


if __name__ == "__main__":
    unittest.main()
