import unittest
from datetime import datetime, timezone

from simple_trade.v2.application.event_bus import EventBus
from simple_trade.v2.application.market_projector import MarketProjector
from simple_trade.v2.domain.enums import DataQuality
from simple_trade.v2.domain.market import TickAggregate
from simple_trade.v2.infrastructure.futu_market_adapter import FutuMarketAdapter


NOW = datetime(2026, 8, 31, 2, 0, tzinfo=timezone.utc)


class MarketProjectorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bus = EventBus(capacity=32)
        self.projector = MarketProjector()
        self.projector.register(self.bus)
        self.adapter = FutuMarketAdapter(strategy_version="test-v2")
        await self.bus.start()

    async def asyncTearDown(self) -> None:
        await self.bus.stop()
        self.projector.unregister()

    async def test_same_stock_snapshot_is_replaced_atomically(self) -> None:
        quote_events = self.adapter.adapt_quote(
            {
                "code": "HK.00100",
                "last_price": 356.6,
                "prev_close": 300.4,
                "data_date": "2026-08-31",
                "data_time": "10:00:00",
            },
            received_time=NOW,
        )
        tick_events = self.adapter.adapt_ticker(
            {
                "code": "HK.00100",
                "time": "2026-08-31 10:00:01",
                "price": 356.8,
                "volume": 100,
                "ticker_direction": "BUY",
                "sequence": 1,
            },
            received_time=NOW,
        )
        for event in (*quote_events, *tick_events):
            self.assertTrue(await self.bus.publish(event))
        await self.bus.join()

        snapshot = self.projector.get("HK.00100")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.quote.last_price, 356.6)
        self.assertEqual(snapshot.last_tick.price, 356.8)
        self.assertEqual(snapshot.last_sequence, 1)
        self.assertEqual(self.projector.snapshot().stocks, 1)

    async def test_sequence_gap_degrades_projection(self) -> None:
        for sequence in (1, 4):
            events = self.adapter.adapt_ticker(
                {
                    "code": "HK.00100",
                    "time": f"2026-08-31 10:00:0{sequence}",
                    "price": 356.0 + sequence,
                    "volume": 100,
                    "ticker_direction": "BUY",
                    "sequence": sequence,
                },
                received_time=NOW,
            )
            for event in events:
                await self.bus.publish(event)
        await self.bus.join()

        snapshot = self.projector.get("HK.00100")
        self.assertIs(snapshot.quality, DataQuality.DEGRADED)
        self.assertEqual(snapshot.sequence_gap_count, 2)
        self.assertTrue(any(reason.startswith("SEQUENCE_GAP") for reason in snapshot.quality_reasons))

    async def test_restored_capital_preserves_cumulative_values(self) -> None:
        aggregate = TickAggregate(
            stock_code="HK.00100",
            as_of=NOW,
            window_seconds=600,
            buy_amount=2_000_000,
            sell_amount=500_000,
            main_net=1_500_000,
            big_buy_count=5,
            big_sell_count=1,
            independent_buy_events=5,
            independent_sell_events=1,
            buy_sell_ratio=0.8,
            cumulative_main_net=8_000_000,
            cumulative_peak=9_000_000,
            cumulative_trough=-500_000,
            last_sequence=88,
            sample_count=6,
            quality=DataQuality.DEGRADED,
        )
        self.projector.restore_capital((aggregate,))

        snapshot = self.projector.get("HK.00100")
        self.assertEqual(snapshot.restored_capital.cumulative_main_net, 8_000_000)
        self.assertEqual(snapshot.last_sequence, 88)
        self.assertIn("CAPITAL_WINDOW_RESTORED_PARTIALLY", snapshot.quality_reasons)


if __name__ == "__main__":
    unittest.main()
