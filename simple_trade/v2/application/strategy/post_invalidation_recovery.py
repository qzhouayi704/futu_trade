"""State-aware confirmation policy for intraday flow reversals after invalidation."""

from dataclasses import dataclass
from datetime import time

from ...domain.decisions import StrategyState
from ...domain.enums import DataQuality
from ...domain.features import FeatureSnapshot
from ...domain.market import TickAggregate
from .models import UniverseDecision


@dataclass(frozen=True, slots=True)
class RecoveryEvidence:
    local_low_price: float
    rebound_from_low_pct: float
    active_buy_ratio_1m: float
    active_buy_ratio_5m: float
    capital_recovery_amount: float
    capital_recovery_ratio: float

    def metadata(self) -> dict[str, float | str]:
        return {
            "watch_kind": "post_invalidation_reversal",
            "strategy_source": "post_invalidation_flow_recovery",
            "local_low_price": round(self.local_low_price, 4),
            "rebound_from_low_pct": round(self.rebound_from_low_pct, 4),
            "active_buy_ratio_1m": round(self.active_buy_ratio_1m, 4),
            "active_buy_ratio_5m": round(self.active_buy_ratio_5m, 4),
            "capital_recovery_amount": round(self.capital_recovery_amount, 2),
            "capital_recovery_ratio": round(self.capital_recovery_ratio, 4),
        }


