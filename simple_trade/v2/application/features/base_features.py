"""Pure calculators for activity, liquidity, price position, and breadth."""

from dataclasses import dataclass
from datetime import datetime
import statistics

from ...domain.enums import DataQuality, MarketRegime
from ...domain.features import (
    ActivityMetrics,
    BreadthMember,
    DailyBar,
    LiquidityMetrics,
    MarketContext,
    PricePosition,
)
from ...domain.market import OrderBookSnapshot, QuoteSnapshot
from .quality import clamp, worst_quality


@dataclass(frozen=True, slots=True)
class ActivityThresholds:
    min_volume: int
    min_turnover_rate: float
    min_turnover_amount: float


class ActivityFeature:
    """Preserve the legacy active-pool boundary while returning a 0-100 score."""

    _THRESHOLDS = {
        "HK": ActivityThresholds(500_000, 0.1, 1_000_000.0),
        "US": ActivityThresholds(3_000_000, 0.5, 5_000_000.0),
    }

    def calculate(self, quote: QuoteSnapshot) -> ActivityMetrics:
        market = "US" if quote.stock_code.startswith("US.") else "HK"
        thresholds = self._THRESHOLDS[market]
        reasons: list[str] = []
        rate = quote.turnover_rate
        rate_score = clamp((rate or 0.0) / 5.0 * 100.0)
        amount_score = clamp(quote.turnover / 50_000_000.0 * 100.0)
        legacy_score = round(rate_score * 0.6 + amount_score * 0.4, 4)

        if rate is None:
            reasons.append("TURNOVER_RATE_MISSING")
        if quote.volume <= 0:
            reasons.append("VOLUME_MISSING")
        if quote.turnover <= 0:
            reasons.append("TURNOVER_MISSING")

        quality = quote.quality
        if reasons and quality is DataQuality.GOOD:
            quality = DataQuality.DEGRADED
        is_active = bool(
            rate is not None
            and quote.volume >= thresholds.min_volume
            and rate >= thresholds.min_turnover_rate
            and quote.turnover >= thresholds.min_turnover_amount
        )
        return ActivityMetrics(
            as_of=quote.exchange_time,
            score=legacy_score,
            legacy_compatible_score=legacy_score,
            turnover_rate=rate,
            turnover_amount=quote.turnover,
            volume=quote.volume,
            is_active=is_active,
            quality=quality,
            reason_codes=tuple(reasons),
        )


class LiquidityFeature:
    """Score executable liquidity from spread, lot value, and turnover amount."""

    def calculate(
        self,
        quote: QuoteSnapshot,
        order_book: OrderBookSnapshot | None,
    ) -> LiquidityMetrics:
        reasons: list[str] = []
        components: list[tuple[float, float]] = []

        spread_pct: float | None = None
        if order_book and order_book.best_bid and order_book.best_ask:
            mid = (order_book.best_bid + order_book.best_ask) / 2.0
            spread_pct = max(0.0, (order_book.best_ask - order_book.best_bid) / mid * 100.0)
            spread_score = 100.0 if spread_pct <= 0.1 else clamp(
                (1.0 - spread_pct) / 0.9 * 100.0
            )
            components.append((spread_score, 0.40))
        else:
            reasons.append("ORDER_BOOK_SPREAD_MISSING")

        lot_value: float | None = None
        if quote.lot_size is not None and quote.last_price > 0:
            lot_value = quote.last_price * quote.lot_size
            if lot_value <= 50_000:
                lot_score = 100.0
            elif lot_value >= 500_000:
                lot_score = 0.0
            else:
                lot_score = (500_000.0 - lot_value) / 450_000.0 * 100.0
            components.append((lot_score, 0.20))
        else:
            reasons.append("LOT_SIZE_MISSING")

        minimum, excellent = (
            (5_000_000.0, 100_000_000.0)
            if quote.stock_code.startswith("US.")
            else (1_000_000.0, 50_000_000.0)
        )
        if quote.turnover < minimum:
            amount_score = 0.0
        else:
            amount_score = clamp(
                50.0 + (quote.turnover - minimum) / (excellent - minimum) * 50.0
            )
        components.append((amount_score, 0.40))
        if quote.turnover <= 0:
            reasons.append("TURNOVER_MISSING")

        available_weight = sum(weight for _, weight in components)
        score = (
            sum(value * weight for value, weight in components) / available_weight
            if available_weight
            else 0.0
        )
        score = round(clamp(score), 4)
        level = "A" if score >= 70 else "B" if score >= 50 else "C" if score >= 30 else "D"
        source_qualities = [quote.quality]
        if order_book is not None:
            source_qualities.append(order_book.quality)
        quality = worst_quality(*source_qualities)
        if reasons and quality is DataQuality.GOOD:
            quality = DataQuality.DEGRADED
        return LiquidityMetrics(
            as_of=quote.exchange_time,
            score=score,
            level=level,
            spread_pct=round(spread_pct, 6) if spread_pct is not None else None,
            lot_size=quote.lot_size,
            lot_value=round(lot_value, 4) if lot_value is not None else None,
            turnover_amount=quote.turnover,
            quality=quality,
            reason_codes=tuple(reasons),
        )


