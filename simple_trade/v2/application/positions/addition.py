"""Conservative one-step position addition confirmation."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

from ...domain.enums import CapitalMemoryState, DataQuality, PositionStatus
from ...domain.features import FeatureSnapshot
from ...domain.market import TickAggregate
from ...domain.positions import PositionEfficiency, PositionSnapshot, PositionState
from ...domain.serialization import JsonValue


HK_TIMEZONE = timezone(timedelta(hours=8))


@dataclass(frozen=True, slots=True)
class PositionAddAssessment:
    confirmed: bool
    metadata_updates: Mapping[str, JsonValue]


class PositionAddPolicy:
    """Only add to a profitable, accepted position with fresh capital support."""

    MIN_HELD_MINUTES = 15.0
    MIN_RETURN_PCT = 0.5
    MAX_RETURN_PCT = 2.5
    MAX_PEAK_DRAWDOWN_PCT = -0.8
    MIN_SLOPE_15M_PCT = 0.15
    MIN_EFFICIENCY_SCORE = 65.0
    MIN_MEMORY_SCORE = 75.0
    MIN_MARKET_BREADTH = 0.50
    MIN_SECTOR_BREADTH = 0.50
    MAX_VWAP_DISTANCE_PCT = 1.20
    ADD_RATIO = 0.10
    TARGET_RATIO = 0.25

    def assess(
        self,
        position: PositionSnapshot,
        state: PositionState | None,
        efficiency: PositionEfficiency,
        feature: FeatureSnapshot | None,
    ) -> PositionAddAssessment:
        if state is None or state.status is not PositionStatus.HOLDING:
            return self._rejected()
        if self._prompt_count(state) >= 1:
            return self._rejected()
        held_minutes = self._trading_minutes_between(state.opened_at, position.as_of)
        if held_minutes < self.MIN_HELD_MINUTES:
            return self._rejected()
        if not (
            self.MIN_RETURN_PCT
            <= efficiency.current_return_pct
            <= self.MAX_RETURN_PCT
        ):
            return self._rejected()
        if efficiency.drawdown_from_peak_pct < self.MAX_PEAK_DRAWDOWN_PCT:
            return self._rejected()
        if (
            efficiency.slope_15m_pct is None
            or efficiency.slope_15m_pct < self.MIN_SLOPE_15M_PCT
        ):
            return self._rejected()
        if efficiency.score < self.MIN_EFFICIENCY_SCORE or efficiency.stalled:
            return self._rejected()
        if feature is None or feature.quality is DataQuality.INVALID:
            return self._rejected()

        acceptance = feature.price_acceptance
        if (
            acceptance is None
            or acceptance.quality is DataQuality.INVALID
            or not acceptance.accepted
            or acceptance.distance_to_vwap_pct is None
            or not 0 <= acceptance.distance_to_vwap_pct <= self.MAX_VWAP_DISTANCE_PCT
        ):
            return self._rejected()

        context = feature.market_context
        if (
            context.quality is DataQuality.INVALID
            or context.market_breadth < self.MIN_MARKET_BREADTH
        ):
            return self._rejected()
        if (
            context.sector_sample_size >= 3
            and (
                context.sector_breadth is None
                or context.sector_breadth < self.MIN_SECTOR_BREADTH
            )
        ):
            return self._rejected()

        memory = feature.capital_memory
        if (
            memory is None
            or memory.quality is DataQuality.INVALID
            or memory.state is not CapitalMemoryState.ACCUMULATING
            or memory.score < self.MIN_MEMORY_SCORE
            or memory.day_main_net <= 0
            or memory.decayed_main_net <= 0
            or memory.recent_15m_main_net <= 0
        ):
            return self._rejected()

        window_15m = self._window(feature, 900)
        window_5m = self._window(feature, 300)
        if window_15m is None or window_5m is None:
            return self._rejected()
        if (
            window_15m.large_order_threshold is None
            or window_15m.flow_scale is None
            or window_5m.sample_count <= 0
        ):
            return self._rejected()
        flow_floor = max(
            (window_15m.large_order_threshold or 0.0) * 3.0,
            (window_15m.flow_scale or 0.0) * 1.25,
        )
        if (
            window_15m.quality is DataQuality.INVALID
            or window_15m.independent_buy_events < 3
            or window_15m.independent_buy_span_seconds < 600
            or window_15m.main_net < flow_floor
            or window_15m.buy_sell_ratio is None
            or window_15m.buy_sell_ratio < 0.70
            or window_15m.active_buy_ratio is None
            or window_15m.active_buy_ratio < 0.55
        ):
            return self._rejected()

        if (
            window_5m.quality is DataQuality.INVALID
            or window_5m.main_net < 0
            or window_5m.independent_sell_events > window_5m.independent_buy_events
            or (
                window_5m.active_buy_ratio is not None
                and window_5m.active_buy_ratio < 0.48
            )
        ):
            return self._rejected()

        return PositionAddAssessment(
            confirmed=True,
            metadata_updates={
                "add_prompt_count": 1,
                "last_add_prompt_at": position.as_of.isoformat(),
                "suggested_add_ratio": self.ADD_RATIO,
                "suggested_target_ratio": self.TARGET_RATIO,
                "add_reference_price": position.current_price,
            },
        )

    @staticmethod
    def _window(feature: FeatureSnapshot, seconds: int) -> TickAggregate | None:
        return next(
            (item for item in feature.tick_windows if item.window_seconds == seconds),
            None,
        )

    @staticmethod
    def _rejected() -> PositionAddAssessment:
        return PositionAddAssessment(confirmed=False, metadata_updates={})

    @staticmethod
    def _prompt_count(state: PositionState) -> int:
        try:
            return max(0, int(state.metadata.get("add_prompt_count", 0) or 0))
        except (TypeError, ValueError, OverflowError):
            return 1

    @staticmethod
    def _trading_minutes_between(start: datetime, end: datetime) -> float:
        start = start.astimezone(HK_TIMEZONE)
        end = end.astimezone(HK_TIMEZONE)
        if end <= start:
            return 0.0
        if start.date() != end.date():
            start = end.replace(hour=9, minute=30, second=0, microsecond=0)
        seconds = 0.0
        for start_hour, start_minute, end_hour, end_minute in (
            (9, 30, 12, 0),
            (13, 0, 16, 0),
        ):
            session_start = end.replace(
                hour=start_hour, minute=start_minute, second=0, microsecond=0
            )
            session_end = end.replace(
                hour=end_hour, minute=end_minute, second=0, microsecond=0
            )
            overlap_start = max(start, session_start)
            overlap_end = min(end, session_end)
            if overlap_end > overlap_start:
                seconds += (overlap_end - overlap_start).total_seconds()
        return seconds / 60.0
