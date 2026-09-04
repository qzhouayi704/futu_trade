import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from simple_trade.v2.application.outcomes.coordinator import OutcomeCoordinator
from simple_trade.v2.application.outcomes.evaluator import OutcomeEvaluator
from simple_trade.v2.application.read_models.cohorts import build_shadow_acceptance
from simple_trade.v2.application.read_models.distribution import histogram, percentile
from simple_trade.v2.domain.decisions import DecisionEvent
from simple_trade.v2.domain.enums import DataQuality, EventType
from simple_trade.v2.domain.events import QuoteEvent
from simple_trade.v2.domain.market import QuoteSnapshot
from simple_trade.v2.domain.outcomes import OutcomeRecord


def make_quote(code: str, at: datetime, price: float, high: float, low: float) -> QuoteSnapshot:
    return QuoteSnapshot(
        stock_code=code, exchange_time=at, last_price=price, prev_close=100,
        high_price=high, low_price=low, quality=DataQuality.GOOD,
    )


class MemoryOutcomeStore:
    def __init__(self) -> None:
        self.records: dict[str, OutcomeRecord] = {}

    async def upsert(self, outcome: OutcomeRecord) -> bool:
        self.records[outcome.decision_event_id] = outcome
        return True

    async def load_active(self, strategy_version: str) -> tuple[OutcomeRecord, ...]:
        return tuple(
            item for item in self.records.values()
            if item.strategy_version == strategy_version and item.next_day_return_pct is None
        )


class OutcomeEvaluatorTests(unittest.TestCase):
    def test_tracks_mfe_mae_milestones_close_and_next_day(self) -> None:
        signal_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        outcome = OutcomeRecord(
            decision_event_id="buy-1", stock_code="HK.00100",
            strategy_version="v2", signal_time=signal_time, signal_price=100,
        )
        evaluator = OutcomeEvaluator()
        intraday = evaluator.apply_quote(
            outcome,
            make_quote("HK.00100", signal_time + timedelta(minutes=30), 106, 110, 90),
        )
        same_day = evaluator.apply_quote(
            intraday,
            make_quote("HK.00100", signal_time + timedelta(hours=6), 104, 110, 90),
        )
        self.assertEqual(same_day.mfe_pct, 6)
        self.assertEqual(same_day.mae_pct, 0)
        self.assertIsNotNone(same_day.time_to_1_5_seconds)
        self.assertIsNotNone(same_day.time_to_3_seconds)
        self.assertIsNotNone(same_day.time_to_5_seconds)
        self.assertEqual(same_day.close_return_pct, 4)

        next_day = evaluator.apply_quote(
            same_day,
            make_quote("HK.00100", signal_time + timedelta(days=1), 103, 104, 99),
        )
        self.assertEqual(next_day.next_day_return_pct, 3)

    def test_rotation_compares_replacement_with_hold_control(self) -> None:
        now = datetime.now(timezone.utc)
        outcome = OutcomeRecord(
            decision_event_id="rotate-1", stock_code="HK.00200",
            strategy_version="v2", signal_time=now, signal_price=20,
            control_stock_code="HK.00100", control_signal_price=100,
        )
        evaluator = OutcomeEvaluator()
        outcome = evaluator.apply_quote(
            outcome, make_quote("HK.00200", now + timedelta(minutes=5), 21, 21, 20)
        )
        outcome = evaluator.apply_quote(
            outcome, make_quote("HK.00100", now + timedelta(minutes=5), 99, 101, 98)
        )
        self.assertEqual(outcome.rotation_return_pct, 5)
        self.assertEqual(outcome.hold_control_return_pct, -1)

    def test_distribution_uses_interpolation_and_stable_bands(self) -> None:
        self.assertEqual(percentile([1, 2, 3, 4, 5], 50), 3)
        bands = histogram([-4, -1, 1, 2, 4, 6])
        self.assertEqual([item["count"] for item in bands], [1, 1, 1, 1, 1, 1])


class OutcomeCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_position_add_decision_creates_separate_outcome(self):
        store = MemoryOutcomeStore()
        coordinator = OutcomeCoordinator(store, strategy_version="test-v2")
        await coordinator.start()
        now = datetime.now(timezone.utc)
        coordinator.on_event(DecisionEvent(
            event_type=EventType.POSITION_ADD_CONFIRMED,
            stock_code="HK.00100",
            exchange_time=now,
            received_time=now,
            source="test",
            strategy_version="test-v2",
            reason_code="POSITION_ADD_CAPITAL_CONFIRMED",
            payload={"position": {"current_price": 10.2}},
        ))
        await coordinator.stop(drain=True)

        self.assertEqual(len(store.records), 1)
        outcome = next(iter(store.records.values()))
        self.assertEqual(outcome.signal_price, 10.2)

    async def test_buy_decision_creates_and_quote_updates_projection(self) -> None:
        store = MemoryOutcomeStore()
        coordinator = OutcomeCoordinator(store, strategy_version="v2", queue_capacity=8)
        await coordinator.start()
        now = datetime.now(timezone.utc)
        event = DecisionEvent(
            event_id="buy-1", event_type=EventType.BUY_CONFIRMED,
            stock_code="HK.00100", exchange_time=now, received_time=now,
            source="test", strategy_version="v2", reason_code="CONFIRMED",
            payload={"feature_snapshot": {"quote": {"last_price": 100}}},
        )
        quote = make_quote("HK.00100", now + timedelta(minutes=2), 102, 102, 99)
        coordinator.on_event(event)
        coordinator.on_event(QuoteEvent(
            event_type=EventType.QUOTE_UPDATED, stock_code=quote.stock_code,
            exchange_time=quote.exchange_time, received_time=quote.exchange_time,
            source="test", strategy_version="v2", quote=quote,
        ))
        await coordinator._queue.join()
        await coordinator.stop(drain=True)
        self.assertEqual(store.records["buy-1"].mfe_pct, 2)
        self.assertTrue(store.records["buy-1"].reached_1_5)

    async def test_first_inflow_is_recorded_as_control_but_other_updates_are_ignored(self) -> None:
        store = MemoryOutcomeStore()
        coordinator = OutcomeCoordinator(store, strategy_version="v2", queue_capacity=8)
        await coordinator.start()
        now = datetime.now(timezone.utc)
        for event_id, reason in (
            ("watch-1", "FIRST_STRONG_INFLOW_WATCH"),
            ("update-1", "RANKING_REFRESH"),
        ):
            coordinator.on_event(DecisionEvent(
                event_id=event_id, event_type=EventType.CANDIDATE_UPDATED,
                stock_code="HK.00100", exchange_time=now, received_time=now,
                source="test", strategy_version="v2", reason_code=reason,
                payload={"feature_snapshot": {"quote": {"last_price": 100}}},
            ))
        await coordinator._queue.join()
        await coordinator.stop(drain=True)
        self.assertIn("watch-1", store.records)
        self.assertNotIn("update-1", store.records)


