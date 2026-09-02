import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from simple_trade.v2.application.strategy.candidate_scorer import CandidateScorer
from simple_trade.v2.application.strategy.models import LegacySignalContext, UniverseDecision
from simple_trade.v2.application.strategy.portfolio import StrategyPortfolio
from simple_trade.v2.application.strategy.state_machine import CandidateStateMachine
from simple_trade.v2.application.strategy.universe import UniversePolicy
from simple_trade.v2.domain.decisions import StrategyState
from simple_trade.v2.domain.enums import (
    CapitalMemoryState,
    DataQuality,
    EventType,
    MarketRegime,
    StrategyStatus,
)
from simple_trade.v2.domain.features import (
    ActivityMetrics,
    FeatureSnapshot,
    LiquidityMetrics,
    MarketContext,
    PriceAcceptance,
    PricePosition,
)
from simple_trade.v2.domain.market import CapitalMemory, QuoteSnapshot, TickAggregate


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
    relative_strength: float = 3.0,
    sector_breadth: float = 0.8,
    atr_percent: float = 3.0,
    distance_to_ma20: float = 1.0,
    memory: CapitalMemory | None = None,
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
            market_sample_size=30, sector_code="AI", sector_breadth=sector_breadth,
            sector_sample_size=8, relative_strength=relative_strength,
            quality=DataQuality.GOOD,
            turnover_rank_percentile=rank, market_regime=regime,
        ),
        price_position=PricePosition(
            as_of=as_of, daily_percentile=0.35, atr_percent=atr_percent,
            drawdown_from_high=-5, distance_to_ma20=distance_to_ma20,
            structure="MID",
            quality=DataQuality.GOOD,
        ),
        activity_score=80, liquidity_score=80, price_acceptance_score=80,
        quality=DataQuality.GOOD, activity=activity, liquidity=liquidity,
        price_acceptance=acceptance, capital_memory=memory,
    )