class PostInvalidationRecoveryPolicy:
    """Require persistent active buying after an invalidated candidate finds a low."""

    WATCH_MIN_AGE_SECONDS = 60
    WATCH_MAX_AGE_SECONDS = 3600
    CONFIRM_MIN_AGE_SECONDS = 60
    CONFIRM_MAX_AGE_SECONDS = 900
    ENTRY_CUTOFF = time(15, 15)
    MIN_REBOUND_FROM_LOW_PCT = 1.5
    MIN_WATCH_ACTIVE_BUY_RATIO_1M = 0.60
    MIN_WATCH_ACTIVE_BUY_RATIO_5M = 0.52
    MIN_CONFIRM_ACTIVE_BUY_RATIO_1M = 0.60
    MIN_CONFIRM_ACTIVE_BUY_RATIO_5M = 0.58
    MIN_WATCH_RECOVERY_RATIO = 0.15
    MIN_CONFIRM_RECOVERY_RATIO = 0.55
    MIN_WATCH_BUY_EVENTS_5M = 2
    MIN_CONFIRM_BUY_EVENTS_5M = 3
    ALLOWED_INVALIDATION_REASONS = {
        "MARKET_CONTEXT_INCOMPLETE",
        "DATA_QUALITY_INVALID",
        "DATA_ENRICHMENT_TIMEOUT",
        "TURNOVER_RANK_NOT_HOT",
        "SECTOR_BREADTH_WEAK",
        "RELATIVE_STRENGTH_LOW",
        "LARGE_OUTFLOW_OFFSETS_INFLOW",
        "PRICE_ACCEPTANCE_BROKEN",
    }
    ALLOWED_UNIVERSE_REASONS = {
        "MARKET_CONTEXT_INCOMPLETE",
        "TURNOVER_RANK_NOT_HOT",
        "SECTOR_BREADTH_WEAK",
        "RELATIVE_STRENGTH_LOW",
    }

    def watch_evidence(
        self,
        snapshot: FeatureSnapshot,
        state: StrategyState,
        universe: UniverseDecision,
    ) -> RecoveryEvidence | None:
        elapsed = (snapshot.computed_at - state.updated_at).total_seconds()
        invalidation_reason = str(state.metadata.get("invalidation_reason") or "")
        if (
            elapsed < self.WATCH_MIN_AGE_SECONDS
            or elapsed > self.WATCH_MAX_AGE_SECONDS
            or invalidation_reason not in self.ALLOWED_INVALIDATION_REASONS
            or not self._common_context(snapshot, universe)
        ):
            return None
        evidence = self._evidence(snapshot)
        one_minute = self._window(snapshot, 60)
        five_minutes = self._window(snapshot, 300)
        if evidence is None or one_minute is None or five_minutes is None:
            return None
        if not (
            self.MIN_REBOUND_FROM_LOW_PCT
            <= evidence.rebound_from_low_pct
            <= self._watch_rebound_cap(snapshot)
            and evidence.active_buy_ratio_1m
            >= self.MIN_WATCH_ACTIVE_BUY_RATIO_1M
            and evidence.active_buy_ratio_5m
            >= self.MIN_WATCH_ACTIVE_BUY_RATIO_5M
            and one_minute.active_net >= self._minimum_active_net(one_minute, 0.35)
            and five_minutes.independent_buy_events
            >= self.MIN_WATCH_BUY_EVENTS_5M
            and evidence.capital_recovery_amount
            >= self._minimum_recovery_amount(five_minutes)
            and evidence.capital_recovery_ratio >= self.MIN_WATCH_RECOVERY_RATIO
        ):
            return None
        return evidence

    def confirmation_evidence(
        self,
        snapshot: FeatureSnapshot,
        state: StrategyState,
        universe: UniverseDecision,
    ) -> RecoveryEvidence | None:
        if state.metadata.get("watch_kind") != "post_invalidation_reversal":
            return None
        elapsed = (snapshot.computed_at - state.updated_at).total_seconds()
        if (
            elapsed < self.CONFIRM_MIN_AGE_SECONDS
            or elapsed > self.CONFIRM_MAX_AGE_SECONDS
            or not self._common_context(snapshot, universe)
        ):
            return None
        evidence = self._evidence(snapshot, state=state)
        one_minute = self._window(snapshot, 60)
        five_minutes = self._window(snapshot, 300)
        if evidence is None or one_minute is None or five_minutes is None:
            return None
        watch_price = self._number(state.metadata.get("watch_price"))
        funds_recovered = bool(
            snapshot.capital_memory is not None
            and (
                snapshot.capital_memory.day_main_net > 0
                or evidence.capital_recovery_ratio
                >= self.MIN_CONFIRM_RECOVERY_RATIO
            )
        )
        if not (
            evidence.rebound_from_low_pct <= self._confirm_rebound_cap(snapshot)
            and evidence.active_buy_ratio_1m
            >= self.MIN_CONFIRM_ACTIVE_BUY_RATIO_1M
            and evidence.active_buy_ratio_5m
            >= self.MIN_CONFIRM_ACTIVE_BUY_RATIO_5M
            and one_minute.active_net >= self._minimum_active_net(one_minute, 0.50)
            and five_minutes.active_net
            >= self._minimum_active_net(five_minutes, 1.0)
            and five_minutes.independent_buy_events
            >= self.MIN_CONFIRM_BUY_EVENTS_5M
            and funds_recovered
            and (watch_price is None or snapshot.quote.last_price >= watch_price)
        ):
            return None
        return evidence

    def _common_context(
        self,
        snapshot: FeatureSnapshot,
        universe: UniverseDecision,
    ) -> bool:
        hard_reasons = set(universe.reason_codes) - self.ALLOWED_UNIVERSE_REASONS
        context = snapshot.market_context
        position = snapshot.price_position
        acceptance = snapshot.price_acceptance
        extension_atr = (
            position.distance_to_ma20 / position.atr_percent
            if position.atr_percent > 0
            else None
        )
        max_vwap_extension = min(3.5, max(1.5, position.atr_percent * 0.50))
        return bool(
            not hard_reasons
            and snapshot.computed_at.timetz().replace(tzinfo=None) <= self.ENTRY_CUTOFF
            and snapshot.quality is not DataQuality.INVALID
            and snapshot.quote.quality is not DataQuality.INVALID
            and context.quality is not DataQuality.INVALID
            and context.market_sample_size >= 20
            and position.quality is not DataQuality.INVALID
            and position.daily_percentile <= 0.85
            and extension_atr is not None
            and extension_atr <= 2.5
            and snapshot.activity is not None
            and snapshot.activity.is_active
            and snapshot.liquidity is not None
            and snapshot.liquidity.quality is not DataQuality.INVALID
            and snapshot.liquidity.score >= 30
            and acceptance is not None
            and acceptance.quality is not DataQuality.INVALID
            and acceptance.accepted
            and (
                acceptance.distance_to_vwap_pct is None
                or -0.3 <= acceptance.distance_to_vwap_pct <= max_vwap_extension
            )
        )

    def _evidence(
        self,
        snapshot: FeatureSnapshot,
        *,
        state: StrategyState | None = None,
    ) -> RecoveryEvidence | None:
        one_minute = self._window(snapshot, 60)
        five_minutes = self._window(snapshot, 300)
        memory = snapshot.capital_memory
        if (
            one_minute is None
            or five_minutes is None
            or memory is None
            or one_minute.quality is DataQuality.INVALID
            or five_minutes.quality is DataQuality.INVALID
            or memory.quality is DataQuality.INVALID
        ):
            return None
        local_low = (
            self._number(state.metadata.get("local_low_price"))
            if state is not None
            else None
        ) or snapshot.quote.low_price
        if local_low <= 0 or snapshot.quote.last_price <= 0 or memory.day_trough >= 0:
            return None
        recovery_amount = memory.day_main_net - memory.day_trough
        recovery_ratio = recovery_amount / abs(memory.day_trough)
        return RecoveryEvidence(
            local_low_price=local_low,
            rebound_from_low_pct=(snapshot.quote.last_price / local_low - 1.0) * 100.0,
            active_buy_ratio_1m=one_minute.active_buy_ratio or 0.0,
            active_buy_ratio_5m=five_minutes.active_buy_ratio or 0.0,
            capital_recovery_amount=recovery_amount,
            capital_recovery_ratio=max(0.0, recovery_ratio),
        )

    @staticmethod
    def _window(snapshot: FeatureSnapshot, seconds: int) -> TickAggregate | None:
        return next(
            (window for window in snapshot.tick_windows if window.window_seconds == seconds),
            None,
        )

    @staticmethod
    def _minimum_active_net(window: TickAggregate, scale_multiple: float) -> float:
        threshold = window.large_order_threshold or 100_000.0
        scale = window.flow_scale or threshold
        return max(threshold, scale * scale_multiple)

    @staticmethod
    def _minimum_recovery_amount(window: TickAggregate) -> float:
        threshold = window.large_order_threshold or 100_000.0
        scale = window.flow_scale or threshold
        return max(2.0 * threshold, 0.5 * scale)

    @staticmethod
    def _watch_rebound_cap(snapshot: FeatureSnapshot) -> float:
        return min(8.0, max(5.0, snapshot.price_position.atr_percent * 1.25))

    @staticmethod
    def _confirm_rebound_cap(snapshot: FeatureSnapshot) -> float:
        return min(12.0, max(8.0, snapshot.price_position.atr_percent * 2.0))

    @staticmethod
    def _number(value: object) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None
