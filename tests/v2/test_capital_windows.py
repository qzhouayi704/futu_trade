import unittest
from datetime import datetime, timedelta, timezone

from simple_trade.v2.application.features.capital_windows import CapitalWindowEngine
from simple_trade.v2.domain.enums import DataQuality, TickDirection
from simple_trade.v2.domain.features import CapitalBaseline
from simple_trade.v2.domain.market import TickAggregate, TickTrade


NOW = datetime(2026, 8, 31, 10, 0, tzinfo=timezone(timedelta(hours=8)))


def tick(
    seconds: int,
    *,
    amount: float = 200_000,
    direction: TickDirection = TickDirection.BUY,
    sequence: int | None = None,
    price: float = 100.0,
) -> TickTrade:
    volume = max(1, int(amount / price))
    return TickTrade(
        stock_code="HK.00100",
        exchange_time=NOW + timedelta(seconds=seconds),
        price=price,
        volume=volume,
        turnover=amount,
        direction=direction,
        sequence=sequence,
    )


class CapitalWindowTests(unittest.TestCase):
    def test_per_stock_baseline_controls_threshold_and_event_span(self) -> None:
        engine = CapitalWindowEngine()
        engine.set_baselines((CapitalBaseline(
            stock_code="HK.00100",
            large_order_threshold=300_000,
            flow_scale=900_000,
            quality=DataQuality.GOOD,
        ),))
        engine.on_tick(tick(0, amount=200_000, sequence=1))
        engine.on_tick(tick(10, amount=400_000, sequence=2))
        engine.on_tick(tick(320, amount=500_000, sequence=3, price=101))

        window = next(
            item for item in engine.snapshots("HK.00100", NOW + timedelta(seconds=321))
            if item.window_seconds == 900
        )
        self.assertEqual(window.sample_count, 2)
        self.assertEqual(window.large_order_threshold, 300_000)
        self.assertEqual(window.flow_scale, 900_000)
        self.assertEqual(window.independent_buy_events, 2)
        self.assertEqual(window.independent_buy_span_seconds, 310)

    def test_one_five_fifteen_thirty_sixty_minute_boundaries(self) -> None:
        engine = CapitalWindowEngine()
        engine.on_tick(tick(0, sequence=1))

        at_boundary = engine.snapshots("HK.00100", NOW + timedelta(seconds=60))
        after_boundary = engine.snapshots("HK.00100", NOW + timedelta(seconds=61))

        self.assertEqual(tuple(item.window_seconds for item in at_boundary), (60, 300, 900, 1800, 3600))
        self.assertEqual(at_boundary[0].sample_count, 1)
        self.assertEqual(after_boundary[0].sample_count, 0)
        self.assertEqual(after_boundary[1].sample_count, 1)

    def test_split_orders_keep_amount_but_count_one_independent_event(self) -> None:
        engine = CapitalWindowEngine()
        for index, price in enumerate((100.0, 100.05, 100.10), start=1):
            engine.on_tick(tick(index - 1, sequence=index, price=price))

        window = engine.snapshots("HK.00100", NOW + timedelta(seconds=3))[0]

        self.assertEqual(window.big_buy_count, 3)
        self.assertEqual(window.independent_buy_events, 1)
        self.assertEqual(window.buy_amount, 600_000)

    def test_inflow_and_outflow_offset_net_count_and_direction(self) -> None:
        engine = CapitalWindowEngine()
        engine.on_tick(tick(0, amount=500_000, sequence=1))
        engine.on_tick(
            tick(10, amount=300_000, direction=TickDirection.SELL, sequence=2)
        )
        window = engine.snapshots("HK.00100", NOW + timedelta(seconds=11))[0]

        self.assertEqual(window.main_net, 200_000)
        self.assertEqual(window.independent_buy_events, 1)
        self.assertEqual(window.independent_sell_events, 1)
        self.assertIs(window.net_direction, TickDirection.BUY)
        self.assertEqual(window.buy_sell_ratio, 0.625)

    def test_business_duplicate_is_rejected_even_without_adapter(self) -> None:
        engine = CapitalWindowEngine()
        source = tick(0, sequence=None)

        self.assertTrue(engine.on_tick(source).accepted)
        self.assertFalse(engine.on_tick(source).accepted)
        self.assertEqual(
            engine.snapshots("HK.00100", NOW + timedelta(seconds=1))[0].sample_count,
            1,
        )

    def test_seed_preserves_cumulative_values_but_marks_window_quality(self) -> None:
        engine = CapitalWindowEngine()
        engine.seed(
            TickAggregate(
                stock_code="HK.00100",
                as_of=NOW,
                window_seconds=600,
                buy_amount=0,
                sell_amount=0,
                main_net=0,
                big_buy_count=4,
                big_sell_count=1,
                independent_buy_events=4,
                independent_sell_events=1,
                buy_sell_ratio=0.8,
                cumulative_main_net=2_000_000,
                cumulative_peak=3_000_000,
                cumulative_trough=-100_000,
                last_sequence=20,
                sample_count=5,
                quality=DataQuality.DEGRADED,
            )
        )
        engine.on_tick(tick(5, amount=500_000, sequence=21))
        window = engine.snapshots("HK.00100", NOW + timedelta(seconds=6))[0]

        self.assertEqual(window.cumulative_main_net, 2_500_000)
        self.assertEqual(window.cumulative_peak, 3_000_000)
        self.assertIs(window.quality, DataQuality.DEGRADED)


if __name__ == "__main__":
    unittest.main()
