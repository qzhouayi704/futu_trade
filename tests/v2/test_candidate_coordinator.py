import unittest
from datetime import timedelta

from simple_trade.v2.application.strategy.coordinator import CandidateCoordinator
from simple_trade.v2.application.strategy.dual_track import DualTrackScoreboard
from simple_trade.v2.domain.decisions import DecisionEvent
from simple_trade.v2.domain.enums import EventType
from simple_trade.v2.domain.events import FeatureSnapshotEvent

from tests.v2.test_candidate_strategy import NOW, snapshot, window


class MemoryStores:
    def __init__(self) -> None:
        self.states = {}
        self.events = []

    async def get(self, stock_code, strategy_version):
        return self.states.get((strategy_version, stock_code))

    async def append_with_state(self, event, state, expected_version):
        key = (state.strategy_version, state.stock_code)
        current = self.states.get(key)
        current_version = current.version if current is not None else 0
        if current_version != expected_version:
            from simple_trade.v2.infrastructure.sqlite_state_store import StateConflictError
            raise StateConflictError("test conflict")
        self.events.append(event)
        self.states[key] = state
        return True


def feature_event(item, suffix: str) -> FeatureSnapshotEvent:
    return FeatureSnapshotEvent(
        event_id=f"feature-{suffix}",
        event_type=EventType.FEATURE_SNAPSHOT_READY,
        stock_code=item.stock_code,
        exchange_time=item.computed_at,
        received_time=item.computed_at,
        source="test",
        strategy_version="test-v2",
        correlation_id=f"correlation-{suffix}",
        snapshot=item,
    )


class CandidateCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_transitions_persist_traceable_snapshots_without_notifications(self) -> None:
        stores = MemoryStores()
        scoreboard = DualTrackScoreboard()
        coordinator = CandidateCoordinator(
            stores, stores, strategy_version="test-v2", observer=scoreboard
        )
        await coordinator.start()
        coordinator.on_feature_snapshot(feature_event(snapshot(), "setup"))
        one = window(900, buys=1, buy_amount=900_000)
        coordinator.on_feature_snapshot(feature_event(
            snapshot(as_of=NOW + timedelta(seconds=1), windows=(one,)), "watch"
        ))
        two = window(900, buys=2, buy_amount=1_200_000, span=301)
        coordinator.on_feature_snapshot(feature_event(
            snapshot(as_of=NOW + timedelta(seconds=301), windows=(two,)), "confirm"
        ))
        await coordinator.stop(drain=True)

        self.assertEqual(
            [event.event_type for event in stores.events],
            [EventType.CANDIDATE_ENTERED, EventType.CANDIDATE_UPDATED, EventType.BUY_CONFIRMED],
        )
        self.assertTrue(stores.events[-1].payload["shadow_only"])
        self.assertIn("feature_snapshot", stores.events[-1].payload)
        self.assertNotIn(EventType.NOTIFICATION_REQUESTED, [event.event_type for event in stores.events])
        self.assertEqual(coordinator.latest("HK.00100").status.value, "BUY_CONFIRMED")
        self.assertEqual(scoreboard.report().v2_confirmed, 1)

    async def test_restart_loads_persisted_state_and_does_not_duplicate_setup(self) -> None:
        stores = MemoryStores()
        first = CandidateCoordinator(stores, stores, strategy_version="test-v2")
        await first.start()
        first.on_feature_snapshot(feature_event(snapshot(), "first"))
        await first.stop(drain=True)

        restarted = CandidateCoordinator(stores, stores, strategy_version="test-v2")
        await restarted.start()
        restarted.on_feature_snapshot(feature_event(
            snapshot(as_of=NOW + timedelta(seconds=5)), "restart"
        ))
        await restarted.stop(drain=True)

        self.assertEqual(len(stores.events), 1)
        self.assertEqual(stores.events[0].event_type, EventType.CANDIDATE_ENTERED)


class DualTrackTests(unittest.TestCase):
    def test_same_stock_signals_within_five_minutes_are_matched(self) -> None:
        scoreboard = DualTrackScoreboard()
        scoreboard.record_legacy_payload({
            "stock_code": "HK.00100", "timestamp": NOW.timestamp(),
            "direction": "RISING", "reason": "legacy",
        })
        scoreboard.record_v2(DecisionEvent(
            event_type=EventType.BUY_CONFIRMED,
            stock_code="HK.00100",
            exchange_time=NOW + timedelta(minutes=3),
            received_time=NOW + timedelta(minutes=3),
            source="test", strategy_version="test-v2", reason_code="FAST",
        ))

        report = scoreboard.report()
        self.assertEqual((report.matched, report.legacy_only, report.v2_only), (1, 0, 0))
        self.assertIn("5 分钟内同股匹配", report.to_markdown())


if __name__ == "__main__":
    unittest.main()
