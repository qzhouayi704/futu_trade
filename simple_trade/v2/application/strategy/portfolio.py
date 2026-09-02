"""Independent strategy nominations with one conservative ranking portfolio."""

from datetime import time

from ...domain.enums import CapitalMemoryState, DataQuality
from ...domain.features import FeatureSnapshot
from ...domain.market import TickAggregate
from ..features.quality import clamp
from .models import (
    CandidateScore,
    StrategyNomination,
    StrategyPortfolioResult,
    UniverseDecision,
)


class CandidateSignalRules:
    LOW_POSITION_MAX_PERCENTILE = 0.50
    MIN_MARKET_BREADTH = 0.40
    ENTRY_CUTOFF = time(11, 30)
    MEMORY_WATCH_CUTOFF = time(15, 15)
    MOMENTUM_MIN_RELATIVE_STRENGTH = 1.5
    MOMENTUM_MIN_ACTIVITY_PERCENTILE = 0.70
    MOMENTUM_MAX_EXTENSION_ATR = 1.0
    STRONG_TREND_MIN_DAILY_PERCENTILE = 0.50
    STRONG_TREND_MAX_EXTENSION_ATR = 2.5
    STRONG_TREND_MIN_RELATIVE_STRENGTH = 2.0
    STRONG_TREND_MIN_ACTIVITY_PERCENTILE = 0.70
    STRONG_TREND_MIN_MEMORY_SCORE = 65.0
    STRONG_TREND_MIN_EVENT_SPAN_SECONDS = 120
    STRONG_TREND_MIN_BUY_RATIO = 0.72
    MOMENTUM_SOFT_UNIVERSE_REASONS = {
        "TURNOVER_RANK_NOT_HOT",
        "SECTOR_BREADTH_WEAK",
        "RELATIVE_STRENGTH_LOW",
    }

    @staticmethod
    def window(snapshot: FeatureSnapshot, seconds: int) -> TickAggregate | None:
        return next(
            (item for item in snapshot.tick_windows if item.window_seconds == seconds),
            None,
        )

    @staticmethod
    def repeated_absorption(window: TickAggregate | None) -> bool:
        if window is None:
            return False
        threshold = window.large_order_threshold or 100_000.0
        scale = window.flow_scale or threshold
        return bool(
            window.independent_buy_events >= 3
            and window.independent_buy_span_seconds >= 600
            and window.main_net >= max(3.0 * threshold, scale)
            and (window.buy_sell_ratio or 0.0) >= 0.65
            and not CandidateSignalRules.outflow_offsets_inflow(window)
        )

    @staticmethod
    def fast_momentum(window: TickAggregate | None) -> bool:
        if window is None:
            return False
        threshold = window.large_order_threshold or 100_000.0
        scale = window.flow_scale or threshold
        return bool(
            window.independent_buy_events >= 3
            and window.independent_buy_span_seconds >= 600
            and window.main_net >= max(3.0 * threshold, 1.25 * scale)
            and (window.buy_sell_ratio or 0.0) >= 0.80
            and not CandidateSignalRules.outflow_offsets_inflow(window)
        )

    @staticmethod
    def fast_reaccumulation(window: TickAggregate | None) -> bool:
        if window is None:
            return False
        threshold = window.large_order_threshold or 100_000.0
        scale = window.flow_scale or threshold
        return bool(
            window.independent_buy_events >= 3
            and window.independent_buy_span_seconds
            >= CandidateSignalRules.STRONG_TREND_MIN_EVENT_SPAN_SECONDS
            and window.main_net >= max(4.0 * threshold, 1.5 * scale)
            and (window.buy_sell_ratio or 0.0)
            >= CandidateSignalRules.STRONG_TREND_MIN_BUY_RATIO
            and not CandidateSignalRules.outflow_offsets_inflow(window)
        )

    @classmethod
    def strong_trend_reentry_context(cls, snapshot: FeatureSnapshot) -> bool:
        memory = snapshot.capital_memory
        context = snapshot.market_context
        position = snapshot.price_position
        acceptance = snapshot.price_acceptance
        activity = snapshot.activity
        liquidity = snapshot.liquidity
        extension_atr = (
            position.distance_to_ma20 / position.atr_percent
            if position.atr_percent > 0
            else None
        )
        max_vwap_extension = min(3.0, max(1.5, position.atr_percent * 0.35))
        return bool(
            memory is not None
            and memory.quality is not DataQuality.INVALID
            and memory.state in {
                CapitalMemoryState.ABSORBING,
                CapitalMemoryState.REVERSING,
                CapitalMemoryState.ACCUMULATING,
            }
            and memory.score >= cls.STRONG_TREND_MIN_MEMORY_SCORE
            and memory.day_main_net > 0
            and memory.recent_15m_buy_events >= 3
            and memory.recent_15m_main_net > 0
            and snapshot.computed_at.timetz().replace(tzinfo=None)
            <= cls.MEMORY_WATCH_CUTOFF
            and snapshot.quality is not DataQuality.INVALID
            and position.quality is not DataQuality.INVALID
            and position.daily_percentile > cls.STRONG_TREND_MIN_DAILY_PERCENTILE
            and extension_atr is not None
            and extension_atr <= cls.STRONG_TREND_MAX_EXTENSION_ATR
            and context.quality is not DataQuality.INVALID
            and context.market_sample_size >= 20
            and context.turnover_rank_percentile is not None
            and context.turnover_rank_percentile
            >= cls.STRONG_TREND_MIN_ACTIVITY_PERCENTILE
            and context.relative_strength is not None
            and context.relative_strength >= cls.STRONG_TREND_MIN_RELATIVE_STRENGTH
            and activity is not None
            and activity.is_active
            and liquidity is not None
            and liquidity.score >= 30
            and acceptance is not None
            and acceptance.accepted
            and (
                acceptance.distance_to_vwap_pct is None
                or -0.3 <= acceptance.distance_to_vwap_pct <= max_vwap_extension
            )
        )

    @classmethod
    def strong_trend_reentry_ready(cls, snapshot: FeatureSnapshot) -> bool:
        return bool(
            cls.strong_trend_reentry_context(snapshot)
            and cls.fast_reaccumulation(cls.window(snapshot, 900))
        )

    @staticmethod
    def adaptive_pullback_limit_pct(
        snapshot: FeatureSnapshot,
        *,
        minimum: float,
    ) -> float:
        atr_limit = max(0.0, snapshot.price_position.atr_percent) * 0.25
        return min(2.5, max(minimum, atr_limit))

    @classmethod
    def strict_momentum_context(cls, snapshot: FeatureSnapshot) -> bool:
        context = snapshot.market_context
        position = snapshot.price_position
        activity = snapshot.activity
        liquidity = snapshot.liquidity
        acceptance = snapshot.price_acceptance
        extension_atr = (
            position.distance_to_ma20 / position.atr_percent
            if position.atr_percent > 0
            else None
        )
        return bool(
            snapshot.quality is DataQuality.GOOD
            and context.quality is DataQuality.GOOD
            and context.market_sample_size >= 20
            and context.turnover_rank_percentile is not None
            and context.turnover_rank_percentile >= cls.MOMENTUM_MIN_ACTIVITY_PERCENTILE
            and context.relative_strength is not None
            and context.relative_strength >= cls.MOMENTUM_MIN_RELATIVE_STRENGTH
            and position.quality is not DataQuality.INVALID
            and extension_atr is not None
            and extension_atr <= cls.MOMENTUM_MAX_EXTENSION_ATR
            and activity is not None
            and activity.is_active
            and liquidity is not None
            and liquidity.score >= 30
            and acceptance is not None
            and acceptance.accepted
            and (
                acceptance.distance_to_vwap_pct is None
                or acceptance.distance_to_vwap_pct >= -0.5
            )
        )

    @staticmethod
    def outflow_offsets_inflow(window: TickAggregate) -> bool:
        threshold = window.large_order_threshold or 100_000.0
        return bool(
            window.main_net <= -threshold
            or (
                window.independent_sell_events > 0
                and window.sell_amount > 0
                and window.sell_amount >= window.buy_amount * 0.80
                and (window.buy_sell_ratio or 0.0) < 0.55
            )
        )

    @classmethod
    def low_position_context(cls, snapshot: FeatureSnapshot) -> bool:
        acceptance = snapshot.price_acceptance
        return bool(
            snapshot.quality is not DataQuality.INVALID
            and snapshot.price_position.quality is not DataQuality.INVALID
            and snapshot.price_position.daily_percentile <= cls.LOW_POSITION_MAX_PERCENTILE
            and snapshot.market_context.quality is not DataQuality.INVALID
            and snapshot.market_context.market_sample_size >= 20
            and snapshot.market_context.market_breadth >= cls.MIN_MARKET_BREADTH
            and snapshot.activity is not None
            and snapshot.activity.is_active
            and snapshot.liquidity is not None
            and snapshot.liquidity.score >= 30
            and acceptance is not None
            and (acceptance.distance_to_vwap_pct is None or acceptance.distance_to_vwap_pct >= -1.0)
            and (acceptance.drawdown_from_peak_pct is None or acceptance.drawdown_from_peak_pct >= -1.5)
        )

    @classmethod
    def before_entry_cutoff(cls, snapshot: FeatureSnapshot) -> bool:
        return snapshot.computed_at.timetz().replace(tzinfo=None) <= cls.ENTRY_CUTOFF

    @classmethod
    def capital_memory_watch_context(cls, snapshot: FeatureSnapshot) -> bool:
        memory = snapshot.capital_memory
        acceptance = snapshot.price_acceptance
        return bool(
            memory is not None
            and memory.quality is not DataQuality.INVALID
            and memory.state in {
                CapitalMemoryState.ABSORBING,
                CapitalMemoryState.REVERSING,
                CapitalMemoryState.ACCUMULATING,
            }
            and memory.recent_15m_buy_events >= 1
            and memory.recent_15m_main_net > 0
            and snapshot.computed_at.timetz().replace(tzinfo=None)
            <= cls.MEMORY_WATCH_CUTOFF
            and snapshot.quality is not DataQuality.INVALID
            and snapshot.price_position.quality is not DataQuality.INVALID
            and snapshot.price_position.daily_percentile <= cls.LOW_POSITION_MAX_PERCENTILE
            and snapshot.market_context.quality is not DataQuality.INVALID
            and snapshot.market_context.market_sample_size >= 20
            and snapshot.activity is not None
            and snapshot.activity.is_active
            and snapshot.liquidity is not None
            and snapshot.liquidity.score >= 30
            and acceptance is not None
            and (
                acceptance.distance_to_vwap_pct is None
                or acceptance.distance_to_vwap_pct >= -1.0
            )
            and (
                acceptance.drawdown_from_peak_pct is None
                or acceptance.drawdown_from_peak_pct >= -1.5
            )
        )


