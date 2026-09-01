import unittest
from datetime import datetime, timedelta, timezone

from simple_trade.v2.application.positions.coordinator import PositionCoordinator
from simple_trade.v2.domain.enums import DataQuality, EventType
from simple_trade.v2.domain.events import PositionReconciledEvent
from simple_trade.v2.domain.positions import PositionReconciliation, PositionSnapshot


NOW = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)


class MemoryPositionStores:
    def __init__(self) -> None:
        self.states = {}
        self.events = []

    async def get(self, stock_code, strategy_version):
        return self.states.get((strategy_version, stock_code))

    async def list_open(self, strategy_version):
        return tuple(
            state for (version, _), state in self.states.items()
            if version == strategy_version and state.status.value != "CLOSED"
        )

    async def append_with_position_state(self, event, state, expected_version):
        key = (state.strategy_version, state.stock_code)
        current = self.states.get(key)
        self.assert_version(current.version if current else 0, expected_version)
        self.events.append(event)
        self.states[key] = state
        return True

    @staticmethod
    def assert_version(current, expected):
        if current != expected:
            raise AssertionError(f"version {current} != {expected}")


class EmptyCandidates:
    def ranked(self, limit=20):
        return ()


class EmptyFeatures:
    def latest(self, stock_code):
        return None


def position() -> PositionSnapshot:
    return PositionSnapshot(
        stock_code="HK.00100", as_of=NOW, quantity=1000,
        sellable_quantity=1000, cost_price=100, current_price=101,
        peak_price=101, lot_size=100,
    )


def event(
    positions,
    *,
    authoritative=True,
    as_of=NOW,
    suffix="1",
) -> PositionReconciledEvent:
    reconciliation = PositionReconciliation(
        as_of=as_of,
        positions=tuple(positions),
        active_orders=(),
        authoritative=authoritative,
        quality=DataQuality.GOOD if authoritative else DataQuality.INVALID,
    )
    return PositionReconciledEvent(
        event_id=f"position-source-{suffix}",
        event_type=EventType.POSITION_RECONCILED,
        stock_code="PORTFOLIO",
        exchange_time=as_of,
        received_time=as_of,
        source="test",
        strategy_version="test-v2",
        correlation_id=f"position-correlation-{suffix}",
        reconciliation=reconciliation,
    )


class PositionCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_broker_position_opens_and_authoritative_absence_closes(self) -> None:
        stores = MemoryPositionStores()
        coordinator = PositionCoordinator(
            stores, stores, EmptyCandidates(), EmptyFeatures(),
            strategy_version="test-v2",
        )
        await coordinator.start()
        coordinator.on_reconciliation(event((position(),), suffix="open"))
        coordinator.on_reconciliation(event(
            (), as_of=NOW + timedelta(minutes=1), suffix="close"
        ))
        await coordinator.stop(drain=True)

        self.assertEqual(
            [item.event_type for item in stores.events],
            [EventType.POSITION_OPENED, EventType.POSITION_CLOSED],
        )
        self.assertTrue(all(item.payload["shadow_only"] for item in stores.events))
        self.assertNotIn(EventType.TRADE_INTENT_CREATED, [item.event_type for item in stores.events])
        self.assertNotIn(EventType.NOTIFICATION_REQUESTED, [item.event_type for item in stores.events])
        self.assertEqual(coordinator.snapshot().closed, 1)

    async def test_non_authoritative_empty_result_never_closes_position(self) -> None:
        stores = MemoryPositionStores()
        coordinator = PositionCoordinator(
            stores, stores, EmptyCandidates(), EmptyFeatures(),
            strategy_version="test-v2",
        )
        await coordinator.start()
        coordinator.on_reconciliation(event((position(),), suffix="open"))
        coordinator.on_reconciliation(event(
            (), authoritative=False, as_of=NOW + timedelta(minutes=1), suffix="failed"
        ))
        await coordinator.stop(drain=True)

        self.assertEqual([item.event_type for item in stores.events], [EventType.POSITION_OPENED])
        self.assertEqual(coordinator.snapshot().closed, 0)


if __name__ == "__main__":
    unittest.main()
