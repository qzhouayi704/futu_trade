import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from simple_trade.v2.application.strategy.candidate_scorer import CandidateScorer
from simple_trade.v2.application.strategy.models import LegacySignalContext, UniverseDecision
from simple_trade.v2.application.strategy.state_machine import CandidateStateMachine
from simple_trade.v2.application.strategy.universe import UniversePolicy
from simple_trade.v2.domain.decisions import StrategyState
from simple_trade.v2.domain.enums import DataQuality, EventType, MarketRegime, StrategyStatus
from simple_trade.v2.domain.features import (
    ActivityMetrics,
    FeatureSnapshot,
    LiquidityMetrics,
    MarketContext,
    PriceAcceptance,
    PricePosition,
)
from simple_trade.v2.domain.market import QuoteSnapshot, TickAggregate


NOW = datetime(2026, 8, 31, 10, 0, tzinfo=timezone(timedelta(hours=8)))


def window(
    seconds: int,
    *,
    buys: int = 0,
    sells: int = 0,
    buy_amount: float = 0,
    sell_amount: float = 0,
    span: int = 0,
) -> TickAggregate:
    total = buy_amount + sell_amount
    return TickAggregate(
        stock_code="HK.00100",
        as_of=NOW + timedelta(seconds=max(span, 1)),
        window_seconds=seconds,
        buy_amount=buy_amount,
        sell_amount=sell_amount,
        main_net=buy_amount - sell_amount,
        big_buy_count=buys,
        big_sell_count=sells,
        independent_buy_events=buys,
        independent_sell_events=sells,
        buy_sell_ratio=buy_amount / total if total else None,
        cumulative_main_net=buy_amount - sell_amount,
        cumulative_peak=max(0, buy_amount - sell_amount),
        cumulative_trough=min(0, buy_amount - sell_amount),
        last_sequence=buys + sells,
        sample_count=buys + sells,
        quality=DataQuality.GOOD,
        large_order_threshold=100_000,
        flow_scale=300_000,
        first_independent_buy_at=NOW if buys else None,
        last_independent_buy_at=NOW + timedelta(seconds=span) if buys else None,
        first_independent_sell_at=NOW if sells else None,
        last_independent_sell_at=NOW + timedelta(seconds=span) if sells else None,
    )


def snapshot(
    *,
    as_of: datetime = NOW,
    regime: MarketRegime = MarketRegime.NORMAL,
    windows: tuple[TickAggregate, ...] = (),
    price: float = 101,
    accepted: bool = True,
    rank: float = 0.95,
) -> FeatureSnapshot:
    quote = QuoteSnapshot(
        stock_code="HK.00100",
        exchange_time=as_of,
        last_price=price,
        prev_close=100,
        volume=2_000_000,
        turnover=100_000_000,
        turnover_rate=2,
        lot_size=100,
        sector_code="AI",
    )
    activity = ActivityMetrics(
        as_of=as_of, score=80, legacy_compatible_score=80,
        turnover_rate=2, turnover_amount=100_000_000, volume=2_000_000,
        is_active=True, quality=DataQuality.GOOD,
    )
    liquidity = LiquidityMetrics(
        as_of=as_of, score=80, level="A", spread_pct=0.1, lot_size=100,
        lot_value=10_100, turnover_amount=100_000_000, quality=DataQuality.GOOD,
    )
    acceptance = PriceAcceptance(
        as_of=as_of, score=80, confirmation_price=100, current_price=price,
        vwap=100.5, return_from_confirmation_pct=price - 100,
        distance_to_vwap_pct=0.4 if accepted else -0.5,
        drawdown_from_peak_pct=-0.2 if accepted else -1.2,
        accepted=accepted, quality=DataQuality.GOOD,
    )
    return FeatureSnapshot(
        stock_code=quote.stock_code,
        computed_at=as_of,
        quote=quote,
        tick_windows=windows,
        market_context=MarketContext(
            as_of=as_of, market_breadth=0.6 if regime is MarketRegime.NORMAL else 0.45,
            market_sample_size=30, sector_code="AI", sector_breadth=0.8,
            sector_sample_size=8, relative_strength=3, quality=DataQuality.GOOD,
            turnover_rank_percentile=rank, market_regime=regime,
        ),
        price_position=PricePosition(
            as_of=as_of, daily_percentile=0.35, atr_percent=3,
            drawdown_from_high=-5, distance_to_ma20=1, structure="MID",
            quality=DataQuality.GOOD,
        ),
        activity_score=80, liquidity_score=80, price_acceptance_score=80,
        quality=DataQuality.GOOD, activity=activity, liquidity=liquidity,
        price_acceptance=acceptance,
    )


