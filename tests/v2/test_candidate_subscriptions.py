import asyncio
from datetime import datetime, timedelta, timezone
import unittest

from simple_trade.v2.application.candidate_subscriptions import (
    CandidateSubscriptionCoordinator,
)
from simple_trade.v2.domain.decisions import DecisionEvent
from simple_trade.v2.domain.enums import EventType


class FakeSubscriptionPort:
    def __init__(self) -> None:
        self.codes: list[str] = []
        self.protected: tuple[str, ...] = ()

    def subscribe_candidate(self, stock_code: str) -> bool:
        self.codes.append(stock_code)
        return True

    def protect_candidates(self, stock_codes: tuple[str, ...]) -> None:
        self.protected = stock_codes


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


def invalidated_event(reason_code: str) -> DecisionEvent:
    now = datetime.now(timezone.utc)
    return DecisionEvent(
        event_type=EventType.CANDIDATE_INVALIDATED,
        stock_code="HK.00100",
        exchange_time=now,
        received_time=now,
        source="test",
        schema_version=1,
        strategy_version="test-v2",
        old_state="WATCHING",
        new_state="INVALIDATED",
        reason_code=reason_code,
    )


def activity_event(
    *,
    stock_code: str = "HK.00100",
    event_type: EventType = EventType.CANDIDATE_UPDATED,
    new_state: str = "WATCHING",
    exchange_time: datetime | None = None,
) -> DecisionEvent:
    now = exchange_time or datetime.now(timezone.utc)
    return DecisionEvent(
        event_type=event_type,
        stock_code=stock_code,
        exchange_time=now,
        received_time=now,
        source="test",
        schema_version=1,
        strategy_version="test-v2",
        old_state="SETUP",
        new_state=new_state,
        reason_code="LOW_POSITION_ACCUMULATION_WATCH",
    )


class CandidateSubscriptionCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_prime_protects_and_subscribes_overnight_candidates(self) -> None:
        port = FakeSubscriptionPort()
        coordinator = CandidateSubscriptionCoordinator(port, cooldown_seconds=300)
        await coordinator.start()

        coordinator.prime(("HK.00100", "HK.03690"))
        await asyncio.wait_for(coordinator._queue.join(), timeout=1)

        self.assertEqual(port.protected, ("HK.00100", "HK.03690"))
        self.assertEqual(port.codes, ["HK.00100", "HK.03690"])
        await coordinator.stop()

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

    async def test_watching_and_confirmed_candidates_stay_protected(self) -> None:
        port = FakeSubscriptionPort()
        coordinator = CandidateSubscriptionCoordinator(port, cooldown_seconds=0)
        await coordinator.start()
        coordinator.prime(("HK.03690",))

        coordinator.on_candidate_activity(activity_event())
        coordinator.on_candidate_activity(activity_event(
            stock_code="HK.00819",
            event_type=EventType.BUY_CONFIRMED,
            new_state="CONFIRMED",
        ))
        await asyncio.wait_for(coordinator._queue.join(), timeout=1)

        self.assertEqual(port.protected, ("HK.03690", "HK.00100", "HK.00819"))
        self.assertIn("HK.00100", port.codes)
        self.assertIn("HK.00819", port.codes)
        await coordinator.stop()

    async def test_restored_intraday_candidates_survive_overnight_refresh(self) -> None:
        port = FakeSubscriptionPort()
        coordinator = CandidateSubscriptionCoordinator(port)
        await coordinator.start()

        coordinator.restore_intraday(("HK.00100", "HK.00819"), "2026-09-09")
        coordinator.prime(("HK.03690",))

        self.assertEqual(port.protected, ("HK.03690", "HK.00100", "HK.00819"))
        await coordinator.stop()

    async def test_hard_invalidation_keeps_intraday_observation_protected(self) -> None:
        port = FakeSubscriptionPort()
        coordinator = CandidateSubscriptionCoordinator(port)
        await coordinator.start()
        coordinator.prime(("HK.00100", "HK.03690"))

        coordinator.on_candidate_invalidated(
            invalidated_event("PRICE_ACCEPTANCE_BROKEN")
        )

        self.assertEqual(port.protected, ("HK.03690", "HK.00100"))
        await coordinator.stop()

    async def test_temporary_invalidation_keeps_overnight_candidate_protected(self) -> None:
        port = FakeSubscriptionPort()
        coordinator = CandidateSubscriptionCoordinator(port)
        await coordinator.start()
        coordinator.prime(("HK.00100",))

        coordinator.on_candidate_invalidated(
            invalidated_event("FLOW_CONFIRMATION_EXPIRED")
        )

        self.assertEqual(port.protected, ("HK.00100",))
        await coordinator.stop()

    async def test_new_session_releases_previous_intraday_candidates(self) -> None:
        port = FakeSubscriptionPort()
        coordinator = CandidateSubscriptionCoordinator(port, cooldown_seconds=0)
        await coordinator.start()
        coordinator.prime(("HK.03690",))
        hk = timezone(timedelta(hours=8))

        coordinator.on_candidate_activity(activity_event(
            stock_code="HK.00100",
            exchange_time=datetime(2026, 9, 9, 10, tzinfo=hk),
        ))
        coordinator.on_candidate_activity(activity_event(
            stock_code="HK.00819",
            exchange_time=datetime(2026, 9, 10, 10, tzinfo=hk),
        ))

        self.assertEqual(port.protected, ("HK.03690", "HK.00819"))
        await coordinator.stop()