class ShadowAcceptanceTests(unittest.TestCase):
    @staticmethod
    def _row(
        event_id: str,
        event_type: str,
        reason: str,
        day: str,
        *,
        buys: int,
        sells: int = 0,
        reached: bool = False,
        regime: str = "NORMAL",
    ) -> dict:
        return {
            "event_id": event_id, "event_type": event_type, "reason_code": reason,
            "signal_time": f"{day}T10:00:00+08:00", "stock_code": "HK.00100",
            "mfe_pct": 2.0 if reached else 0.8, "mae_pct": -0.5,
            "close_return_pct": 1.0 if reached else -0.2,
            "next_day_return_pct": 0.5, "reached_1_5": reached,
            "reached_3": False, "reached_5": False,
            "time_to_1_5_seconds": 900 if reached else None,
            "hold_control_return_pct": None, "rotation_return_pct": None,
            "payload": {"feature_snapshot": {
                "market_context": {"market_regime": regime},
                "tick_windows": [{
                    "window_seconds": 900, "independent_buy_events": buys,
                    "independent_sell_events": sells, "buy_amount": 100,
                    "sell_amount": 30 if sells else 0, "main_net": 70,
                }],
            }},
        }

    def test_compares_single_control_with_confirmed_multi_inflow(self) -> None:
        rows = [
            self._row(
                "watch", "CANDIDATE_UPDATED", "FIRST_STRONG_INFLOW_WATCH",
                "2026-09-01", buys=1,
            ),
            self._row(
                "buy", "BUY_CONFIRMED", "FAST_15M_MULTI_INFLOW_CONFIRMED",
                "2026-09-01", buys=2, sells=1, reached=True,
            ),
        ]
        report = build_shadow_acceptance(rows, target_days=10)
        self.assertEqual(report["observed_days"], 1)
        self.assertFalse(report["ready"])
        self.assertEqual(report["entry_summary"]["reached_1_5_ratio"], 1.0)
        self.assertEqual(report["first_inflow_control"]["reached_1_5_ratio"], 0.0)
        inflows = {item["key"]: item for item in report["cohorts"]["inflow_frequency"]}
        self.assertEqual(inflows["SINGLE"]["sample_count"], 1)
        self.assertEqual(inflows["MULTI_2"]["sample_count"], 1)
        outflows = {item["key"] for item in report["cohorts"]["outflow_context"]}
        self.assertEqual(outflows, {"NO_LARGE_OUTFLOW", "MINOR_OUTFLOW"})

    def test_uses_latest_distinct_trading_days_and_rotation_advantage(self) -> None:
        rows = [
            self._row(
                str(day), "BUY_CONFIRMED", "FAST_15M_MULTI_INFLOW_CONFIRMED",
                f"2026-08-{day:02d}", buys=2, reached=True,
            )
            for day in range(1, 13)
        ]
        rotation = self._row(
            "rotation", "ROTATION_PROPOSED", "CONFIRMED_CANDIDATE_NET_ADVANTAGE",
            "2026-08-12", buys=0,
        )
        rotation["rotation_return_pct"] = 3.0
        rotation["hold_control_return_pct"] = 1.0
        rows.append(rotation)
        report = build_shadow_acceptance(rows, target_days=10)
        self.assertTrue(report["ready"])
        self.assertEqual(report["date_range"]["start"], "2026-08-03")
        self.assertEqual(report["rotation_summary"]["advantage"]["percentiles"]["p50"], 2.0)
        self.assertEqual(report["rotation_summary"]["rotation_win_ratio"], 1.0)


class V2RouteContractTests(unittest.TestCase):
    def test_backend_and_frontend_routes_exist(self) -> None:
        root = Path(__file__).resolve().parents[2]
        backend = (root / "simple_trade/routers/v2/read_models.py").read_text(encoding="utf-8")
        for path in (
            "/cockpit", "/candidates", "/candidates/history",
            "/candidates/{stock_code}/timeline", "/positions", "/decisions",
            "/outcomes/distribution", "/outcomes/alert-performance",
            "/outcomes/shadow-acceptance",
            "/system/health", "/system/runtime",
        ):
            self.assertIn(f'@router.get("{path}"', backend)
        self.assertTrue((root / "futu-trade-frontend/src/app/v2/page.tsx").is_file())
        self.assertTrue((root / "futu-trade-frontend/src/app/api/v2/[...path]/route.ts").is_file())


if __name__ == "__main__":
    unittest.main()
