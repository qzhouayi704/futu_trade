"""Deterministic candidate state machine driven only by a feature snapshot."""

from ...domain.decisions import StrategyState
from ...domain.enums import DataQuality, EventType, MarketRegime, StrategyStatus
from ...domain.features import FeatureSnapshot
from ...domain.market import TickAggregate
from .models import LegacySignalContext, TransitionProposal, UniverseDecision


class CandidateStateMachine:
    FAST_WINDOW_SECONDS = 900
    SLOW_WINDOW_SECONDS = 3600
    MIN_FAST_EVENT_SPAN_SECONDS = 300
    MIN_SLOW_EVENT_SPAN_SECONDS = 600
    REENTRY_COOLDOWN_SECONDS = 3600
    SOFT_REENTRY_SECONDS = 300
    UNIVERSE_GRACE_SECONDS = 300
    SOFT_UNIVERSE_REASONS = {
        "TURNOVER_RANK_NOT_HOT",
        "SECTOR_BREADTH_WEAK",
        "RELATIVE_STRENGTH_LOW",
    }

    def evaluate(
        self,
        snapshot: FeatureSnapshot,
        state: StrategyState | None,
        universe: UniverseDecision,
        legacy: LegacySignalContext | None = None,
    ) -> TransitionProposal | None:
        status = state.status if state is not None else StrategyStatus.IDLE
        if status is StrategyStatus.IDLE:
            return self._enter_setup(snapshot, universe) or self._enter_legacy_watch(
                snapshot, legacy, universe,
                event_type=EventType.CANDIDATE_ENTERED,
                reason="LEGACY_RALLY_STRONG_WATCH",
            )
        if status is StrategyStatus.INVALIDATED:
            return self._reenter_setup(snapshot, state, universe, legacy)
        if status is StrategyStatus.SETUP:
            if snapshot.quality is DataQuality.INVALID:
                return self._invalidate(
                    EventType.CANDIDATE_INVALIDATED,
                    universe,
                    reason="DATA_QUALITY_INVALID",
                )
            legacy_watch = self._enter_legacy_watch(
                snapshot, legacy, universe,
                event_type=EventType.CANDIDATE_UPDATED,
                reason="LEGACY_RALLY_SETUP_WATCH",
            )
            if legacy_watch is not None:
                return legacy_watch
            if not universe.eligible:
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
        if regime is not MarketRegime.EXTREME and self._fast_confirmed(fast):
            return self._confirm(snapshot, state, "FAST_15M_MULTI_INFLOW_CONFIRMED")
        if regime is MarketRegime.WEAK and self._slow_confirmed(slow, extreme=False):
            return self._confirm(
                snapshot, state, "WEAK_MARKET_60M_STRONG_STOCK_CONFIRMED"
            )
        if regime is MarketRegime.EXTREME and self._slow_confirmed(slow, extreme=True):
            return self._confirm(
                snapshot, state, "EXTREME_MARKET_60M_MULTI_INFLOW_CONFIRMED"
            )

        watch_seconds = (
            self.FAST_WINDOW_SECONDS
            if regime is MarketRegime.NORMAL
            else self.SLOW_WINDOW_SECONDS
        )
        if (snapshot.computed_at - state.updated_at).total_seconds() > watch_seconds:
            return TransitionProposal(
                new_status=StrategyStatus.INVALIDATED,
                event_type=EventType.BUY_INVALIDATED,
                reason_code="FLOW_CONFIRMATION_EXPIRED",
                metadata={"cooldown_started_at": snapshot.computed_at},
            )
        return None

    @staticmethod
    def _enter_setup(
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
    ) -> TransitionProposal | None:
        if not universe.eligible or snapshot.price_position.quality is DataQuality.INVALID:
            return None
        return TransitionProposal(
            new_status=StrategyStatus.SETUP,
            event_type=EventType.CANDIDATE_ENTERED,
            reason_code="HOT_ACTIVE_DAILY_SETUP",
            metadata={
                "setup_at": snapshot.computed_at,
                "daily_percentile": snapshot.price_position.daily_percentile,
                "daily_structure": snapshot.price_position.structure,
            },
        )

    def _reenter_setup(
        self,
        snapshot: FeatureSnapshot,
        state: StrategyState,
        universe: UniverseDecision,
        legacy: LegacySignalContext | None,
    ) -> TransitionProposal | None:
        elapsed = (snapshot.computed_at - state.updated_at).total_seconds()
        invalidation_reason = str(state.metadata.get("invalidation_reason") or "")
        if (
            elapsed >= self.SOFT_REENTRY_SECONDS
            and invalidation_reason in self.SOFT_UNIVERSE_REASONS
        ):
            watch = self._enter_legacy_watch(
                snapshot, legacy, universe,
                event_type=EventType.CANDIDATE_ENTERED,
                reason="SOFT_GATE_STRONG_SIGNAL_REENTRY",
            )
            if watch is not None:
                return watch
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
        if snapshot.quality is DataQuality.INVALID:
            return TransitionProposal(
                new_status=StrategyStatus.INVALIDATED,
                event_type=EventType.BUY_INVALIDATED,
                reason_code="DATA_QUALITY_INVALID",
                metadata={"cooldown_started_at": snapshot.computed_at},
            )
        fast = self._window(snapshot, self.FAST_WINDOW_SECONDS)
        if fast is not None and self._outflow_offsets_inflow(fast):
            return TransitionProposal(
                new_status=StrategyStatus.INVALIDATED,
                event_type=EventType.BUY_INVALIDATED,
                reason_code="LARGE_OUTFLOW_OFFSETS_INFLOW",
                metadata={"cooldown_started_at": snapshot.computed_at},
            )
        acceptance = snapshot.price_acceptance
        watch_price = self._number(state.metadata.get("watch_price")) if state else None
        watch_return = (
            (snapshot.quote.last_price / watch_price - 1.0) * 100.0
            if watch_price and snapshot.quote.last_price > 0
            else None
        )
        if (
            (watch_return is not None and watch_return < -1.0)
            or (
                acceptance is not None
                and (
                    (acceptance.distance_to_vwap_pct is not None and acceptance.distance_to_vwap_pct < -0.3)
                    or (acceptance.drawdown_from_peak_pct is not None and acceptance.drawdown_from_peak_pct < -1.0)
                )
            )
        ):
            return TransitionProposal(
                new_status=StrategyStatus.INVALIDATED,
                event_type=EventType.BUY_INVALIDATED,
                reason_code="PRICE_ACCEPTANCE_BROKEN",
                metadata={"cooldown_started_at": snapshot.computed_at},
            )
        if (
            not universe.eligible
            and state is not None
            and state.status is StrategyStatus.WATCHING
            and self._state_age(snapshot, state) > self.UNIVERSE_GRACE_SECONDS
        ):
            return TransitionProposal(
                new_status=StrategyStatus.INVALIDATED,
                event_type=EventType.BUY_INVALIDATED,
                reason_code="HOT_UNIVERSE_EXITED",
                metadata={"cooldown_started_at": snapshot.computed_at},
            )
        return None

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
        if window is None:
            return False
        threshold = window.large_order_threshold or 100_000.0
        scale = window.flow_scale or threshold
        return bool(
            window.independent_buy_events >= 2
            and window.independent_buy_span_seconds >= 300
            and window.main_net >= max(4.0 * threshold, 1.5 * scale)
            and (window.buy_sell_ratio or 0.0) >= 0.80
        )

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
        threshold = window.large_order_threshold or 100_000.0
        hard_flip = window.main_net <= -threshold
        material_offset = bool(
            window.independent_sell_events > 0
            and window.sell_amount > 0
            and window.sell_amount >= window.buy_amount * 0.80
            and (window.buy_sell_ratio or 0.0) < 0.55
        )
        return hard_flip or material_offset

    @staticmethod
    def _confirm(
        snapshot: FeatureSnapshot,
        state: StrategyState,
        reason: str,
    ) -> TransitionProposal | None:
        acceptance = snapshot.price_acceptance
        watch_price = CandidateStateMachine._number(state.metadata.get("watch_price"))
        if (
            snapshot.quality is not DataQuality.GOOD
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
            metadata={
                "confirmed_at": snapshot.computed_at,
                "confirmed_price": snapshot.quote.last_price,
                "protection_price": round(snapshot.quote.last_price * 0.99, 4),
                "expected_window_minutes": 15 if "15M" in reason else 60,
            },
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

    @classmethod
    def _enter_legacy_watch(
        cls,
        snapshot: FeatureSnapshot,
        legacy: LegacySignalContext | None,
        universe: UniverseDecision,
        *,
        event_type: EventType,
        reason: str,
    ) -> TransitionProposal | None:
        if legacy is None or not cls._legacy_signal_is_strong(snapshot, legacy, universe):
            return None
        return TransitionProposal(
            new_status=StrategyStatus.WATCHING,
            event_type=event_type,
            reason_code=reason,
            metadata={
                "watch_started_at": snapshot.computed_at,
                "watch_price": snapshot.quote.last_price,
                "legacy_signal_at": legacy.observed_at,
                "legacy_signal_source": legacy.source,
                "legacy_net_buy_amount": legacy.net_buy_amount,
                "legacy_price_change_pct": legacy.price_change_pct,
            },
        )

    @classmethod
    def _legacy_signal_is_strong(
        cls,
        snapshot: FeatureSnapshot,
        legacy: LegacySignalContext,
        universe: UniverseDecision,
    ) -> bool:
        hard_reasons = set(universe.reason_codes) - cls.SOFT_UNIVERSE_REASONS
        age = (snapshot.computed_at - legacy.observed_at).total_seconds()
        activity = snapshot.activity
        liquidity = snapshot.liquidity
        return bool(
            legacy.source == "absorption_scanner"
            and legacy.direction == "BUY"
            and 0 <= age <= 900
            and legacy.duration_minutes >= 5
            and 1.0 <= legacy.price_change_pct <= 2.5
            and legacy.net_buy_amount >= 1_000_000.0
            and legacy.position != "high"
            and legacy.signal_price > 0
            and snapshot.quote.last_price >= legacy.signal_price * 0.99
            and snapshot.quality is not DataQuality.INVALID
            and snapshot.price_position.quality is not DataQuality.INVALID
            and activity is not None
            and activity.is_active
            and liquidity is not None
            and liquidity.score >= 30
            and not hard_reasons
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
