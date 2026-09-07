import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from simple_trade.utils.trade_time import HK_TIMEZONE
from simple_trade.v2.application.read_models.service import V2ReadModelService
from simple_trade.v2.domain.candidates import (
    OvernightObservation,
    OvernightPriority,
    OvernightStatus,
)


class NameDatabase:
    def execute_query(self, query: str, params: tuple | None = None) -> list:
        if "FROM stocks" in query:
            return [("HK.00100", "MINIMAX-W")]
        return []


class OvernightCoordinator:
    def __init__(self, observation: OvernightObservation) -> None:
        self._observation = observation

    def overnight_observations(self) -> tuple[OvernightObservation, ...]:
        return (self._observation,)

    def overnight_priority_codes(self) -> tuple[str, ...]:
        return (self._observation.priority.stock_code,)


class OvernightReadModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_exposes_lifecycle_and_selected_state_in_chinese_ui_contract(self) -> None:
        now = datetime.now(HK_TIMEZONE)
        priority = OvernightPriority(
            stock_code="HK.00100",
            source_date=(now - timedelta(days=1)).date().isoformat(),
            source_time=now - timedelta(days=1),
            score=78,
            reference_price=339,
            daily_percentile=0.3,
            atr_percent=4.2,
            capital_memory_score=76,
            day_main_net=8_000_000,
            independent_buy_events=4,
            source_reason="FAST_15M_MULTI_INFLOW_CONFIRMED",
            setup_id="setup-1",
            eligible_date=now.date().isoformat(),
            expires_date=(now + timedelta(days=2)).date().isoformat(),
            age_sessions=1,
        )
        observation = OvernightObservation(
            priority=priority,
            status=OvernightStatus.WATCHING,
            reason_code="OVERNIGHT_PRIORITY_PENDING_RECONFIRMATION",
            last_event_time=now,
        )
        runtime = SimpleNamespace(
            candidate_coordinator=OvernightCoordinator(observation),
            overnight_status="READY",
            overnight_updated_at=now,
        )

        result = await V2ReadModelService(NameDatabase(), runtime).overnight_candidates()

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["selected_count"], 1)
        self.assertFalse(result["alerts_enabled"])
        self.assertEqual(result["items"][0]["stock_name"], "MINIMAX-W")
        self.assertTrue(result["items"][0]["selected"])

    async def test_reports_unavailable_instead_of_an_empty_success_when_runtime_is_missing(self) -> None:
        result = await V2ReadModelService(NameDatabase()).overnight_candidates()

        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["selected_count"], 0)


if __name__ == "__main__":
    unittest.main()
