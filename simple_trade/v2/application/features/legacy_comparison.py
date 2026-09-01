"""Explainable comparison between legacy feature outputs and one V2 snapshot."""

from dataclasses import dataclass
from datetime import datetime

from ...domain.features import FeatureSnapshot


@dataclass(frozen=True, slots=True, kw_only=True)
class LegacyRawFeatures:
    stock_code: str
    as_of: datetime
    high_turnover_activity_score: float | None = None
    momentum_buy_ratio: float | None = None
    momentum_vwap: float | None = None
    sniper_cumulative_net: float | None = None
    sniper_mega_buy_count: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureDifference:
    metric: str
    legacy_value: float | None
    v2_value: float | None
    absolute_difference: float | None
    reason_code: str


@dataclass(frozen=True, slots=True, kw_only=True)
class LegacyComparisonReport:
    stock_code: str
    as_of: datetime
    differences: tuple[FeatureDifference, ...]

    def to_markdown(self) -> str:
        lines = [
            f"# Feature comparison: {self.stock_code}",
            "",
            "| Metric | Legacy | V2 | Difference | Reason |",
            "|---|---:|---:|---:|---|",
        ]
        for item in self.differences:
            legacy = "n/a" if item.legacy_value is None else f"{item.legacy_value:.4f}"
            v2 = "n/a" if item.v2_value is None else f"{item.v2_value:.4f}"
            difference = (
                "n/a"
                if item.absolute_difference is None
                else f"{item.absolute_difference:.4f}"
            )
            lines.append(
                f"| {item.metric} | {legacy} | {v2} | {difference} | {item.reason_code} |"
            )
        return "\n".join(lines) + "\n"


class LegacyFeatureComparator:
    def compare(
        self,
        legacy: LegacyRawFeatures,
        snapshot: FeatureSnapshot,
    ) -> LegacyComparisonReport:
        if legacy.stock_code.strip().upper() != snapshot.stock_code:
            raise ValueError("legacy and V2 stock codes must match")
        five_minute = next(
            (window for window in snapshot.tick_windows if window.window_seconds == 300),
            None,
        )
        longest = max(snapshot.tick_windows, key=lambda window: window.window_seconds, default=None)
        legacy_activity = legacy.high_turnover_activity_score
        if legacy_activity is not None and 0 <= legacy_activity <= 1:
            legacy_activity *= 100.0
        values = (
            (
                "activity_score",
                legacy_activity,
                snapshot.activity_score,
                "SCALE_NORMALIZED_0_1_TO_0_100",
            ),
            (
                "buy_ratio",
                legacy.momentum_buy_ratio,
                five_minute.buy_sell_ratio if five_minute else None,
                "ALL_TICKS_VS_BIG_ORDER_WINDOW",
            ),
            (
                "vwap",
                legacy.momentum_vwap,
                snapshot.price_acceptance.vwap if snapshot.price_acceptance else None,
                "MINUTE_BAR_VWAP_VS_INCREMENTAL_TICK_VWAP",
            ),
            (
                "cumulative_main_net",
                legacy.sniper_cumulative_net,
                longest.cumulative_main_net if longest else None,
                "MINUTE_DB_AGGREGATE_VS_DEDUPED_TICK_STREAM",
            ),
            (
                "independent_buy_events",
                float(legacy.sniper_mega_buy_count)
                if legacy.sniper_mega_buy_count is not None
                else None,
                float(longest.independent_buy_events) if longest else None,
                "RAW_TRIGGER_COUNT_VS_SPLIT_ORDER_GROUPING",
            ),
        )
        differences = tuple(
            FeatureDifference(
                metric=metric,
                legacy_value=legacy_value,
                v2_value=v2_value,
                absolute_difference=(
                    abs(legacy_value - v2_value)
                    if legacy_value is not None and v2_value is not None
                    else None
                ),
                reason_code=reason,
            )
            for metric, legacy_value, v2_value, reason in values
        )
        return LegacyComparisonReport(
            stock_code=snapshot.stock_code,
            as_of=snapshot.computed_at,
            differences=differences,
        )