class StrategyPortfolio:
    """Runs independent selectors; it cannot create a state transition."""

    def evaluate(
        self,
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
        base_score: CandidateScore,
    ) -> StrategyPortfolioResult:
        nominations = (
            self._capital_absorption(snapshot, base_score),
            self._capital_memory_reversal(snapshot, universe, base_score),
            self._strong_trend_reentry(snapshot, universe, base_score),
            self._momentum(snapshot, universe, base_score),
        )
        eligible = tuple(item for item in nominations if item.eligible)
        sources = tuple(item.strategy_id for item in eligible)
        best = max((item.score for item in eligible), default=base_score.total)
        return StrategyPortfolioResult(
            nominations=nominations,
            strategy_sources=sources,
            consensus_count=len(sources),
            ranking_score=round(min(100.0, max(base_score.total, best)), 4),
        )

    @staticmethod
    def _capital_absorption(
        snapshot: FeatureSnapshot,
        base: CandidateScore,
    ) -> StrategyNomination:
        fast = CandidateSignalRules.window(snapshot, 900)
        context_ok = CandidateSignalRules.low_position_context(snapshot)
        flow_ok = CandidateSignalRules.repeated_absorption(fast)
        cutoff_ok = CandidateSignalRules.before_entry_cutoff(snapshot)
        eligible = context_ok and flow_ok and cutoff_ok
        score = clamp(
            base.capital_flow * 0.45
            + base.price_acceptance * 0.25
            + base.daily_position * 0.20
            + snapshot.activity_score * 0.10
        )
        reasons = []
        if not context_ok:
            reasons.append("ABSORPTION_CONTEXT_NOT_READY")
        if not flow_ok:
            reasons.append("ABSORPTION_SEQUENCE_NOT_READY")
        if not cutoff_ok:
            reasons.append("ABSORPTION_ENTRY_WINDOW_CLOSED")
        return StrategyNomination(
            strategy_id="capital_absorption",
            eligible=eligible,
            stage="CONFIRMED" if eligible else "WATCH" if context_ok else "REJECTED",
            score=round(score, 4),
            reason_codes=tuple(reasons) or ("LOW_POSITION_REPEATED_ABSORPTION",),
        )

    @staticmethod
    def _capital_memory_reversal(
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
        base: CandidateScore,
    ) -> StrategyNomination:
        memory = snapshot.capital_memory
        fast = CandidateSignalRules.window(snapshot, 900)
        hard_reasons = set(universe.reason_codes) - (
            CandidateSignalRules.MOMENTUM_SOFT_UNIVERSE_REASONS
            | {"MARKET_CONTEXT_INCOMPLETE"}
        )
        watch_ready = bool(
            not hard_reasons
            and CandidateSignalRules.capital_memory_watch_context(snapshot)
        )
        confirmed = bool(
            watch_ready
            and snapshot.market_context.market_breadth
            >= CandidateSignalRules.MIN_MARKET_BREADTH
            and CandidateSignalRules.repeated_absorption(fast)
        )
        score = clamp(
            (memory.score if memory is not None else 0.0) * 0.45
            + base.price_acceptance * 0.25
            + base.daily_position * 0.20
            + base.activity * 0.10
        )
        return StrategyNomination(
            strategy_id="capital_memory_reversal",
            eligible=confirmed,
            stage="CONFIRMED" if confirmed else "WATCH" if watch_ready else "REJECTED",
            score=round(score, 4),
            reason_codes=(
                ("CAPITAL_MEMORY_MULTI_INFLOW_READY",)
                if confirmed
                else ("CAPITAL_MEMORY_REVERSAL_WATCH",)
                if watch_ready
                else tuple(hard_reasons) or ("CAPITAL_MEMORY_CONTEXT_NOT_READY",)
            ),
        )

    @staticmethod
    def _momentum(
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
        base: CandidateScore,
    ) -> StrategyNomination:
        fast = CandidateSignalRules.window(snapshot, 900)
        hard_reasons = set(universe.reason_codes) - (
            CandidateSignalRules.MOMENTUM_SOFT_UNIVERSE_REASONS
        )
        context_ok = not hard_reasons and CandidateSignalRules.strict_momentum_context(
            snapshot
        )
        eligible = bool(
            context_ok
            and CandidateSignalRules.fast_momentum(fast)
        )
        score = clamp(
            base.capital_flow * 0.40
            + base.price_acceptance * 0.30
            + base.activity * 0.15
            + base.relative_strength * 0.15
        )
        return StrategyNomination(
            strategy_id="momentum_continuation",
            eligible=eligible,
            stage="CONFIRMED" if eligible else "WATCH" if context_ok else "REJECTED",
            score=round(score, 4),
            reason_codes=(
                ("STRICT_MOMENTUM_SHADOW_READY",)
                if eligible
                else tuple(hard_reasons) or ("STRICT_MOMENTUM_CONTEXT_NOT_READY",)
            ),
        )

    @staticmethod
    def _strong_trend_reentry(
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
        base: CandidateScore,
    ) -> StrategyNomination:
        hard_reasons = set(universe.reason_codes) - (
            CandidateSignalRules.MOMENTUM_SOFT_UNIVERSE_REASONS
        )
        context_ok = bool(
            not hard_reasons
            and CandidateSignalRules.strong_trend_reentry_context(snapshot)
        )
        eligible = bool(
            context_ok and CandidateSignalRules.strong_trend_reentry_ready(snapshot)
        )
        memory_score = snapshot.capital_memory.score if snapshot.capital_memory else 0.0
        score = clamp(
            memory_score * 0.35
            + base.capital_flow * 0.30
            + base.price_acceptance * 0.20
            + base.relative_strength * 0.15
        )
        return StrategyNomination(
            strategy_id="strong_trend_reentry",
            eligible=eligible,
            stage="CONFIRMED" if eligible else "WATCH" if context_ok else "REJECTED",
            score=round(score, 4),
            reason_codes=(
                ("STRONG_TREND_SECOND_INFLOW_READY",)
                if eligible
                else tuple(hard_reasons) or ("STRONG_TREND_REENTRY_CONTEXT_NOT_READY",)
            ),
        )
