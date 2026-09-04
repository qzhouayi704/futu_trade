"""Deterministic candidate state machine driven only by a feature snapshot."""

from ...domain.decisions import StrategyState
from ...domain.enums import (
    CapitalMemoryState,
    DataQuality,
    EventType,
    MarketRegime,
    StrategyStatus,
)
from ...domain.features import FeatureSnapshot
from ...domain.market import TickAggregate
from .models import TransitionProposal, UniverseDecision
from .portfolio import CandidateSignalRules


class CandidateStateMachine:
    FAST_WINDOW_SECONDS = 900
    SLOW_WINDOW_SECONDS = 3600
    MIN_FAST_EVENT_SPAN_SECONDS = 300
    MIN_SLOW_EVENT_SPAN_SECONDS = 600
    REENTRY_COOLDOWN_SECONDS = 3600
    SOFT_REENTRY_SECONDS = 300
    FLOW_REENTRY_SECONDS = 120
    UNIVERSE_GRACE_SECONDS = 300
    SETUP_ENRICHMENT_GRACE_SECONDS = 600
    QUOTE_SETUP_MAX_DAILY_PERCENTILE = 0.75
    LOW_POSITION_MAX_PERCENTILE = CandidateSignalRules.LOW_POSITION_MAX_PERCENTILE
    SOFT_UNIVERSE_REASONS = {
        "TURNOVER_RANK_NOT_HOT",
        "SECTOR_BREADTH_WEAK",
        "RELATIVE_STRENGTH_LOW",
    }
    OBSERVATION_BYPASS_REASONS = SOFT_UNIVERSE_REASONS | {
        "MARKET_CONTEXT_INCOMPLETE",
    }
    PRESETUP_BYPASS_REASONS = OBSERVATION_BYPASS_REASONS | {
        "SNAPSHOT_INVALID",
    }
    ENRICHABLE_SETUP_FIELDS = {
        "liquidity.spread",
        "liquidity.lot_size",
        "capital_windows.tick_stream",
        "capital_memory.event_stream",
        "price_acceptance.confirmation_price",
        "price_acceptance.vwap",
    }
    ENRICHABLE_CONFIRM_FIELDS = {
        "liquidity.spread",
        "liquidity.lot_size",
    }

    def evaluate(
        self,
        snapshot: FeatureSnapshot,
        state: StrategyState | None,
        universe: UniverseDecision,
    ) -> TransitionProposal | None:
        status = state.status if state is not None else StrategyStatus.IDLE
        if status is StrategyStatus.IDLE:
            # Every new stock first enters SETUP. This creates a deterministic
            # subscription/enrichment boundary before any fund-flow state.
            return (
                self._confirm_strong_trend_reentry(snapshot, universe)
                or self._enter_setup(snapshot, universe)
            )
        if status is StrategyStatus.INVALIDATED:
            return self._reenter_setup(snapshot, state, universe)
        if status is StrategyStatus.SETUP:
            strong_trend = self._confirm_strong_trend_reentry(snapshot, universe)
            if strong_trend is not None:
                return strong_trend
            memory_watch = self._enter_capital_memory_watch(
                snapshot, universe, event_type=EventType.CANDIDATE_UPDATED
            )
            if memory_watch is not None:
                return memory_watch
            low_position_watch = self._enter_low_position_watch(
                snapshot, universe, event_type=EventType.CANDIDATE_UPDATED
            )
            if low_position_watch is not None:
                return low_position_watch
            momentum_watch = self._enter_strict_momentum_watch(
                snapshot, universe, event_type=EventType.CANDIDATE_UPDATED
            )
            if momentum_watch is not None:
                return momentum_watch
            if snapshot.quality is DataQuality.INVALID:
                if self._quote_setup_context(snapshot, universe):
                    if self._state_age(snapshot, state) <= self.SETUP_ENRICHMENT_GRACE_SECONDS:
                        return None
                    return self._invalidate(
                        EventType.CANDIDATE_INVALIDATED,
                        universe,
                        reason="DATA_ENRICHMENT_TIMEOUT",
                    )
                return self._invalidate(
                    EventType.CANDIDATE_INVALIDATED,
                    universe,
                    reason="DATA_QUALITY_INVALID",
                )
            if not universe.eligible and not self._strict_momentum_context(
                snapshot, universe
            ):
                if self._state_age(snapshot, state) <= self.UNIVERSE_GRACE_SECONDS:
                    return None
                return self._invalidate(EventType.CANDIDATE_INVALIDATED, universe)
            window = self._window(snapshot, self.FAST_WINDOW_SECONDS)
            if window is not None and self._initial_inflow(window):
                return TransitionProposal(
                    new_status=StrategyStatus.WATCHING,
                    event_type=EventType.CANDIDATE_UPDATED,
                    reason_code="FIRST_STRONG_INFLOW_WATCH",
                    confirmation_price=snapshot.quote.last_price,
                    metadata={
                        "watch_started_at": snapshot.computed_at,
                        "watch_price": snapshot.quote.last_price,
                        "first_flow_at": window.first_independent_buy_at,
                    },
                )
            return None

        if status is StrategyStatus.WATCHING:
            strong_trend = self._confirm_strong_trend_reentry(snapshot, universe)
            if strong_trend is not None:
                return strong_trend
        if status in {StrategyStatus.WATCHING, StrategyStatus.CONFIRMED}:
            invalid = self._active_invalidation(snapshot, state, universe)
            if invalid is not None:
                return invalid
        if status is StrategyStatus.CONFIRMED:
            return None
        if status is not StrategyStatus.WATCHING or state is None:
            return None

        fast = self._window(snapshot, self.FAST_WINDOW_SECONDS)
        slow = self._window(snapshot, self.SLOW_WINDOW_SECONDS)
        regime = snapshot.market_context.market_regime
        low_position_watch = (
            state.metadata.get("watch_kind") == "low_position_accumulation"
        )
        capital_memory_watch = state.metadata.get("watch_kind") == "capital_memory"
        if (
            capital_memory_watch
            and self._low_position_market_confirmed(snapshot, universe)
            and snapshot.computed_at.timetz().replace(tzinfo=None)
            <= CandidateSignalRules.MEMORY_WATCH_CUTOFF
            and (
                self._low_position_accumulation(fast)
                or self._low_position_accumulation(slow)
            )
        ):
            return self._confirm(
                snapshot,
                state,
                "CAPITAL_MEMORY_MULTI_INFLOW_SHADOW_CONFIRMED",
                alert_eligible=False,
            )
        if (
            low_position_watch
            and self._low_position_market_confirmed(snapshot, universe)
            and CandidateSignalRules.before_entry_cutoff(snapshot)
            and (
                self._low_position_accumulation(fast)
                or self._low_position_accumulation(slow)
            )
        ):
            return self._confirm(
                snapshot, state, "LOW_POSITION_15M_ACCUMULATION_CONFIRMED"
            )
        if (
            self._strict_momentum_context(snapshot, universe)
            and self._fast_confirmed(fast)
        ):
            return self._confirm(
                snapshot,
                state,
                "STRICT_MOMENTUM_SHADOW_CONFIRMED",
                alert_eligible=False,
            )
        if (
            universe.eligible
            and regime is MarketRegime.WEAK
            and self._slow_confirmed(slow, extreme=False)
        ):
            return self._confirm(
                snapshot, state, "WEAK_MARKET_60M_STRONG_STOCK_CONFIRMED"
            )
        if (
            universe.eligible
            and regime is MarketRegime.EXTREME
            and self._slow_confirmed(slow, extreme=True)
        ):
            return self._confirm(
                snapshot, state, "EXTREME_MARKET_60M_MULTI_INFLOW_CONFIRMED"
            )

        watch_seconds = (
            self.SLOW_WINDOW_SECONDS
            if low_position_watch or capital_memory_watch or regime is not MarketRegime.NORMAL
            else self.FAST_WINDOW_SECONDS
        )
        if (snapshot.computed_at - state.updated_at).total_seconds() > watch_seconds:
            return TransitionProposal(
                new_status=StrategyStatus.INVALIDATED,
                event_type=EventType.BUY_INVALIDATED,
                reason_code="FLOW_CONFIRMATION_EXPIRED",
                metadata={"cooldown_started_at": snapshot.computed_at},
            )
        return None

    @classmethod
    def _enter_setup(
        cls,
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
    ) -> TransitionProposal | None:
        if not cls._quote_setup_context(snapshot, universe):
            return None
        if (
            snapshot.price_position.daily_percentile
            > cls.QUOTE_SETUP_MAX_DAILY_PERCENTILE
            and CandidateSignalRules.strong_trend_discovery_context(snapshot)
        ):
            reason = "STRONG_TREND_DISCOVERY_SETUP"
        elif snapshot.quality is DataQuality.INVALID:
            reason = "QUOTE_DATA_ENRICHMENT_SETUP"
        elif universe.eligible:
            reason = "HOT_ACTIVE_DAILY_SETUP"
        else:
            reason = "ACTIVE_QUOTE_PRESETUP"
        return TransitionProposal(
            new_status=StrategyStatus.SETUP,
            event_type=EventType.CANDIDATE_ENTERED,
            reason_code=reason,
            alert_eligible=False,
            metadata={
                "setup_at": snapshot.computed_at,
                "daily_percentile": snapshot.price_position.daily_percentile,
                "daily_structure": snapshot.price_position.structure,
                "pending_fields": snapshot.missing_fields,
                "alert_eligible": False,
            },
        )

    def _reenter_setup(
        self,
        snapshot: FeatureSnapshot,
        state: StrategyState,
        universe: UniverseDecision,
    ) -> TransitionProposal | None:
        elapsed = (snapshot.computed_at - state.updated_at).total_seconds()
        invalidation_reason = str(state.metadata.get("invalidation_reason") or "")
        if elapsed >= self.FLOW_REENTRY_SECONDS:
            strong_trend = self._confirm_strong_trend_reentry(snapshot, universe)
            if strong_trend is not None:
                return strong_trend
        if (
            elapsed >= self.SOFT_REENTRY_SECONDS
            and invalidation_reason in self.SOFT_UNIVERSE_REASONS
        ):
            memory_watch = self._enter_capital_memory_watch(
                snapshot, universe, event_type=EventType.CANDIDATE_ENTERED
            )
            if memory_watch is not None:
                return memory_watch
            low_position_watch = self._enter_low_position_watch(
                snapshot, universe, event_type=EventType.CANDIDATE_ENTERED
            )
            if low_position_watch is not None:
                return low_position_watch
            momentum_watch = self._enter_strict_momentum_watch(
                snapshot, universe, event_type=EventType.CANDIDATE_ENTERED
            )
            if momentum_watch is not None:
                return momentum_watch
        if elapsed < self.REENTRY_COOLDOWN_SECONDS:
            return None
        proposal = self._enter_setup(snapshot, universe)
        if proposal is None:
            return None
        return TransitionProposal(
            new_status=proposal.new_status,
            event_type=proposal.event_type,
            reason_code="COOLDOWN_COMPLETE_REENTER_SETUP",
            metadata=proposal.metadata,
        )

    def _active_invalidation(
        self,
        snapshot: FeatureSnapshot,
        state: StrategyState | None,
        universe: UniverseDecision,
    ) -> TransitionProposal | None:
        if (
            state is not None
            and state.metadata.get("watch_started_at") is not None
            and snapshot.computed_at <= state.updated_at
        ):
            return None
        if snapshot.quality is DataQuality.INVALID:
            return self._active_invalidated(snapshot, "DATA_QUALITY_INVALID")
        memory = snapshot.capital_memory
        if (
            state is not None
            and state.metadata.get("watch_kind") == "capital_memory"
            and memory is not None
            and memory.state is CapitalMemoryState.DISTRIBUTING
        ):
            return self._active_invalidated(
                snapshot, "CAPITAL_MEMORY_TURNED_DISTRIBUTING"
            )
        fast = self._window(snapshot, self.FAST_WINDOW_SECONDS)
        slow = self._window(snapshot, self.SLOW_WINDOW_SECONDS)
        fast_outflow = fast is not None and self._outflow_offsets_inflow(fast)
        slow_outflow = slow is not None and self._outflow_offsets_inflow(slow)
        if fast_outflow or (
            slow_outflow and not self._recent_inflow_recovered(snapshot, fast)
        ):
            return self._active_invalidated(snapshot, "LARGE_OUTFLOW_OFFSETS_INFLOW")
        acceptance = snapshot.price_acceptance
        watch_price = self._number(state.metadata.get("watch_price")) if state else None
        low_position_watch = bool(
            state and state.metadata.get("watch_kind") == "low_position_accumulation"
        )
        capital_memory_watch = bool(
            state and state.metadata.get("watch_kind") == "capital_memory"
        )
        tolerant_watch = low_position_watch or capital_memory_watch
        vwap_floor = -1.0 if tolerant_watch else -0.3
        pullback_limit = CandidateSignalRules.adaptive_pullback_limit_pct(
            snapshot,
            minimum=1.5 if tolerant_watch else 1.0,
        )
        drawdown_floor = -pullback_limit
        watch_return_floor = -pullback_limit
        watch_return = (
            (snapshot.quote.last_price / watch_price - 1.0) * 100.0
            if watch_price and snapshot.quote.last_price > 0
            else None
        )
        if (
            (watch_return is not None and watch_return < watch_return_floor)
            or (
                acceptance is not None
                and (
                    (
                        acceptance.distance_to_vwap_pct is not None
                        and acceptance.distance_to_vwap_pct < vwap_floor
                    )
                    or (
                        acceptance.drawdown_from_peak_pct is not None
                        and acceptance.drawdown_from_peak_pct < drawdown_floor
                    )
                )
            )
        ):
            return self._active_invalidated(snapshot, "PRICE_ACCEPTANCE_BROKEN")
        if (
            not universe.eligible
            and state is not None
            and state.status is StrategyStatus.WATCHING
            and self._state_age(snapshot, state) > self.UNIVERSE_GRACE_SECONDS
            and not self._strict_momentum_context(snapshot, universe)
            and not (
                tolerant_watch
                and bool(universe.reason_codes)
                and set(universe.reason_codes).issubset(
                    self.OBSERVATION_BYPASS_REASONS
                )
                and (
                    self._usable_global_context(snapshot)
                    or (
                        capital_memory_watch
                        and snapshot.market_context.quality is not DataQuality.INVALID
                        and snapshot.market_context.market_sample_size >= 20
                    )
                )
            )
        ):
            return self._active_invalidated(snapshot, "HOT_UNIVERSE_EXITED")
        return None

    @classmethod
    def _confirm_strong_trend_reentry(
        cls,
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
    ) -> TransitionProposal | None:
        hard_reasons = set(universe.reason_codes) - cls.SOFT_UNIVERSE_REASONS
        memory = snapshot.capital_memory
        if (
            hard_reasons
            or memory is None
            or not CandidateSignalRules.strong_trend_reentry_ready(snapshot)
        ):
            return None
        protection_pct = CandidateSignalRules.adaptive_pullback_limit_pct(
            snapshot,
            minimum=1.2,
        )
        return TransitionProposal(
            new_status=StrategyStatus.CONFIRMED,
            event_type=EventType.BUY_CONFIRMED,
            reason_code="STRONG_TREND_SECOND_INFLOW_CONFIRMED",
            confirmation_price=snapshot.quote.last_price,
            alert_eligible=True,
            metadata={
                "confirmed_at": snapshot.computed_at,
                "confirmed_price": snapshot.quote.last_price,
                "protection_price": round(
                    snapshot.quote.last_price * (1.0 - protection_pct / 100.0), 4
                ),
                "alert_eligible": True,
                "expected_window_minutes": 15,
                "watch_kind": "strong_trend_reentry",
                "capital_memory_score": memory.score,
                "day_main_net": memory.day_main_net,
                "recent_15m_main_net": memory.recent_15m_main_net,
                "recent_15m_buy_events": memory.recent_15m_buy_events,
            },
        )

    @staticmethod
    def _active_invalidated(
        snapshot: FeatureSnapshot,
        reason: str,
    ) -> TransitionProposal:
        return TransitionProposal(
            new_status=StrategyStatus.INVALIDATED,
            event_type=EventType.BUY_INVALIDATED,
            reason_code=reason,
            metadata={
                "cooldown_started_at": snapshot.computed_at,
                "invalidation_reason": reason,
            },
        )

    @classmethod
    def _enter_capital_memory_watch(
        cls,
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
        *,
        event_type: EventType,
    ) -> TransitionProposal | None:
        hard_reasons = set(universe.reason_codes) - cls.OBSERVATION_BYPASS_REASONS
        memory = snapshot.capital_memory
        if (
            hard_reasons
            or not CandidateSignalRules.capital_memory_watch_context(snapshot)
            or memory is None
        ):
            return None
        return TransitionProposal(
            new_status=StrategyStatus.WATCHING,
            event_type=event_type,
            reason_code="CAPITAL_MEMORY_REVERSAL_WATCH",
            confirmation_price=snapshot.quote.last_price,
            alert_eligible=False,
            metadata={
                "watch_started_at": snapshot.computed_at,
                "watch_price": snapshot.quote.last_price,
                "watch_kind": "capital_memory",
                "capital_memory_state": memory.state.value,
                "capital_memory_score": memory.score,
                "day_main_net": memory.day_main_net,
                "decayed_main_net": memory.decayed_main_net,
                "recent_15m_main_net": memory.recent_15m_main_net,
                "recent_15m_buy_events": memory.recent_15m_buy_events,
            },
        )

    @classmethod
    def _enter_low_position_watch(
        cls,
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
        *,
        event_type: EventType,
    ) -> TransitionProposal | None:
        hard_reasons = set(universe.reason_codes) - cls.OBSERVATION_BYPASS_REASONS
        position = snapshot.price_position
        acceptance = snapshot.price_acceptance
        activity = snapshot.activity
        liquidity = snapshot.liquidity
        window = cls._window(snapshot, cls.FAST_WINDOW_SECONDS)
        if not cls._low_position_accumulation(window):
            window = cls._window(snapshot, cls.SLOW_WINDOW_SECONDS)
        if (
            hard_reasons
            or snapshot.quality is DataQuality.INVALID
            or not cls._usable_global_context(snapshot)
            or position.quality is DataQuality.INVALID
            or position.daily_percentile > cls.LOW_POSITION_MAX_PERCENTILE
            or snapshot.market_context.market_breadth < CandidateSignalRules.MIN_MARKET_BREADTH
            or not CandidateSignalRules.before_entry_cutoff(snapshot)
            or activity is None
            or not activity.is_active
            or liquidity is None
            or liquidity.score < 30
            or acceptance is None
            or (
                acceptance.distance_to_vwap_pct is not None
                and acceptance.distance_to_vwap_pct < -1.0
            )
            or (
                acceptance.drawdown_from_peak_pct is not None
                and acceptance.drawdown_from_peak_pct < -1.5
            )
            or not cls._low_position_accumulation(window)
        ):
            return None
        return TransitionProposal(
            new_status=StrategyStatus.WATCHING,
            event_type=event_type,
            reason_code="LOW_POSITION_ACCUMULATION_WATCH",
            confirmation_price=snapshot.quote.last_price,
            metadata={
                "watch_started_at": snapshot.computed_at,
                "watch_price": snapshot.quote.last_price,
                "watch_kind": "low_position_accumulation",
                "first_flow_at": window.first_independent_buy_at,
                "daily_percentile": position.daily_percentile,
                "daily_structure": position.structure,
            },
        )

    @classmethod
    def _enter_strict_momentum_watch(
        cls,
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
        *,
        event_type: EventType,
    ) -> TransitionProposal | None:
        window = cls._window(snapshot, cls.FAST_WINDOW_SECONDS)
        if (
            not cls._strict_momentum_context(snapshot, universe)
            or window is None
            or not cls._initial_inflow(window)
        ):
            return None
        return TransitionProposal(
            new_status=StrategyStatus.WATCHING,
            event_type=event_type,
            reason_code="STRICT_MOMENTUM_WATCH",
            confirmation_price=snapshot.quote.last_price,
            metadata={
                "watch_started_at": snapshot.computed_at,
                "watch_price": snapshot.quote.last_price,
                "watch_kind": "strict_momentum",
                "first_flow_at": window.first_independent_buy_at,
            },
        )

    @staticmethod
    def _usable_global_context(snapshot: FeatureSnapshot) -> bool:
        context = snapshot.market_context
        return bool(
            context.quality is not DataQuality.INVALID
            and context.market_sample_size >= 20
            and context.turnover_rank_percentile is not None
        )

    @classmethod
    def _quote_setup_context(
        cls,
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
    ) -> bool:
        hard_reasons = set(universe.reason_codes) - cls.PRESETUP_BYPASS_REASONS
        activity = snapshot.activity
        liquidity = snapshot.liquidity
        if (
            hard_reasons
            or activity is None
            or not activity.is_active
            or liquidity is None
            or liquidity.score < 30
            or snapshot.price_position.quality is DataQuality.INVALID
            or (
                snapshot.price_position.daily_percentile
                > cls.QUOTE_SETUP_MAX_DAILY_PERCENTILE
                and not CandidateSignalRules.strong_trend_discovery_context(snapshot)
            )
            or not cls._usable_global_context(snapshot)
        ):
            return False
        if snapshot.quality is not DataQuality.INVALID:
            return True
        missing = set(snapshot.missing_fields)
        return bool(missing and missing.issubset(cls.ENRICHABLE_SETUP_FIELDS))

    @classmethod
    def setup_blockers(
        cls,
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
    ) -> tuple[str, ...]:
        """Return the concrete reasons a quote could not enter pre-candidate setup."""
        reasons = [
            reason
            for reason in universe.reason_codes
            if reason not in cls.PRESETUP_BYPASS_REASONS
        ]
        activity = snapshot.activity
        liquidity = snapshot.liquidity
        position = snapshot.price_position
        context = snapshot.market_context

        if activity is None or not activity.is_active:
            reasons.append("NOT_ACTIVE")
        if liquidity is None or liquidity.score < 30:
            reasons.append("LIQUIDITY_TOO_LOW")
        if position.quality is DataQuality.INVALID:
            reasons.append("DAILY_POSITION_INVALID")
        elif position.daily_percentile > cls.QUOTE_SETUP_MAX_DAILY_PERCENTILE:
            extension_atr = (
                position.distance_to_ma20 / position.atr_percent
                if position.atr_percent > 0
                else None
            )
            if (
                extension_atr is None
                or extension_atr > CandidateSignalRules.STRONG_TREND_MAX_EXTENSION_ATR
            ):
                reasons.append("PRICE_TOO_EXTENDED_FOR_ENTRY")
            elif not CandidateSignalRules.strong_trend_discovery_context(snapshot):
                reasons.append("STRONG_TREND_DISCOVERY_NOT_READY")
        if not cls._usable_global_context(snapshot):
            reasons.append("MARKET_CONTEXT_INCOMPLETE")
        if snapshot.quality is DataQuality.INVALID:
            missing = set(snapshot.missing_fields)
            if not missing or not missing.issubset(cls.ENRICHABLE_SETUP_FIELDS):
                reasons.append("DATA_QUALITY_INVALID")

        reasons.extend(universe.reason_codes)
        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _low_position_accumulation(window: TickAggregate | None) -> bool:
        return CandidateSignalRules.repeated_absorption(window)

    @staticmethod
    def _initial_inflow(window: TickAggregate) -> bool:
        threshold = window.large_order_threshold or 100_000.0
        scale = window.flow_scale or threshold
        return bool(
            window.independent_buy_events >= 1
            and window.main_net >= max(3.0 * threshold, scale)
            and (window.buy_sell_ratio or 0.0) >= 0.75
        )

    @staticmethod
    def _fast_confirmed(window: TickAggregate | None) -> bool:
        return CandidateSignalRules.fast_momentum(window)

    @staticmethod
    def _slow_confirmed(
        window: TickAggregate | None,
        *,
        extreme: bool,
    ) -> bool:
        if window is None:
            return False
        threshold = window.large_order_threshold or 100_000.0
        scale = window.flow_scale or threshold
        return bool(
            window.independent_buy_events >= 3
            and window.independent_buy_span_seconds >= 600
            and window.main_net >= max(
                (5.0 if extreme else 4.0) * threshold,
                (2.0 if extreme else 1.5) * scale,
            )
            and (window.buy_sell_ratio or 0.0) >= (5.0 / 6.0 if extreme else 0.80)
        )

    @staticmethod
    def _outflow_offsets_inflow(window: TickAggregate) -> bool:
        return CandidateSignalRules.outflow_offsets_inflow(window)

    @staticmethod
    def _recent_inflow_recovered(
        snapshot: FeatureSnapshot,
        fast: TickAggregate | None,
    ) -> bool:
        if (
            fast is not None
            and fast.independent_buy_events >= 2
            and fast.main_net > 0
            and (fast.buy_sell_ratio or 0.0) >= 0.65
        ):
            return True
        memory = snapshot.capital_memory
        return bool(
            memory is not None
            and memory.state is not CapitalMemoryState.DISTRIBUTING
            and memory.recent_15m_buy_events >= 2
            and memory.recent_15m_main_net > 0
        )

    @classmethod
    def _low_position_market_confirmed(
        cls,
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
    ) -> bool:
        hard_reasons = set(universe.reason_codes) - cls.OBSERVATION_BYPASS_REASONS
        return bool(
            not hard_reasons
            and cls._usable_global_context(snapshot)
            and snapshot.market_context.market_breadth
            >= CandidateSignalRules.MIN_MARKET_BREADTH
        )

    @classmethod
    def _strict_momentum_context(
        cls,
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
    ) -> bool:
        hard_reasons = set(universe.reason_codes) - cls.SOFT_UNIVERSE_REASONS
        return bool(
            not hard_reasons
            and CandidateSignalRules.strict_momentum_context(snapshot)
        )

    @staticmethod
    def _confirm(
        snapshot: FeatureSnapshot,
        state: StrategyState,
        reason: str,
        *,
        alert_eligible: bool = True,
    ) -> TransitionProposal | None:
        acceptance = snapshot.price_acceptance
        watch_price = CandidateStateMachine._number(state.metadata.get("watch_price"))
        if (
            not CandidateStateMachine._confirmation_quality_usable(snapshot)
            or acceptance is None
            or not acceptance.accepted
            or (watch_price is not None and snapshot.quote.last_price < watch_price)
        ):
            return None
        return TransitionProposal(
            new_status=StrategyStatus.CONFIRMED,
            event_type=EventType.BUY_CONFIRMED,
            reason_code=reason,
            confirmation_price=snapshot.quote.last_price,
            alert_eligible=alert_eligible,
            metadata={
                "confirmed_at": snapshot.computed_at,
                "confirmed_price": snapshot.quote.last_price,
                "protection_price": round(snapshot.quote.last_price * 0.99, 4),
                "alert_eligible": alert_eligible,
                "expected_window_minutes": (
                    15 if "15M" in reason or "MOMENTUM" in reason else 60
                ),
                "confirmation_quality": (
                    "GOOD"
                    if snapshot.quality is DataQuality.GOOD
                    else "DEGRADED_ENRICHABLE"
                ),
            },
        )

    @classmethod
    def _confirmation_quality_usable(cls, snapshot: FeatureSnapshot) -> bool:
        if snapshot.quality is DataQuality.GOOD:
            return True
        if snapshot.quality is DataQuality.INVALID:
            return False
        missing = set(snapshot.missing_fields)
        return bool(
            missing
            and missing.issubset(cls.ENRICHABLE_CONFIRM_FIELDS)
            and snapshot.quote.quality is DataQuality.GOOD
            and snapshot.price_position.quality is not DataQuality.INVALID
            and snapshot.market_context.quality is not DataQuality.INVALID
            and snapshot.price_acceptance is not None
            and snapshot.price_acceptance.quality is not DataQuality.INVALID
            and any(
                window.quality is not DataQuality.INVALID
                for window in snapshot.tick_windows
            )
        )

    @staticmethod
    def _invalidate(
        event_type: EventType,
        universe: UniverseDecision,
        *,
        reason: str | None = None,
    ) -> TransitionProposal:
        selected_reason = reason or universe.reason_codes[0]
        return TransitionProposal(
            new_status=StrategyStatus.INVALIDATED,
            event_type=event_type,
            reason_code=selected_reason,
            metadata={"invalidation_reason": selected_reason},
        )

    @staticmethod
    def _state_age(snapshot: FeatureSnapshot, state: StrategyState) -> float:
        return max(0.0, (snapshot.computed_at - state.updated_at).total_seconds())

    @staticmethod
    def _window(snapshot: FeatureSnapshot, seconds: int) -> TickAggregate | None:
        return next(
            (window for window in snapshot.tick_windows if window.window_seconds == seconds),
            None,
        )

    @staticmethod
    def _number(value: object) -> float | None:
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        return None
