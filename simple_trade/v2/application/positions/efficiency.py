"""Position MFE/MAE, price stagnation, and capital-decay calculator."""

from datetime import datetime, timedelta, timezone

from ...domain.enums import DataQuality
from ...domain.features import FeatureSnapshot
from ...domain.positions import PositionEfficiency, PositionSnapshot, PositionState
from ..features.quality import clamp, worst_quality


PricePoint = tuple[datetime, float]
HK_TIMEZONE = timezone(timedelta(hours=8))


class PositionEfficiencyEngine:
    def calculate(
        self,
        position: PositionSnapshot,
        state: PositionState | None,
        feature: FeatureSnapshot | None,
        prices: tuple[PricePoint, ...],
    ) -> PositionEfficiency:
        basis_changed = bool(
            state is not None
            and state.cost_price > 0
            and position.cost_price > 0
            and abs(position.cost_price / state.cost_price - 1.0) > 0.005
        )
        analytics_state = None if basis_changed else state
        current_return = position.current_return_pct
        prior_peak = analytics_state.peak_price if analytics_state is not None else position.current_price
        prior_trough = analytics_state.trough_price if analytics_state is not None else position.current_price
        peak_price = max(prior_peak, position.current_price)
        trough_price = min(prior_trough, position.current_price)
        mfe = max(
            analytics_state.mfe_pct if analytics_state is not None else current_return,
            self._return(position.cost_price, peak_price),
        )
        mae = min(
            analytics_state.mae_pct if analytics_state is not None else current_return,
            self._return(position.cost_price, trough_price),
        )
        drawdown = self._return(peak_price, position.current_price)

        flow_current = 0.0
        flow_threshold = 1.0
        feature_quality = DataQuality.INVALID
        if feature is not None:
            risk_windows = tuple(
                item for item in feature.tick_windows
                if item.window_seconds in {900, 1800, 3600}
                and item.quality is not DataQuality.INVALID
            )
            flow_values = [item.main_net for item in risk_windows]
            if (
                feature.capital_memory is not None
                and feature.capital_memory.quality is not DataQuality.INVALID
            ):
                flow_values.append(feature.capital_memory.decayed_main_net)
            if flow_values:
                flow_current = min(flow_values)
            if risk_windows:
                flow_threshold = max(
                    item.large_order_threshold or 1.0 for item in risk_windows
                )
                feature_quality = worst_quality(
                    *(item.quality for item in risk_windows)
                )
        prior_flow_peak = analytics_state.flow_peak if analytics_state is not None else flow_current
        memory_peak = (
            feature.capital_memory.day_peak
            if feature is not None and feature.capital_memory is not None
            else 0.0
        )
        flow_peak = max(prior_flow_peak, memory_peak, flow_current, 0.0)
        flow_drawdown = clamp(
            (flow_peak - flow_current) / max(flow_peak, flow_threshold),
            0.0,
            1.0,
        )

        slope15 = self._slope(prices, position.as_of, 15)
        slope30 = self._slope(prices, position.as_of, 30)
        slope60 = self._slope(prices, position.as_of, 60)
        range15 = self._range(prices, position.as_of, 15)
        last_high = (
            position.as_of
            if analytics_state is None or position.current_price > analytics_state.peak_price
            else analytics_state.last_high_at
        )
        minutes_since_high = self._trading_minutes_between(last_high, position.as_of)
        held_minutes = (
            self._trading_minutes_between(analytics_state.opened_at, position.as_of)
            if analytics_state is not None
            else 0.0
        )
        stalled = bool(
            held_minutes >= 30
            and minutes_since_high >= 20
            and slope15 is not None
            and abs(slope15) <= 0.30
            and range15 is not None
            and range15 <= 0.80
            and flow_current <= flow_peak
        )

        return_score = clamp(50.0 + current_return * 8.0)
        retention = (
            clamp(max(0.0, current_return) / mfe * 100.0)
            if mfe > 0
            else 50.0 if current_return >= 0 else 20.0
        )
        trend_score = clamp(50.0 + (slope15 or 0.0) * 60.0)
        flow_score = clamp(100.0 * (1.0 - flow_drawdown))
        score = round(
            return_score * 0.30
            + retention * 0.25
            + trend_score * 0.25
            + flow_score * 0.20,
            4,
        )
        reasons: list[str] = []
        if slope15 is None or range15 is None:
            reasons.append("PRICE_HISTORY_INSUFFICIENT")
        if feature is None:
            reasons.append("FEATURE_SNAPSHOT_MISSING")
        if basis_changed:
            reasons.append("COST_BASIS_CHANGED")
        if stalled:
            reasons.append("SUSTAINED_PRICE_STALL")
        quality = worst_quality(position.quality, feature_quality)
        if reasons and quality is DataQuality.GOOD:
            quality = DataQuality.DEGRADED
        return PositionEfficiency(
            stock_code=position.stock_code,
            as_of=position.as_of,
            current_return_pct=round(current_return, 6),
            mfe_pct=round(mfe, 6),
            mae_pct=round(mae, 6),
            drawdown_from_peak_pct=round(drawdown, 6),
            flow_peak=round(flow_peak, 4),
            flow_current=round(flow_current, 4),
            flow_drawdown_ratio=round(flow_drawdown, 6),
            slope_15m_pct=slope15,
            slope_30m_pct=slope30,
            slope_60m_pct=slope60,
            range_15m_pct=range15,
            minutes_since_high=round(minutes_since_high, 4),
            score=score,
            stalled=stalled,
            quality=quality,
            reason_codes=tuple(reasons),
        )

    @staticmethod
    def _return(base: float, current: float) -> float:
        return (current / base - 1.0) * 100.0 if base > 0 and current > 0 else 0.0

    @staticmethod
    def _selected(
        prices: tuple[PricePoint, ...],
        as_of: datetime,
        minutes: int,
    ) -> tuple[PricePoint, ...]:
        cutoff = as_of - timedelta(minutes=minutes)
        return tuple(point for point in prices if cutoff <= point[0] <= as_of)

    def _slope(
        self,
        prices: tuple[PricePoint, ...],
        as_of: datetime,
        minutes: int,
    ) -> float | None:
        selected = self._selected(prices, as_of, minutes)
        if len(selected) < 2 or selected[0][1] <= 0:
            return None
        return round((selected[-1][1] / selected[0][1] - 1.0) * 100.0, 6)

    def _range(
        self,
        prices: tuple[PricePoint, ...],
        as_of: datetime,
        minutes: int,
    ) -> float | None:
        selected = self._selected(prices, as_of, minutes)
        if len(selected) < 2:
            return None
        values = [point[1] for point in selected if point[1] > 0]
        if len(values) < 2:
            return None
        return round((max(values) / min(values) - 1.0) * 100.0, 6)

    @staticmethod
    def _trading_minutes_between(start: datetime, end: datetime) -> float:
        start = start.astimezone(HK_TIMEZONE)
        end = end.astimezone(HK_TIMEZONE)
        if end <= start:
            return 0.0
        if start.date() != end.date():
            start = end.replace(hour=9, minute=30, second=0, microsecond=0)
        sessions = ((9, 30, 12, 0), (13, 0, 16, 0))
        seconds = 0.0
        for start_hour, start_minute, end_hour, end_minute in sessions:
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
