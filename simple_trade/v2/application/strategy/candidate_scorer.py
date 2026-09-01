"""Explainable ranking score. Scores never produce state transitions."""

from ...domain.enums import DataQuality
from ...domain.features import FeatureSnapshot
from ..features.quality import clamp, worst_quality
from .models import CandidateScore


class CandidateScorer:
    def score(self, snapshot: FeatureSnapshot) -> CandidateScore:
        window = self._window(snapshot, 900) or self._window(snapshot, 3600)
        reasons: list[str] = []
        if window is None:
            flow_score = 0.0
            reasons.append("CAPITAL_WINDOW_MISSING")
        else:
            scale = max(window.flow_scale or 0.0, window.large_order_threshold or 1.0)
            normalized_net = max(0.0, window.main_net) / scale
            amount = clamp(normalized_net / 4.0 * 100.0)
            events = clamp(window.independent_buy_events / 3.0 * 100.0)
            ratio = clamp(((window.buy_sell_ratio or 0.0) - 0.5) / 0.35 * 100.0)
            flow_score = amount * 0.45 + events * 0.30 + ratio * 0.25

        strength = snapshot.market_context.relative_strength
        strength_score = clamp(((strength or 0.0) + 1.0) / 6.0 * 100.0)
        percentile = snapshot.price_position.daily_percentile
        daily_score = (
            90.0 if percentile <= 0.30 else
            80.0 if percentile <= 0.65 else
            55.0 if percentile <= 0.85 else 30.0
        )
        activity = snapshot.activity_score
        liquidity = snapshot.liquidity_score
        acceptance = snapshot.price_acceptance_score
        total = round(
            activity * 0.20
            + liquidity * 0.15
            + flow_score * 0.30
            + acceptance * 0.20
            + strength_score * 0.10
            + daily_score * 0.05,
            4,
        )
        quality = worst_quality(
            snapshot.quality,
            window.quality if window is not None else DataQuality.INVALID,
        )
        return CandidateScore(
            total=total,
            activity=round(activity, 4),
            liquidity=round(liquidity, 4),
            capital_flow=round(flow_score, 4),
            price_acceptance=round(acceptance, 4),
            relative_strength=round(strength_score, 4),
            daily_position=daily_score,
            quality=quality,
            reason_codes=tuple(reasons) or ("RANKING_ONLY",),
        )

    @staticmethod
    def _window(snapshot: FeatureSnapshot, seconds: int):
        return next(
            (window for window in snapshot.tick_windows if window.window_seconds == seconds),
            None,
        )
