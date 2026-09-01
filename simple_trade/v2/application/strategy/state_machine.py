"""Deterministic candidate state machine driven only by a feature snapshot."""

from datetime import datetime

from ...domain.decisions import StrategyState
from ...domain.enums import DataQuality, EventType, MarketRegime, StrategyStatus
from ...domain.features import FeatureSnapshot
from ...domain.market import TickAggregate
from .models import TransitionProposal, UniverseDecision


class CandidateStateMachine:
    FAST_WINDOW_SECONDS = 900
    SLOW_WINDOW_SECONDS = 3600
    MIN_FAST_EVENT_SPAN_SECONDS = 300
    MIN_SLOW_EVENT_SPAN_SECONDS = 600
    REENTRY_COOLDOWN_SECONDS = 3600

    def evaluate(
        self,
        snapshot: FeatureSnapshot,
        state: StrategyState | None,
        universe: UniverseDecision,
    ) -> TransitionProposal | None:
        status = state.status if state is not None else StrategyStatus.IDLE
        if status is StrategyStatus.IDLE:
            return self._enter_setup(snapshot, universe)
        if status is StrategyStatus.INVALIDATED:
            return self._reenter_setup(snapshot, state, universe)
        if status is StrategyStatus.SETUP:
            if not universe.eligible:
                return self._invalidate(EventType.CANDIDATE_INVALIDATED, universe)
            if snapshot.quality is DataQuality.INVALID:
                return self._invalidate(
                    EventType.CANDIDATE_INVALIDATED,
                    universe,
                    reason="DATA_QUALITY_INVALID",
                )
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
    ) -> TransitionProposal | None:
        elapsed = (snapshot.computed_at - state.updated_at).total_seconds()
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
        if not universe.eligible and state is not None and state.status is StrategyStatus.WATCHING:
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
        return TransitionProposal(
            new_status=StrategyStatus.INVALIDATED,
            event_type=event_type,
            reason_code=reason or universe.reason_codes[0],
        )

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