def capital_memory(
    *,
    as_of: datetime = NOW,
    state: CapitalMemoryState = CapitalMemoryState.REVERSING,
) -> CapitalMemory:
    return CapitalMemory(
        stock_code="HK.00100",
        as_of=as_of,
        state=state,
        score=82,
        day_main_net=-1_000_000,
        day_peak=500_000,
        day_trough=-5_000_000,
        day_recovery_ratio=0.73,
        decayed_buy_amount=4_000_000,
        decayed_sell_amount=300_000,
        decayed_main_net=3_700_000,
        decayed_buy_events=1.8,
        decayed_sell_events=0.2,
        recent_15m_main_net=2_000_000,
        recent_15m_buy_events=2,
        recent_15m_sell_events=0,
        half_life_minutes=30,
        quality=DataQuality.GOOD,
        reason_codes=("CAPITAL_MEMORY_REVERSING",),
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

    def test_daily_position_has_meaningful_ranking_weight(self) -> None:
        base = snapshot(windows=(window(3600, buys=3, buy_amount=1_500_000, span=900),))
        low = replace(
            base,
            price_position=replace(base.price_position, daily_percentile=0.20),
        )
        high = replace(
            base,
            price_position=replace(base.price_position, daily_percentile=0.90),
        )

        low_score = CandidateScorer().score(low)
        high_score = CandidateScorer().score(high)

        self.assertGreaterEqual(low_score.total - high_score.total, 9.0)

    def test_strategy_portfolio_keeps_consensus_as_diagnostic_without_bonus(self) -> None:
        fast = window(900, buys=3, buy_amount=1_500_000, span=600)
        item = snapshot(as_of=NOW + timedelta(minutes=10), windows=(fast,))
        item = replace(
            item,
            price_position=replace(item.price_position, daily_percentile=0.20),
        )
        base = CandidateScorer().score(item)

        portfolio = StrategyPortfolio().evaluate(item, ELIGIBLE, base)

        self.assertIn("capital_absorption", portfolio.strategy_sources)
        self.assertIn("momentum_continuation", portfolio.strategy_sources)
        self.assertEqual(portfolio.consensus_count, 2)
        self.assertNotIn(
            "relative_strength",
            {item.strategy_id for item in portfolio.nominations},
        )
        self.assertEqual(
            portfolio.ranking_score,
            max(base.total, *(item.score for item in portfolio.nominations if item.eligible)),
        )

    def test_absorption_nomination_respects_breadth_and_entry_cutoff(self) -> None:
        fast = window(900, buys=3, buy_amount=1_500_000, span=600)
        base = snapshot(as_of=NOW + timedelta(minutes=10), windows=(fast,))
        weak_breadth = replace(
            base,
            market_context=replace(base.market_context, market_breadth=0.39),
        )
        late = replace(base, computed_at=NOW.replace(hour=11, minute=31))

        for item in (weak_breadth, late):
            score = CandidateScorer().score(item)
            result = StrategyPortfolio().evaluate(item, ELIGIBLE, score)
            self.assertNotIn("capital_absorption", result.strategy_sources)

    def test_idle_enters_setup_but_single_inflow_only_enters_watching(self) -> None:
        setup = self.machine.evaluate(snapshot(), None, ELIGIBLE)
        self.assertEqual(setup.new_status, StrategyStatus.SETUP)

        one = window(900, buys=1, buy_amount=900_000)
        watching = self.machine.evaluate(
            snapshot(windows=(one,)), state(StrategyStatus.SETUP), ELIGIBLE
        )
        self.assertEqual(watching.new_status, StrategyStatus.WATCHING)
        self.assertEqual(watching.event_type, EventType.CANDIDATE_UPDATED)

    def test_strict_momentum_requires_three_spaced_inflows_and_context(self) -> None:
        two = window(900, buys=2, buy_amount=1_200_000, span=301)
        self.assertIsNone(self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(seconds=301), windows=(two,)),
            state(StrategyStatus.WATCHING, metadata={"watch_price": 100}),
            ELIGIBLE,
        ))

        strict = window(900, buys=3, buy_amount=1_200_000, span=600)
        result = self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(seconds=600), windows=(strict,)),
            state(StrategyStatus.WATCHING, metadata={"watch_price": 100}),
            ELIGIBLE,
        )
        self.assertEqual(result.new_status, StrategyStatus.CONFIRMED)
        self.assertEqual(result.reason_code, "STRICT_MOMENTUM_SHADOW_CONFIRMED")
        self.assertFalse(result.alert_eligible)

        compressed = window(900, buys=3, buy_amount=1_200_000, span=10)
        self.assertIsNone(self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(seconds=10), windows=(compressed,)),
            state(StrategyStatus.WATCHING, metadata={"watch_price": 100}), ELIGIBLE,
        ))

        degraded = replace(
            snapshot(as_of=NOW + timedelta(seconds=600), windows=(strict,)),
            quality=DataQuality.DEGRADED,
        )
        self.assertIsNone(self.machine.evaluate(
            degraded,
            state(StrategyStatus.WATCHING, metadata={"watch_price": 100}),
            ELIGIBLE,
        ))

        for weak_context in (
            snapshot(
                as_of=NOW + timedelta(seconds=600), windows=(strict,),
                distance_to_ma20=4.0,
            ),
            snapshot(
                as_of=NOW + timedelta(seconds=600), windows=(strict,),
                relative_strength=1.0,
            ),
            snapshot(
                as_of=NOW + timedelta(seconds=600), windows=(strict,), rank=0.65,
            ),
        ):
            self.assertIsNone(self.machine.evaluate(
                weak_context,
                state(StrategyStatus.WATCHING, metadata={"watch_price": 100}),
                ELIGIBLE,
            ))

    def test_strict_momentum_can_bypass_weak_sector_breadth_only(self) -> None:
        strict = window(900, buys=3, buy_amount=1_200_000, span=600)
        item = snapshot(
            as_of=NOW + timedelta(seconds=600),
            windows=(strict,),
            sector_breadth=0.30,
        )
        soft = UniverseDecision(
            eligible=False,
            reason_codes=("SECTOR_BREADTH_WEAK",),
        )

        result = self.machine.evaluate(
            item,
            state(StrategyStatus.WATCHING, metadata={"watch_price": 100}),
            soft,
        )

        self.assertEqual(result.reason_code, "STRICT_MOMENTUM_SHADOW_CONFIRMED")
        self.assertFalse(result.alert_eligible)

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
        self.assertEqual(
            price_break.metadata["invalidation_reason"],
            "PRICE_ACCEPTANCE_BROKEN",
        )

    def test_high_atr_watch_uses_adaptive_price_acceptance_floor(self) -> None:
        item = snapshot(
            as_of=NOW + timedelta(minutes=1),
            price=99.6,
            atr_percent=8.0,
        )
        normal_pullback = replace(
            item,
            price_acceptance=replace(
                item.price_acceptance,
                accepted=False,
                distance_to_vwap_pct=0.7,
                drawdown_from_peak_pct=-1.01,
            ),
        )
        watching = state(
            StrategyStatus.WATCHING,
            metadata={"watch_price": 100},
        )

        self.assertIsNone(self.machine.evaluate(normal_pullback, watching, ELIGIBLE))

        broken = replace(
            normal_pullback,
            price_acceptance=replace(
                normal_pullback.price_acceptance,
                drawdown_from_peak_pct=-2.01,
            ),
        )
        invalidated = self.machine.evaluate(broken, watching, ELIGIBLE)
        self.assertEqual(invalidated.reason_code, "PRICE_ACCEPTANCE_BROKEN")

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

    def test_low_position_repeated_inflow_bypasses_only_soft_universe_gates(self) -> None:
        slow = window(
            3600,
            buys=4,
            sells=1,
            buy_amount=1_500_000,
            sell_amount=300_000,
            span=900,
        )
        item = snapshot(as_of=NOW + timedelta(minutes=15), windows=(slow,))
        item = replace(
            item,
            price_position=replace(item.price_position, daily_percentile=0.20),
        )

        watching = self.machine.evaluate(item, None, SOFT_INELIGIBLE)

        self.assertEqual(watching.new_status, StrategyStatus.WATCHING)
        self.assertEqual(watching.reason_code, "LOW_POSITION_ACCUMULATION_WATCH")
        self.assertEqual(watching.metadata["watch_kind"], "low_position_accumulation")

        incomplete_context = UniverseDecision(
            eligible=False,
            reason_codes=("MARKET_CONTEXT_INCOMPLETE",),
        )
        degraded = replace(
            item,
            market_context=replace(
                item.market_context,
                quality=DataQuality.DEGRADED,
                sector_code=None,
                sector_breadth=None,
                sector_sample_size=0,
                relative_strength=None,
            ),
            quality=DataQuality.DEGRADED,
        )
        self.assertEqual(
            self.machine.evaluate(degraded, None, incomplete_context).new_status,
            StrategyStatus.WATCHING,
        )

        invalid_context = replace(
            degraded,
            market_context=replace(
                degraded.market_context,
                quality=DataQuality.INVALID,
                market_sample_size=0,
                turnover_rank_percentile=None,
            ),
        )
        self.assertIsNone(
            self.machine.evaluate(invalid_context, None, incomplete_context)
        )

    def test_capital_memory_reversal_is_visible_in_weak_market_but_stays_shadow(self) -> None:
        as_of = NOW.replace(hour=14)
        item = snapshot(as_of=as_of, memory=capital_memory(as_of=as_of))
        item = replace(
            item,
            market_context=replace(item.market_context, market_breadth=0.15),
            price_position=replace(item.price_position, daily_percentile=0.20),
        )

        watch = self.machine.evaluate(item, None, SOFT_INELIGIBLE)

        self.assertEqual(watch.new_status, StrategyStatus.WATCHING)
        self.assertEqual(watch.reason_code, "CAPITAL_MEMORY_REVERSAL_WATCH")
        self.assertFalse(watch.alert_eligible)
        self.assertEqual(watch.metadata["watch_kind"], "capital_memory")
        watching = state(
            StrategyStatus.WATCHING,
            updated_at=as_of,
            metadata={"watch_price": 100, "watch_kind": "capital_memory"},
        )
        self.assertIsNone(self.machine.evaluate(item, watching, SOFT_INELIGIBLE))

        repeated = window(900, buys=3, buy_amount=1_500_000, span=600)
        confirmed_item = replace(
            item,
            tick_windows=(repeated,),
            market_context=replace(item.market_context, market_breadth=0.60),
        )
        confirmed = self.machine.evaluate(confirmed_item, watching, SOFT_INELIGIBLE)
        self.assertEqual(confirmed.new_status, StrategyStatus.CONFIRMED)
        self.assertEqual(
            confirmed.reason_code,
            "CAPITAL_MEMORY_MULTI_INFLOW_SHADOW_CONFIRMED",
        )
        self.assertFalse(confirmed.alert_eligible)

    def test_capital_memory_watch_invalidates_when_flow_turns_to_distribution(self) -> None:
        as_of = NOW.replace(hour=14)
        item = snapshot(
            as_of=as_of,
            memory=capital_memory(
                as_of=as_of, state=CapitalMemoryState.DISTRIBUTING
            ),
        )
        watching = state(
            StrategyStatus.WATCHING,
            updated_at=as_of,
            metadata={"watch_price": 101, "watch_kind": "capital_memory"},
        )

        result = self.machine.evaluate(item, watching, ELIGIBLE)

        self.assertEqual(result.new_status, StrategyStatus.INVALIDATED)
        self.assertEqual(result.reason_code, "CAPITAL_MEMORY_TURNED_DISTRIBUTING")

    def test_low_position_watch_requires_low_position_and_no_material_offset(self) -> None:
        accumulation = window(3600, buys=3, buy_amount=1_200_000, span=900)
        high = snapshot(as_of=NOW + timedelta(minutes=15), windows=(accumulation,))
        high = replace(
            high,
            price_position=replace(high.price_position, daily_percentile=0.80),
        )
        self.assertIsNone(self.machine.evaluate(high, None, SOFT_INELIGIBLE))

        offset = window(
            3600,
            buys=4,
            sells=3,
            buy_amount=1_200_000,
            sell_amount=1_100_000,
            span=900,
        )
        low = snapshot(as_of=NOW + timedelta(minutes=15), windows=(offset,))
        low = replace(
            low,
            price_position=replace(low.price_position, daily_percentile=0.20),
        )
        self.assertIsNone(self.machine.evaluate(low, None, SOFT_INELIGIBLE))

    def test_empty_fast_window_does_not_hide_valid_slow_accumulation(self) -> None:
        empty_fast = window(900)
        slow = window(3600, buys=4, buy_amount=1_800_000, span=900)
        item = snapshot(
            as_of=NOW + timedelta(minutes=15),
            windows=(empty_fast, slow),
        )
        item = replace(
            item,
            price_position=replace(item.price_position, daily_percentile=0.20),
        )

        watching = self.machine.evaluate(item, None, SOFT_INELIGIBLE)

        self.assertEqual(watching.new_status, StrategyStatus.WATCHING)
        self.assertEqual(watching.reason_code, "LOW_POSITION_ACCUMULATION_WATCH")

    def test_low_position_watch_can_confirm_through_soft_universe_gates(self) -> None:
        slow = window(3600, buys=4, buy_amount=1_800_000, span=900)
        item = snapshot(
            as_of=NOW + timedelta(minutes=15),
            regime=MarketRegime.WEAK,
            windows=(slow,),
        )
        item = replace(
            item,
            price_position=replace(item.price_position, daily_percentile=0.20),
        )
        watching = state(
            StrategyStatus.WATCHING,
            metadata={
                "watch_price": 100,
                "watch_kind": "low_position_accumulation",
            },
        )

        confirmed = self.machine.evaluate(item, watching, SOFT_INELIGIBLE)
        self.assertEqual(confirmed.new_status, StrategyStatus.CONFIRMED)
        self.assertTrue(confirmed.alert_eligible)
        self.assertEqual(
            confirmed.reason_code,
            "LOW_POSITION_15M_ACCUMULATION_CONFIRMED",
        )

    def test_soft_universe_gate_has_grace_and_fast_signal_reentry(self) -> None:
        setup_state = state(StrategyStatus.SETUP, updated_at=NOW)
        self.assertIsNone(self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(minutes=4), rank=0.60),
            setup_state,
            SOFT_INELIGIBLE,
        ))
        invalidated = self.machine.evaluate(
            snapshot(as_of=NOW + timedelta(minutes=6), rank=0.60),
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

    def test_high_position_second_inflow_reconfirms_after_price_invalidation(self) -> None:
        as_of = NOW + timedelta(minutes=3)
        fast = window(
            900,
            buys=5,
            buy_amount=56_000_000,
            span=300,
        )
        memory = replace(
            capital_memory(as_of=as_of, state=CapitalMemoryState.ACCUMULATING),
            score=86,
            day_main_net=189_000_000,
            day_peak=195_000_000,
            recent_15m_main_net=56_000_000,
            recent_15m_buy_events=5,
        )
        item = snapshot(
            as_of=as_of,
            regime=MarketRegime.EXTREME,
            windows=(fast,),
            price=169,
            sector_breadth=0.22,
            relative_strength=4.8,
            atr_percent=8.0,
            distance_to_ma20=17.0,
            memory=memory,
        )
        item = replace(
            item,
            market_context=replace(item.market_context, market_breadth=0.19),
            price_position=replace(
                item.price_position,
                daily_percentile=0.82,
                structure="HIGH",
            ),
        )
        invalid = state(
            StrategyStatus.INVALIDATED,
            updated_at=NOW,
            metadata={"invalidation_reason": "PRICE_ACCEPTANCE_BROKEN"},
        )

        reconfirmed = self.machine.evaluate(item, invalid, SOFT_INELIGIBLE)

        self.assertEqual(reconfirmed.new_status, StrategyStatus.CONFIRMED)
        self.assertEqual(reconfirmed.event_type, EventType.BUY_CONFIRMED)
        self.assertEqual(
            reconfirmed.reason_code,
            "STRONG_TREND_SECOND_INFLOW_CONFIRMED",
        )
        self.assertTrue(reconfirmed.alert_eligible)
        self.assertEqual(reconfirmed.metadata["protection_price"], 165.62)
        restart_recovered = self.machine.evaluate(item, None, SOFT_INELIGIBLE)
        self.assertEqual(restart_recovered.new_status, StrategyStatus.CONFIRMED)
        self.assertEqual(
            restart_recovered.reason_code,
            "STRONG_TREND_SECOND_INFLOW_CONFIRMED",
        )
        portfolio = StrategyPortfolio().evaluate(
            item,
            SOFT_INELIGIBLE,
            CandidateScorer().score(item),
        )
        self.assertIn("strong_trend_reentry", portfolio.strategy_sources)

    def test_high_position_reentry_rejects_overextension_and_offsetting_outflow(self) -> None:
        as_of = NOW + timedelta(minutes=3)
        memory = replace(
            capital_memory(as_of=as_of, state=CapitalMemoryState.ACCUMULATING),
            score=86,
            day_main_net=100_000_000,
            recent_15m_main_net=30_000_000,
            recent_15m_buy_events=5,
        )
        fast = window(
            900,
            buys=5,
            buy_amount=56_000_000,
            span=300,
        )
        base = snapshot(
            as_of=as_of,
            windows=(fast,),
            price=169,
            relative_strength=4.8,
            atr_percent=8.0,
            distance_to_ma20=21.0,
            memory=memory,
        )
        base = replace(
            base,
            price_position=replace(base.price_position, daily_percentile=0.82),
        )
        invalid = state(
            StrategyStatus.INVALIDATED,
            updated_at=NOW,
            metadata={"invalidation_reason": "PRICE_ACCEPTANCE_BROKEN"},
        )
        self.assertIsNone(self.machine.evaluate(base, invalid, SOFT_INELIGIBLE))

        offset = window(
            900,
            buys=5,
            sells=3,
            buy_amount=56_000_000,
            sell_amount=50_000_000,
            span=300,
        )
        not_extended = replace(
            base,
            tick_windows=(offset,),
            price_position=replace(base.price_position, distance_to_ma20=17.0),
        )
        self.assertIsNone(
            self.machine.evaluate(not_extended, invalid, SOFT_INELIGIBLE)
        )


if __name__ == "__main__":
    unittest.main()
