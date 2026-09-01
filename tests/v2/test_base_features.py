import unittest
from datetime import datetime, timedelta, timezone

from simple_trade.v2.application.features.base_features import (
    ActivityFeature,
    BreadthFeature,
    LiquidityFeature,
    PricePositionFeature,
    RelativeStrengthFeature,
)
from simple_trade.v2.application.features.price_acceptance import (
    PriceAcceptanceFeature,
    PriceTape,
)
from simple_trade.v2.domain.enums import DataQuality, TickDirection
from simple_trade.v2.domain.features import BreadthMember, DailyBar
from simple_trade.v2.domain.market import (
    OrderBookLevel,
    OrderBookSnapshot,
    QuoteSnapshot,
    TickTrade,
)


NOW = datetime(2026, 8, 31, 10, 0, tzinfo=timezone(timedelta(hours=8)))


def make_quote(**changes) -> QuoteSnapshot:
    values = {
        "stock_code": "HK.00100",
        "exchange_time": NOW,
        "last_price": 100.0,
        "prev_close": 95.0,
        "volume": 2_000_000,
        "turnover": 25_000_000.0,
        "turnover_rate": 2.5,
        "amplitude": 5.0,
        "lot_size": 100,
        "sector_code": "AI",
        "quality": DataQuality.GOOD,
    }
    values.update(changes)
    return QuoteSnapshot(**values)


class BaseFeatureTests(unittest.TestCase):
    def test_activity_matches_legacy_pool_score_and_boundary(self) -> None:
        metrics = ActivityFeature().calculate(make_quote())

        self.assertEqual(metrics.score, 50.0)
        self.assertEqual(metrics.legacy_compatible_score, 50.0)
        self.assertTrue(metrics.is_active)
        self.assertIs(metrics.quality, DataQuality.GOOD)

    def test_activity_missing_turnover_rate_is_explicitly_degraded(self) -> None:
        metrics = ActivityFeature().calculate(make_quote(turnover_rate=None))

        self.assertFalse(metrics.is_active)
        self.assertIs(metrics.quality, DataQuality.DEGRADED)
        self.assertIn("TURNOVER_RATE_MISSING", metrics.reason_codes)

    def test_liquidity_uses_spread_lot_value_and_turnover(self) -> None:
        quote = make_quote(turnover=50_000_000.0)
        book = OrderBookSnapshot(
            stock_code=quote.stock_code,
            exchange_time=NOW,
            bid_levels=(OrderBookLevel(price=99.96, volume=10_000),),
            ask_levels=(OrderBookLevel(price=100.04, volume=10_000),),
            quality=DataQuality.GOOD,
        )
        metrics = LiquidityFeature().calculate(quote, book)

        self.assertEqual(metrics.score, 100.0)
        self.assertEqual(metrics.level, "A")
        self.assertEqual(metrics.lot_value, 10_000.0)
        self.assertLess(metrics.spread_pct, 0.1)

    def test_liquidity_missing_book_and_lot_is_degraded(self) -> None:
        metrics = LiquidityFeature().calculate(make_quote(lot_size=None), None)

        self.assertIs(metrics.quality, DataQuality.DEGRADED)
        self.assertEqual(
            set(metrics.reason_codes),
            {"ORDER_BOOK_SPREAD_MISSING", "LOT_SIZE_MISSING"},
        )

    def test_price_position_has_low_mid_high_fixed_boundaries(self) -> None:
        bars = tuple(
            DailyBar(
                stock_code="HK.00100",
                as_of=NOW - timedelta(days=20 - index),
                open_price=20,
                high_price=30,
                low_price=10,
                close_price=20,
            )
            for index in range(20)
        )
        feature = PricePositionFeature()

        low = feature.calculate("HK.00100", NOW, 12, bars)
        mid = feature.calculate("HK.00100", NOW, 20, bars)
        high = feature.calculate("HK.00100", NOW, 28, bars)

        self.assertEqual((low.structure, mid.structure, high.structure), ("LOW", "MID", "HIGH"))
        self.assertTrue(all(item.quality is DataQuality.GOOD for item in (low, mid, high)))

    def test_market_and_sector_breadth_are_separate(self) -> None:
        members = tuple(
            BreadthMember(
                stock_code=f"HK.{index:05d}",
                change_pct=float(index - 10),
                turnover=1_000_000,
                sector_code="AI" if index < 5 else "OTHER",
            )
            for index in range(20)
        )
        context = BreadthFeature().calculate("HK.00004", "AI", NOW, members)

        self.assertEqual(context.market_breadth, 0.45)
        self.assertEqual(context.sector_breadth, 0.0)
        self.assertEqual(context.relative_strength, 2.0)
        self.assertIs(context.quality, DataQuality.GOOD)

    def test_relative_strength_is_stock_minus_sector_median(self) -> None:
        value = RelativeStrengthFeature().calculate(5.0, (1.0, 2.0, 3.0, 4.0, 5.0))

        self.assertEqual(value, 2.0)

    def test_price_acceptance_checks_confirmation_vwap_and_peak_drawdown(self) -> None:
        tape = PriceTape()
        tick = TickTrade(
            stock_code="HK.00100",
            exchange_time=NOW,
            price=100,
            volume=2_000,
            turnover=200_000,
            direction=TickDirection.BUY,
            sequence=1,
        )
        tape.on_tick(tick)
        tape.confirm(tick.stock_code, tick.price, tick.exchange_time)
        tape.observe_price(tick.stock_code, 102, NOW + timedelta(seconds=10))
        result = PriceAcceptanceFeature().calculate(
            as_of=NOW + timedelta(seconds=20),
            current_price=101.2,
            tape=tape.snapshot(tick.stock_code, NOW + timedelta(seconds=20)),
        )

        self.assertTrue(result.accepted)
        self.assertAlmostEqual(result.distance_to_vwap_pct, 1.2)
        self.assertGreaterEqual(result.drawdown_from_peak_pct, -1.0)


if __name__ == "__main__":
    unittest.main()