def state(
    status: StrategyStatus,
    *,
    updated_at: datetime = NOW,
    metadata: dict | None = None,
) -> StrategyState:
    return StrategyState(
        stock_code="HK.00100", strategy_version="test-v2", status=status,
        version=1, last_event_id="previous", updated_at=updated_at,
        metadata=metadata or {},
    )


ELIGIBLE = UniverseDecision(eligible=True, reason_codes=())
SOFT_INELIGIBLE = UniverseDecision(
    eligible=False,
    reason_codes=("TURNOVER_RANK_NOT_HOT",),
)


def legacy_signal(
    *,
    observed_at: datetime = NOW,
    position: str = "low",
) -> LegacySignalContext:
    return LegacySignalContext(
        observed_at=observed_at,
        source="absorption_scanner",
        direction="BUY",
        severity="medium",
        duration_minutes=6,
        price_change_pct=1.6,
        net_buy_amount=2_000_000,
        position=position,
        signal_price=100.5,
    )


class CandidateStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = CandidateStateMachine()

    def test_universe_requires_hot_rank_and_scorer_only_returns_ranking(self) -> None:
        cold = snapshot(rank=0.60)
        decision = UniversePolicy().evaluate(cold)
        score = CandidateScorer().score(cold)

        self.assertFalse(decision.eligible)
        self.assertIn("TURNOVER_RANK_NOT_HOT", decision.reason_codes)
        self.assertGreaterEqual(score.total, 0)
        self.assertLessEqual(score.total, 100)
        self.assertFalse(hasattr(score, "event_type"))

    def test_idle_enters_setup_but_single_inflow_only_enters_watching(self) -> None:
        setup = self.machine.evaluate(snapshot(), None, ELIGIBLE)
        self.assertEqual(setup.new_status, StrategyStatus.SETUP)

        one = window(900, buys=1, buy_amount=900_000)
        watching = self.machine.evaluate(
            snapshot(windows=(one,)), state(StrategyStatus.SETUP), ELIGIBLE
        )
        self.assertEqual(watching.new_status, StrategyStatus.WATCHING)
        self.assertEqual(watching.event_type, EventType.CANDIDATE_UPDATED)

    def test_fast_confirmation_requires_multiple_spaced_inflows_and_acceptance(self) -> None:
        two = window(900, buys=2, buy_amount=1_200_000, span=301)
        result = self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(seconds=301), windows=(two,)),
            state(StrategyStatus.WATCHING, metadata={"watch_price": 100}),
            ELIGIBLE,
        )
        self.assertEqual(result.new_status, StrategyStatus.CONFIRMED)
        self.assertEqual(result.reason_code, "FAST_15M_MULTI_INFLOW_CONFIRMED")

        compressed = window(900, buys=2, buy_amount=1_200_000, span=10)
        self.assertIsNone(self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(seconds=10), windows=(compressed,)),
            state(StrategyStatus.WATCHING, metadata={"watch_price": 100}), ELIGIBLE,
        ))

        degraded = replace(
            snapshot(as_of=NOW + timedelta(seconds=301), windows=(two,)),
            quality=DataQuality.DEGRADED,
        )
        self.assertIsNone(self.machine.evaluate(
            degraded,
            state(StrategyStatus.WATCHING, metadata={"watch_price": 100}),
            ELIGIBLE,
        ))

    def test_weak_market_allows_sixty_minute_slow_confirmation(self) -> None:
        fast = window(900, buys=1, buy_amount=500_000)
        slow = window(3600, buys=3, buy_amount=1_500_000, span=900)
        result = self.machine.evaluate(
            snapshot(
                as_of=NOW + timedelta(seconds=900), regime=MarketRegime.WEAK,
                windows=(fast, slow),
            ),
            state(StrategyStatus.WATCHING, metadata={"watch_price": 100}),
            ELIGIBLE,
        )
        self.assertEqual(result.new_status, StrategyStatus.CONFIRMED)
        self.assertIn("60M", result.reason_code)

    def test_outflow_and_price_break_invalidate_before_confirmation(self) -> None:
        outflow = window(
            900, buys=1, sells=2, buy_amount=500_000, sell_amount=700_000, span=300
        )
        result = self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(seconds=300), windows=(outflow,)),
            state(StrategyStatus.WATCHING, metadata={"watch_price": 100}), ELIGIBLE,
        )
        self.assertEqual(result.new_status, StrategyStatus.INVALIDATED)
        self.assertEqual(result.reason_code, "LARGE_OUTFLOW_OFFSETS_INFLOW")

        price_break = self.machine.evaluate(
            snapshot(price=98.5, accepted=False),
            state(StrategyStatus.WATCHING, metadata={"watch_price": 100}), ELIGIBLE,
        )
        self.assertEqual(price_break.reason_code, "PRICE_ACCEPTANCE_BROKEN")

    def test_invalidated_state_respects_one_hour_reentry_cooldown(self) -> None:
        invalid = state(StrategyStatus.INVALIDATED, updated_at=NOW)
        self.assertIsNone(self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(minutes=59)), invalid, ELIGIBLE
        ))
        reentry = self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(minutes=61)), invalid, ELIGIBLE
        )
        self.assertEqual(reentry.new_status, StrategyStatus.SETUP)
        self.assertEqual(reentry.reason_code, "COOLDOWN_COMPLETE_REENTER_SETUP")

    def test_strong_rally_opens_watch_but_high_position_does_not(self) -> None:
        item = snapshot(as_of=NOW + timedelta(minutes=5))
        watch = self.machine.evaluate(
            item,
            None,
            SOFT_INELIGIBLE,
            legacy_signal(observed_at=NOW + timedelta(minutes=4)),
        )
        self.assertEqual(watch.new_status, StrategyStatus.WATCHING)
        self.assertEqual(watch.reason_code, "LEGACY_RALLY_STRONG_WATCH")

        self.assertIsNone(self.machine.evaluate(
            item,
            None,
            SOFT_INELIGIBLE,
            legacy_signal(observed_at=NOW + timedelta(minutes=4), position="high"),
        ))

    def test_soft_universe_gate_has_grace_and_fast_signal_reentry(self) -> None:
        setup_state = state(StrategyStatus.SETUP, updated_at=NOW)
        self.assertIsNone(self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(minutes=4)),
            setup_state,
            SOFT_INELIGIBLE,
        ))
        invalidated = self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(minutes=6)),
            setup_state,
            SOFT_INELIGIBLE,
        )
        self.assertEqual(invalidated.new_status, StrategyStatus.INVALIDATED)

        invalid_state = state(
            StrategyStatus.INVALIDATED,
            updated_at=NOW,
            metadata={"invalidation_reason": "TURNOVER_RANK_NOT_HOT"},
        )
        reentered = self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(minutes=6)),
            invalid_state,
            SOFT_INELIGIBLE,
            legacy_signal(observed_at=NOW + timedelta(minutes=5)),
        )
        self.assertEqual(reentered.new_status, StrategyStatus.WATCHING)
        self.assertEqual(reentered.reason_code, "SOFT_GATE_STRONG_SIGNAL_REENTRY")


if __name__ == "__main__":
    unittest.main()
