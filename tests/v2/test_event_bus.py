import asyncio
import unittest
from datetime import datetime, timezone

from simple_trade.v2.application.event_bus import EventBus
from simple_trade.v2.domain.enums import EventType
from simple_trade.v2.domain.events import DomainEvent


def make_event(sequence: int) -> DomainEvent:
    now = datetime.now(timezone.utc)
    return DomainEvent(
        event_type=EventType.QUOTE_UPDATED,
        stock_code="HK.00100",
        exchange_time=now,
        received_time=now,
        source="test",
        sequence=sequence,
    )


class EventBusTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_and_handler_failure_isolation(self) -> None:
        bus = EventBus(capacity=8)
        received: list[int] = []

        async def failing_handler(event: DomainEvent) -> None:
            raise RuntimeError(f"failed-{event.sequence}")

        async def collecting_handler(event: DomainEvent) -> None:
            received.append(event.sequence or 0)

        bus.subscribe(EventType.QUOTE_UPDATED, failing_handler)
        bus.subscribe(EventType.QUOTE_UPDATED, collecting_handler)
        await bus.start()
        try:
            with self.assertLogs(level="ERROR") as captured:
                self.assertTrue(await bus.publish(make_event(1)))
                self.assertTrue(await bus.publish(make_event(2)))
                await bus.join()
        finally:
            await bus.stop()

        self.assertEqual(received, [1, 2])
        stats = bus.snapshot()
        self.assertEqual(stats.published, 2)
        self.assertEqual(stats.processed, 2)
        self.assertEqual(stats.handler_failures, 2)
        self.assertEqual(len(captured.records), 2)

    async def test_full_queue_rejects_without_blocking(self) -> None:
        bus = EventBus(capacity=1)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocking_handler(event: DomainEvent) -> None:
            entered.set()
            await release.wait()

        bus.subscribe(EventType.QUOTE_UPDATED, blocking_handler)
        await bus.start()
        self.assertTrue(bus.publish_nowait(make_event(1)))
        await entered.wait()
        self.assertTrue(bus.publish_nowait(make_event(2)))
        self.assertFalse(bus.publish_nowait(make_event(3)))
        release.set()
        await bus.stop(drain=True)

        stats = bus.snapshot()
        self.assertEqual(stats.dropped, 1)
        self.assertEqual(stats.processed, 2)


if __name__ == "__main__":
    unittest.main()
