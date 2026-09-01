"""Hot and executable universe gate; it never creates a trade action."""

from ...domain.enums import DataQuality, MarketRegime
from ...domain.features import FeatureSnapshot
from .models import UniverseDecision


class UniversePolicy:
    def evaluate(self, snapshot: FeatureSnapshot) -> UniverseDecision:
        reasons: list[str] = []
        context = snapshot.market_context
        activity = snapshot.activity
        liquidity = snapshot.liquidity

        if snapshot.quality is DataQuality.INVALID:
            reasons.append("SNAPSHOT_INVALID")
        if activity is None or not activity.is_active:
            reasons.append("NOT_ACTIVE")
        if liquidity is None or liquidity.score < 30:
            reasons.append("LIQUIDITY_TOO_LOW")
        if context.quality is not DataQuality.GOOD:
            reasons.append("MARKET_CONTEXT_INCOMPLETE")

        rank_min = 0.90 if context.market_regime is MarketRegime.EXTREME else 0.80
        if (
            context.turnover_rank_percentile is None
            or context.turnover_rank_percentile < rank_min
        ):
            reasons.append("TURNOVER_RANK_NOT_HOT")

        sector_min = {
            MarketRegime.NORMAL: 0.55,
            MarketRegime.WEAK: 0.50,
            MarketRegime.EXTREME: 0.70,
        }[context.market_regime]
        if context.sector_breadth is None or context.sector_breadth < sector_min:
            reasons.append("SECTOR_BREADTH_WEAK")

        strength_min = 0.0 if context.market_regime is MarketRegime.NORMAL else 2.5
        if context.relative_strength is None or context.relative_strength < strength_min:
            reasons.append("RELATIVE_STRENGTH_LOW")
        return UniverseDecision(eligible=not reasons, reason_codes=tuple(reasons))
