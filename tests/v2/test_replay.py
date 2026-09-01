import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from simple_trade.v2.application.event_bus import EventBus
from simple_trade.v2.domain.enums import EventType
from simple_trade.v2.domain.events import DomainEvent
from simple_trade.v2.infrastructure.futu_market_adapter import FutuMarketAdapter
from simple_trade.v2.interfaces.event_digest import event_stream_digest
from simple_trade.v2.interfaces.replay import MarketSessionPolicy, ReplayEngine
from simple_trade.v2.ports.clock import VirtualClock


HK = timezone(timedelta(hours=8))


class ReplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bus = EventBus(capacity=64)
        await self.bus.start()
        self.adapter = FutuMarketAdapter(strategy_version="test-v2")

    async def asyncTearDown(self) -> None:
        await self.bus.stop()

    def tick_event(self, at: str, sequence: int):
        events = self.adapter.adapt_ticker(
            {
                "code": "HK.00100",
                "time": at,
                "price": 356.6,
                "volume": 100,
                "ticker_direction": "BUY",
                "sequence": sequence,
            },
            received_time=datetime(2026, 8, 31, 2, 0, tzinfo=timezone.utc),
        )
        return events[-1]

    async def test_lunch_close_and_holiday_are_not_decision_eligible(self) -> None:
        received_buy_events: list[DomainEvent] = []
        self.bus.subscribe(EventType.BUY_CONFIRMED, received_buy_events.append)
        events = (
            self.tick_event("2026-08-31 10:00:00", 1),
            self.tick_event("2026-08-31 12:30:00", 2),
            self.tick_event("2026-08-31 16:01:00", 3),
        )
        engine = ReplayEngine(
            self.bus,
            VirtualClock(datetime(2026, 8, 31, 9, 0, tzinfo=HK)),
            MarketSessionPolicy(lambda market, day: day != date(2026, 9, 1)),
        )
        summary = await engine.replay(events)

        self.assertEqual(summary.eligible_events, 1)
        self.assertEqual(summary.closed_session_events, 2)
        self.assertEqual(received_buy_events, [])

        holiday_event = self.tick_event("2026-09-01 10:00:00", 4)
        holiday_summary = await engine.replay((holiday_event,))
        self.assertEqual(holiday_summary.eligible_events, 0)
        self.assertEqual(holiday_summary.closed_session_events, 1)

    async def test_out_of_order_replay_emits_quality_event(self) -> None:
        quality_events: list[DomainEvent] = []
        self.bus.subscribe(EventType.DATA_QUALITY_CHANGED, quality_events.append)
        later = self.tick_event("2026-08-31 10:00:02", 1)
        earlier = self.tick_event("2026-08-31 10:00:01", 2)
        engine = ReplayEngine(
            self.bus,
            VirtualClock(datetime(2026, 8, 31, 9, 0, tzinfo=HK)),
        )
        summary = await engine.replay((later, earlier))

        self.assertEqual(summary.out_of_order_events, 1)
        self.assertTrue(
            any("OUT_OF_ORDER_REPLAY_TIME" in event.reason_codes for event in quality_events)
        )

    async def test_live_and_replay_semantic_digest_match(self) -> None:
        event = self.tick_event("2026-08-31 10:00:00", 1)
        replay_copy = replace(
            event,
            event_id="different-event-id",
            correlation_id="different-correlation-id",
            received_time=event.received_time + timedelta(seconds=5),
            source="historical.replay",
        )
        self.assertEqual(
            event_stream_digest((event,)),
            event_stream_digest((replay_copy,)),
        )


if __name__ == "__main__":
    unittest.main()
