import unittest
from datetime import datetime, timezone

from simple_trade.v2.application.features.legacy_comparison import (
    LegacyFeatureComparator,
    LegacyRawFeatures,
)
from simple_trade.v2.domain.enums import DataQuality
from simple_trade.v2.domain.features import (
    FeatureSnapshot,
    MarketContext,
    PriceAcceptance,
    PricePosition,
)
from simple_trade.v2.domain.market import QuoteSnapshot, TickAggregate


NOW = datetime(2026, 8, 31, 2, 0, tzinfo=timezone.utc)


def make_window(seconds: int) -> TickAggregate:
    return TickAggregate(
        stock_code="HK.00100",
        as_of=NOW,
        window_seconds=seconds,
        buy_amount=800_000,
        sell_amount=200_000,
        main_net=600_000,
        big_buy_count=4,
        big_sell_count=1,
        independent_buy_events=2,
        independent_sell_events=1,
        buy_sell_ratio=0.8,
        cumulative_main_net=2_000_000,
        cumulative_peak=2_500_000,
        cumulative_trough=0,
        last_sequence=10,
        sample_count=5,
        quality=DataQuality.GOOD,
    )


class LegacyComparisonTests(unittest.TestCase):
    def test_report_explains_each_population_difference(self) -> None:
        quote = QuoteSnapshot(
            stock_code="HK.00100",
            exchange_time=NOW,
            last_price=101,
            prev_close=100,
        )
        acceptance = PriceAcceptance(
            as_of=NOW,
            score=80,
            confirmation_price=100,
            current_price=101,
            vwap=100.5,
            return_from_confirmation_pct=1,
            distance_to_vwap_pct=0.4975,
            drawdown_from_peak_pct=-0.5,
            accepted=True,
            quality=DataQuality.GOOD,
        )
        snapshot = FeatureSnapshot(
            stock_code="HK.00100",
            computed_at=NOW,
            quote=quote,
            tick_windows=(make_window(300), make_window(3600)),
            market_context=MarketContext(
                as_of=NOW,
                market_breadth=0.6,
                market_sample_size=20,
                sector_code="AI",
                sector_breadth=0.8,
                sector_sample_size=5,
                relative_strength=2,
                quality=DataQuality.GOOD,
            ),
            price_position=PricePosition(
                as_of=NOW,
                daily_percentile=0.4,
                atr_percent=3,
                drawdown_from_high=-2,
                distance_to_ma20=1,
                structure="MID",
                quality=DataQuality.GOOD,
            ),
            activity_score=50,
            liquidity_score=70,
            price_acceptance_score=80,
            price_acceptance=acceptance,
            quality=DataQuality.GOOD,
        )
        legacy = LegacyRawFeatures(
            stock_code="HK.00100",
            as_of=NOW,
            high_turnover_activity_score=0.5,
            momentum_buy_ratio=0.75,
            momentum_vwap=100.4,
            sniper_cumulative_net=1_800_000,
            sniper_mega_buy_count=4,
        )

        report = LegacyFeatureComparator().compare(legacy, snapshot)
        markdown = report.to_markdown()

        self.assertEqual(len(report.differences), 5)
        self.assertEqual(report.differences[0].absolute_difference, 0)
        self.assertIn("ALL_TICKS_VS_BIG_ORDER_WINDOW", markdown)
        self.assertIn("RAW_TRIGGER_COUNT_VS_SPLIT_ORDER_GROUPING", markdown)


if __name__ == "__main__":
    unittest.main()
