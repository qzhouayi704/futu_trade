import unittest
from datetime import datetime, timedelta, timezone

from simple_trade.v2.application.event_bus import EventBus
from simple_trade.v2.application.features.feature_engine import FeatureEngine
from simple_trade.v2.application.market_projector import MarketProjector
from simple_trade.v2.domain.enums import DataQuality, EventType
from simple_trade.v2.domain.events import FeatureSnapshotEvent, QuoteEvent
from simple_trade.v2.domain.features import DailyBar
from simple_trade.v2.domain.features import CapitalBaseline
from simple_trade.v2.infrastructure.futu_market_adapter import FutuMarketAdapter


NOW = datetime(2026, 8, 31, 10, 0, tzinfo=timezone(timedelta(hours=8)))


class FeatureEngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bus = EventBus(capacity=256)
        self.projector = MarketProjector()
        self.projector.register(self.bus)
        self.engine = FeatureEngine(self.projector, strategy_version="test-v2")
        self.engine.register(self.bus)
        self.adapter = FutuMarketAdapter(strategy_version="test-v2")
        self.events: list[FeatureSnapshotEvent] = []
        self.bus.subscribe(EventType.FEATURE_SNAPSHOT_READY, self.events.append)
        await self.bus.start()

    async def asyncTearDown(self) -> None:
        await self.bus.stop()
        self.engine.unregister()
        self.projector.unregister()

    async def test_complete_inputs_publish_good_feature_snapshot(self) -> None:
        target = "HK.00100"
        quote_events = []
        for index in range(20):
            code = target if index == 0 else f"HK.{index + 100:05d}"
            quote_events.extend(
                self.adapter.adapt_quote(
                    {
                        "code": code,
                        "last_price": 100.5 + index * 0.1,
                        "prev_close": 100.0,
                        "volume": 2_000_000,
                        "turnover": 50_000_000,
                        "turnover_rate": 2.0,
                        "amplitude": 4.0,
                        "lot_size": 100,
                        "plate_name": "AI" if index < 5 else "OTHER",
                        "data_date": "2026-08-31",
                        "data_time": "10:00:05",
                    },
                    received_time=NOW,
                )
            )
        quotes = tuple(
            event.quote for event in quote_events if isinstance(event, QuoteEvent)
        )
        self.engine.stage_quote_universe(quotes)
        self.engine.seed_daily_bars(
            tuple(
                DailyBar(
                    stock_code=target,
                    as_of=NOW - timedelta(days=20 - index),
                    open_price=95,
                    high_price=105,
                    low_price=90,
                    close_price=98 + index * 0.1,
                )
                for index in range(20)
            )
        )
        self.engine.seed_capital_baselines((CapitalBaseline(
            stock_code=target,
            large_order_threshold=100_000,
            flow_scale=100_000,
            quality=DataQuality.GOOD,
        ),))

        for event in self.adapter.adapt_order_book(
            target,
            {"Bid": [(100.4, 10_000, 5)], "Ask": [(100.6, 10_000, 5)]},
            received_time=NOW,
        ):
            await self.bus.publish(event)
        for event in self.adapter.adapt_ticker(
            {
                "code": target,
                "time": "2026-08-31 10:00:00",
                "price": 100.0,
                "volume": 2_000,
                "turnover": 200_000,
                "ticker_direction": "BUY",
                "sequence": 1,
            },
            received_time=NOW,
        ):
            await self.bus.publish(event)
        target_quote_event = next(
            event
            for event in quote_events
            if isinstance(event, QuoteEvent) and event.stock_code == target
        )
        await self.bus.publish(target_quote_event)
        await self.bus.join()

        snapshot = self.engine.latest(target)
        self.assertIsNotNone(snapshot)
        self.assertIs(snapshot.quality, DataQuality.GOOD)
        self.assertEqual(snapshot.missing_fields, ())
        self.assertEqual(tuple(window.window_seconds for window in snapshot.tick_windows), (60, 300, 900, 1800, 3600))
        self.assertIsNotNone(snapshot.capital_memory)
        self.assertEqual(snapshot.capital_memory.recent_15m_buy_events, 1)
        self.assertTrue(snapshot.price_acceptance.accepted)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].snapshot, snapshot)

    async def test_missing_reference_inputs_are_visible_not_silently_neutral(self) -> None:
        events = self.adapter.adapt_quote(
            {
                "code": "HK.00999",
                "last_price": 10,
                "prev_close": 10,
                "volume": 1,
                "turnover": 10,
                "data_date": "2026-08-31",
                "data_time": "10:00:05",
            },
            received_time=NOW,
        )
        for event in events:
            await self.bus.publish(event)
        await self.bus.join()

        snapshot = self.engine.latest("HK.00999")
        self.assertIs(snapshot.quality, DataQuality.INVALID)
        self.assertIn("price_position.daily_bars", snapshot.missing_fields)
        self.assertIn("capital_windows.tick_stream", snapshot.missing_fields)
        self.assertIn("capital_memory.event_stream", snapshot.missing_fields)
        self.assertIn("liquidity.lot_size", snapshot.missing_fields)


if __name__ == "__main__":
    unittest.main()