class PricePositionFeature:
    def __init__(self, lookback: int = 20, atr_period: int = 14) -> None:
        if lookback < 2 or atr_period < 2:
            raise ValueError("lookback and atr_period must be at least 2")
        self._lookback = lookback
        self._atr_period = atr_period

    def calculate(
        self,
        stock_code: str,
        as_of: datetime,
        current_price: float,
        bars: tuple[DailyBar, ...],
    ) -> PricePosition:
        valid = sorted(
            (
                bar
                for bar in bars
                if bar.stock_code == stock_code and bar.as_of <= as_of
            ),
            key=lambda bar: bar.as_of,
        )[-self._lookback :]
        if not valid or current_price <= 0:
            return PricePosition(
                as_of=as_of,
                daily_percentile=0.5,
                atr_percent=0.0,
                drawdown_from_high=0.0,
                distance_to_ma20=0.0,
                structure="UNKNOWN",
                quality=DataQuality.INVALID,
            )

        high = max(bar.high_price for bar in valid)
        low = min(bar.low_price for bar in valid)
        percentile = 0.5 if high <= low else clamp(
            (current_price - low) / (high - low), 0.0, 1.0
        )
        closes = [bar.close_price for bar in valid]
        ma = sum(closes) / len(closes)
        true_ranges: list[float] = []
        for index, bar in enumerate(valid):
            previous_close = valid[index - 1].close_price if index else bar.close_price
            true_ranges.append(
                max(
                    bar.high_price - bar.low_price,
                    abs(bar.high_price - previous_close),
                    abs(bar.low_price - previous_close),
                )
            )
        atr_values = true_ranges[-self._atr_period :]
        atr = sum(atr_values) / len(atr_values)
        structure = "LOW" if percentile <= 0.3 else "HIGH" if percentile >= 0.7 else "MID"
        quality = (
            DataQuality.GOOD
            if len(valid) >= self._lookback
            else DataQuality.DEGRADED
            if len(valid) >= 5
            else DataQuality.INVALID
        )
        return PricePosition(
            as_of=as_of,
            daily_percentile=round(percentile, 6),
            atr_percent=round(atr / current_price * 100.0, 6),
            drawdown_from_high=round((current_price / high - 1.0) * 100.0, 6),
            distance_to_ma20=round((current_price / ma - 1.0) * 100.0, 6),
            structure=structure,
            quality=quality,
        )


class BreadthFeature:
    def __init__(self, min_market_size: int = 20, min_sector_size: int = 5) -> None:
        if min_market_size <= 0 or min_sector_size <= 0:
            raise ValueError("breadth sample thresholds must be positive")
        self._min_market_size = min_market_size
        self._min_sector_size = min_sector_size
        self._relative_strength = RelativeStrengthFeature()

    def calculate(
        self,
        stock_code: str,
        sector_code: str | None,
        as_of: datetime,
        members: tuple[BreadthMember, ...],
    ) -> MarketContext:
        market = "US" if stock_code.startswith("US.") else "HK"
        market_rows = [
            member
            for member in members
            if member.eligible
            and ("US" if member.stock_code.startswith("US.") else "HK") == market
        ]
        market_breadth = (
            sum(member.change_pct > 0 for member in market_rows) / len(market_rows)
            if market_rows
            else 0.0
        )
        sector_rows = [
            member
            for member in market_rows
            if sector_code and member.sector_code == sector_code
        ]
        sector_breadth = (
            sum(member.change_pct > 0 for member in sector_rows) / len(sector_rows)
            if sector_rows
            else None
        )
        target = next((member for member in market_rows if member.stock_code == stock_code), None)
        relative_strength = None
        if target is not None and sector_rows:
            relative_strength = self._relative_strength.calculate(
                target.change_pct,
                tuple(member.change_pct for member in sector_rows),
            )
        turnover_rank = None
        if target is not None and market_rows:
            lower = sum(member.turnover < target.turnover for member in market_rows)
            equal = sum(member.turnover == target.turnover for member in market_rows)
            turnover_rank = (lower + equal * 0.5) / len(market_rows)
        regime = (
            MarketRegime.NORMAL
            if market_breadth >= 0.55
            else MarketRegime.WEAK
            if market_breadth >= 0.40
            else MarketRegime.EXTREME
        )

        if not market_rows or target is None:
            quality = DataQuality.INVALID
        elif len(market_rows) < self._min_market_size:
            quality = DataQuality.DEGRADED
        elif sector_code is None or len(sector_rows) < self._min_sector_size:
            quality = DataQuality.DEGRADED
        else:
            quality = DataQuality.GOOD
        return MarketContext(
            as_of=as_of,
            market_breadth=round(market_breadth, 6),
            market_sample_size=len(market_rows),
            sector_code=sector_code,
            sector_breadth=round(sector_breadth, 6) if sector_breadth is not None else None,
            sector_sample_size=len(sector_rows),
            relative_strength=(
                round(relative_strength, 6) if relative_strength is not None else None
            ),
            quality=quality,
            turnover_rank_percentile=(
                round(turnover_rank, 6) if turnover_rank is not None else None
            ),
            market_regime=regime,
        )


class RelativeStrengthFeature:
    """Return stock change minus the median change of its sector, in percentage points."""

    def calculate(
        self,
        stock_change_pct: float,
        sector_changes_pct: tuple[float, ...],
    ) -> float | None:
        if not sector_changes_pct:
            return None
        return stock_change_pct - statistics.median(sector_changes_pct)
