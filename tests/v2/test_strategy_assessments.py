import unittest
from datetime import datetime, timezone

from simple_trade.v2.application.strategy.assessments import (
    EntryPlan,
    SetupLifecycle,
    SignalPermission,
    StrategyAssessment,
    signal_permission,
)
from simple_trade.v2.domain.enums import StrategyStatus


class StrategyAssessmentContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.as_of = datetime(2026, 9, 7, 2, 30, tzinfo=timezone.utc)

    def test_permission_separates_tracking_research_formal_and_delivery(self) -> None:
        self.assertEqual(
            signal_permission("SETUP", alert_eligible=False),
            SignalPermission.TRACKING,
        )
        self.assertEqual(
            signal_permission("CONFIRMED", alert_eligible=False),
            SignalPermission.RESEARCH,
        )
        self.assertEqual(
            signal_permission("CONFIRMED", alert_eligible=True),
            SignalPermission.FORMAL_ELIGIBLE,
        )
        self.assertEqual(
            signal_permission("INVALIDATED", alert_eligible=True),
            SignalPermission.NONE,
        )
        self.assertEqual(
            signal_permission("CONFIRMED", alert_eligible=True, delivered=True),
            SignalPermission.DELIVERED,
        )
        self.assertEqual(
            signal_permission("UNKNOWN", alert_eligible=True),
            SignalPermission.NONE,
        )

    def test_strategy_assessment_and_lifecycle_require_traceable_fields(self) -> None:
        assessment = StrategyAssessment(
            stock_code="hk.00100",
            strategy_id="capital_absorption",
            as_of=self.as_of,
            stage=StrategyStatus.WATCHING,
            score=72.5,
            reference_price=100,
            permission=SignalPermission.TRACKING,
            reason_codes=("LOW_POSITION_ACCUMULATION_WATCH",),
            evidence={"daily_percentile": 0.2},
        )
        lifecycle = SetupLifecycle(
            setup_id="setup-1",
            stock_code=assessment.stock_code,
            strategy_version="test-v1",
            opened_at=self.as_of,
            updated_at=self.as_of,
            first_stage=StrategyStatus.SETUP,
            max_stage=StrategyStatus.WATCHING,
            current_status=StrategyStatus.WATCHING,
            current_reason_code=assessment.reason_codes[0],
            permission=assessment.permission,
        )

        self.assertEqual(assessment.stock_code, "HK.00100")
        self.assertEqual(lifecycle.permission, SignalPermission.TRACKING)
        with self.assertRaises(TypeError):
            assessment.evidence["daily_percentile"] = 0.3

    def test_entry_plan_rejects_inverted_prices_and_missing_horizon(self) -> None:
        plan = EntryPlan(
            setup_id="setup-1",
            stock_code="HK.00100",
            strategy_id="capital_absorption",
            as_of=self.as_of,
            reference_price=100,
            entry_price_min=99,
            entry_price_max=101,
            max_chase_price=102,
            invalidation_price=96,
            initial_position_ratio=0.05,
            holding_sessions=3,
        )
        self.assertEqual(plan.holding_sessions, 3)
        with self.assertRaisesRegex(ValueError, "价格顺序"):
            EntryPlan(
                setup_id="setup-1",
                stock_code="HK.00100",
                strategy_id="capital_absorption",
                as_of=self.as_of,
                reference_price=100,
                entry_price_min=99,
                entry_price_max=101,
                max_chase_price=100,
                invalidation_price=96,
                initial_position_ratio=0.05,
                holding_sessions=3,
            )


if __name__ == "__main__":
    unittest.main()
