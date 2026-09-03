import asyncio
from datetime import datetime, timezone
import unittest

from simple_trade.v2.application.candidate_subscriptions import (
    CandidateSubscriptionCoordinator,
)
from simple_trade.v2.domain.decisions import DecisionEvent
from simple_trade.v2.domain.enums import EventType


class FakeSubscriptionPort:
    def __init__(self) -> None:
        self.codes: list[str] = []

    def subscribe_candidate(self, stock_code: str) -> bool:
        self.codes.append(stock_code)
        return True


def entered_event(new_state: str = "SETUP") -> DecisionEvent:
    now = datetime.now(timezone.utc)
    return DecisionEvent(
        event_type=EventType.CANDIDATE_ENTERED,
        stock_code="HK.00100",
        exchange_time=now,
        received_time=now,
        source="test",
        schema_version=1,
        strategy_version="test-v2",
        old_state="IDLE",
        new_state=new_state,
        reason_code="QUOTE_DATA_ENRICHMENT_SETUP",
    )


class CandidateSubscriptionCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_entry_promotes_ticker_without_blocking_event_handler(self) -> None:
        port = FakeSubscriptionPort()
        coordinator = CandidateSubscriptionCoordinator(port, cooldown_seconds=300)
        await coordinator.start()

        coordinator.on_candidate_entered(entered_event())
        coordinator.on_candidate_entered(entered_event())
        await asyncio.wait_for(coordinator._queue.join(), timeout=1)

        self.assertEqual(port.codes, ["HK.00100"])
        self.assertEqual(coordinator.snapshot().completed, 1)
        self.assertEqual(coordinator.snapshot().deduplicated, 1)
        await coordinator.stop()

    async def test_non_candidate_state_is_ignored(self) -> None:
        port = FakeSubscriptionPort()
        coordinator = CandidateSubscriptionCoordinator(port)
        await coordinator.start()

        coordinator.on_candidate_entered(entered_event("CONFIRMED"))
        await asyncio.sleep(0)

        self.assertEqual(port.codes, [])
        await coordinator.stop()
