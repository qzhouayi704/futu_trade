"""Adaptive intraday exit rules validated by the recent tick holdout."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping

from ...domain.enums import CapitalMemoryState, DataQuality
from ...domain.features import FeatureSnapshot
from ...domain.market import TickAggregate
from ...domain.positions import PositionEfficiency, PositionState
from ...domain.serialization import JsonValue


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuralExitAssessment:
    exit_reason: str | None
    strong_outflow: bool
    fresh_support: bool
    weakening: bool
    active_sell_pressure: bool
    metadata_updates: Mapping[str, JsonValue]


class StructuralExitPolicy:
    HARD_STOP_PCT = -3.0
    TAKE_PROFIT_PCT = 5.0
    TRAIL_ACTIVATION_PCT = 3.0
    TRAIL_PULLBACK_PCT = -1.5
    PROFIT_FLOOR_PCT = 0.5
    VWAP_BREAK_MINUTES = 5
    SUPPORT_GRACE_MINUTES = 20
    OUTFLOW_EVENTS = 3
    OUTFLOW_SPAN_SECONDS = 300
    WEAKENING_VWAP_MINUTES = 5
    WEAKENING_SLOPE_PCT = -0.45
    WEAKENING_DRAWDOWN_PCT = -1.0
    DOWNTREND_EXIT_VWAP_MINUTES = 10
    DOWNTREND_EXIT_DRAWDOWN_PCT = -1.5
    DOWNTREND_EXIT_MAX_SCORE = 35.0
    ACTIVE_SELL_MULTIPLE = 1.5

    def assess(
        self,
        state: PositionState | None,
        efficiency: PositionEfficiency,
        feature: FeatureSnapshot | None,
    ) -> StructuralExitAssessment:
        metadata = {} if state is None or "COST_BASIS_CHANGED" in efficiency.reason_codes else state.metadata
        vwap_count, vwap_minute = self._vwap_break_state(metadata, feature)
        support_at = self._support_at(metadata, feature)
        as_of = efficiency.as_of
        fresh_support = bool(
            support_at is not None
            and timedelta(0) <= as_of - support_at <= timedelta(minutes=self.SUPPORT_GRACE_MINUTES)
        )
        strong_outflow = self._repeated_outflow(feature)
        active_sell_pressure = self._active_sell_pressure(feature)
        weakening = bool(
            active_sell_pressure
            and vwap_count >= self.WEAKENING_VWAP_MINUTES
            and efficiency.slope_15m_pct is not None
            and efficiency.slope_15m_pct <= self.WEAKENING_SLOPE_PCT
            and efficiency.drawdown_from_peak_pct <= self.WEAKENING_DRAWDOWN_PCT
            and efficiency.flow_current < 0
        )
        updates: dict[str, JsonValue] = {
            "exit_vwap_below_minutes": vwap_count,
            "exit_last_vwap_minute": vwap_minute,
            "exit_last_support_at": self._iso(support_at),
            "exit_repeated_outflow": strong_outflow,
            "exit_active_sell_pressure": active_sell_pressure,
            "exit_weakening": weakening,
        }

        reason = None
        if efficiency.current_return_pct <= self.HARD_STOP_PCT:
            reason = "HARD_STOP_3_PCT"
        elif efficiency.current_return_pct >= self.TAKE_PROFIT_PCT:
            reason = "TAKE_PROFIT_5_PCT"
        elif (
            strong_outflow
            and not fresh_support
            and (
                vwap_count >= self.VWAP_BREAK_MINUTES
                or efficiency.drawdown_from_peak_pct <= self.TRAIL_PULLBACK_PCT
            )
        ):
            reason = "REPEATED_OUTFLOW_AND_STRUCTURE_BREAK"
        elif (
            weakening
            and not fresh_support
            and vwap_count >= self.DOWNTREND_EXIT_VWAP_MINUTES
            and efficiency.drawdown_from_peak_pct <= self.DOWNTREND_EXIT_DRAWDOWN_PCT
            and efficiency.score <= self.DOWNTREND_EXIT_MAX_SCORE
        ):
            reason = "SUSTAINED_DOWNTREND_AND_VWAP_BREAK"
        elif (
            efficiency.mfe_pct >= self.TRAIL_ACTIVATION_PCT
            and efficiency.drawdown_from_peak_pct <= self.TRAIL_PULLBACK_PCT
            and not fresh_support
        ):
            reason = "TRAIL_AFTER_SUPPORT_LOST"
        elif (
            efficiency.mfe_pct >= self.TRAIL_ACTIVATION_PCT
            and efficiency.current_return_pct <= self.PROFIT_FLOOR_PCT
            and not fresh_support
        ):
            reason = "PROFIT_FLOOR_AFTER_SUPPORT_LOST"
        return StructuralExitAssessment(
            exit_reason=reason,
            strong_outflow=strong_outflow,
            fresh_support=fresh_support,
            weakening=weakening,
            active_sell_pressure=active_sell_pressure,
            metadata_updates=updates,
        )

    def _active_sell_pressure(self, feature: FeatureSnapshot | None) -> bool:
        if feature is None:
            return False
        window = next(
            (item for item in feature.tick_windows if item.window_seconds == 900),
            None,
        )
        if window is None or window.quality is DataQuality.INVALID:
            return False
        threshold = window.large_order_threshold or 100_000.0
        total = window.active_buy_amount + window.active_sell_amount
        return bool(
            total >= threshold * 2.0
            and window.active_sell_amount
            >= max(threshold, window.active_buy_amount * self.ACTIVE_SELL_MULTIPLE)
            and window.active_net <= -threshold
        )

    def _vwap_break_state(
        self,
        metadata: Mapping[str, JsonValue],
        feature: FeatureSnapshot | None,
    ) -> tuple[int, str | None]:
        previous_count = self._integer(metadata.get("exit_vwap_below_minutes"))
        previous_minute = self._datetime(metadata.get("exit_last_vwap_minute"))
        if feature is None or feature.price_acceptance is None:
            return previous_count, self._iso(previous_minute)
        distance = feature.price_acceptance.distance_to_vwap_pct
        current_minute = feature.computed_at.replace(second=0, microsecond=0)
        if distance is None:
            return previous_count, self._iso(previous_minute)
        if distance >= 0:
            return 0, self._iso(current_minute)
        if previous_minute == current_minute:
            return max(1, previous_count), self._iso(current_minute)
        consecutive = bool(
            previous_minute is not None
            and timedelta(0) < current_minute - previous_minute <= timedelta(seconds=90)
        )
        return (previous_count + 1 if consecutive else 1), self._iso(current_minute)

    def _support_at(
        self,
        metadata: Mapping[str, JsonValue],
        feature: FeatureSnapshot | None,
    ) -> datetime | None:
        prior = self._datetime(metadata.get("exit_last_support_at"))
        if feature is None:
            return prior
        window = next((item for item in feature.tick_windows if item.window_seconds == 900), None)
        if window is None or window.last_independent_buy_at is None:
            return prior
        threshold = window.large_order_threshold or 100_000.0
        net_supported = bool(
            window.main_net >= threshold
            and (window.buy_sell_ratio or 0.0) >= 0.60
            and window.independent_buy_events > 0
        )
        reclaimed_after_outflow = bool(
            window.last_independent_sell_at is not None
            and window.last_independent_buy_at > window.last_independent_sell_at
            and window.buy_amount >= threshold
        )
        supported = net_supported or reclaimed_after_outflow
        observed = window.last_independent_buy_at if supported else None
        return max(item for item in (prior, observed) if item is not None) if prior or observed else None

    def _repeated_outflow(self, feature: FeatureSnapshot | None) -> bool:
        if feature is None:
            return False
        recent = next(
            (item for item in feature.tick_windows if item.window_seconds == 900),
            None,
        )
        if recent is not None and self._window_has_repeated_outflow(recent):
            return True
        memory = feature.capital_memory
        distributing = bool(
            memory is not None
            and memory.quality is not DataQuality.INVALID
            and memory.state is CapitalMemoryState.DISTRIBUTING
            and memory.decayed_main_net < 0
            and memory.decayed_sell_events >= max(3.0, memory.decayed_buy_events * 1.5)
        )
        if not distributing:
            return False
        return any(
            self._window_has_repeated_outflow(window, threshold_multiple=2.0)
            for window in feature.tick_windows
            if window.window_seconds in {1800, 3600}
        )

    def _window_has_repeated_outflow(
        self,
        window: TickAggregate,
        *,
        threshold_multiple: float = 1.0,
    ) -> bool:
        if window.quality is DataQuality.INVALID:
            return False
        threshold = window.large_order_threshold or 100_000.0
        span = (
            (window.last_independent_sell_at - window.first_independent_sell_at).total_seconds()
            if window.first_independent_sell_at and window.last_independent_sell_at
            else 0.0
        )
        return bool(
            window.independent_sell_events >= self.OUTFLOW_EVENTS
            and span >= self.OUTFLOW_SPAN_SECONDS
            and window.main_net <= -(threshold * threshold_multiple)
            and window.sell_amount >= max(threshold, window.buy_amount * 1.2)
        )

    @staticmethod
    def _datetime(value: JsonValue | None) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _integer(value: JsonValue | None) -> int:
        return int(value) if isinstance(value, (int, float)) else 0

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None
