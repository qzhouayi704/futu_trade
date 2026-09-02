import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np


ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "analysis"
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

import low_position_accumulation_grid as grid  # noqa: E402
import low_position_adaptive_exit as adaptive_exit  # noqa: E402
import low_position_adaptive_tick_holdout as adaptive_tick  # noqa: E402
import low_position_tick_holdout as tick_holdout  # noqa: E402


class LowPositionAccumulationGridTests(unittest.TestCase):
    def test_confirmation_requires_count_span_and_sixty_minute_recency(self) -> None:
        indices = [1, 6, 11, 80]

        self.assertEqual(grid.select_confirmation(indices, 3, 10), (11, 1))
        self.assertIsNone(grid.select_confirmation(indices, 4, 10))
        self.assertIsNone(grid.select_confirmation(indices, 2, 60))
        self.assertEqual(grid.select_confirmation([20, 80], 2, 60), (80, 20))

    def test_exit_applies_stop_and_round_trip_cost(self) -> None:
        prices = np.asarray([100.0, 99.5, 98.9, 101.0])
        capital = {
            "buy": np.asarray([1.0, 1.0, 1.0, 1.0]),
            "sell": np.zeros(4),
            "net": np.ones(4),
        }

        result = grid.simulate_exit(
            prices,
            0,
            capital,
            threshold=10.0,
            stop_loss=0.01,
            trail_pullback=0.015,
        )

        self.assertAlmostEqual(result, -0.0135)

    def test_exit_ignores_small_relative_sell_offset(self) -> None:
        prices = np.asarray([100.0, 100.5, 102.0])
        capital = {
            "buy": np.asarray([10.0, 4.0, 10.0]),
            "sell": np.asarray([0.0, 6.0, 0.0]),
            "net": np.asarray([10.0, -2.0, 10.0]),
        }

        result = grid.simulate_exit(
            prices,
            0,
            capital,
            threshold=10.0,
            stop_loss=0.02,
            trail_pullback=0.02,
        )

        self.assertAlmostEqual(result, 0.0175)

    def test_exit_prioritizes_material_net_outflow(self) -> None:
        prices = np.asarray([100.0, 100.5, 102.0])
        capital = {
            "buy": np.asarray([10.0, 0.0, 10.0]),
            "sell": np.asarray([0.0, 10.0, 0.0]),
            "net": np.asarray([10.0, -10.0, 10.0]),
        }

        result = grid.simulate_exit(
            prices,
            0,
            capital,
            threshold=10.0,
            stop_loss=0.02,
            trail_pullback=0.02,
        )

        self.assertAlmostEqual(result, 0.0025)

    def test_exit_can_lock_fixed_profit_target(self) -> None:
        prices = np.asarray([100.0, 101.6, 104.0])
        capital = {
            "buy": np.ones(3),
            "sell": np.zeros(3),
            "net": np.ones(3),
        }

        result = grid.simulate_exit(
            prices,
            0,
            capital,
            threshold=10.0,
            stop_loss=0.01,
            trail_pullback=0.01,
            take_profit=0.015,
        )

        self.assertAlmostEqual(result, 0.0135)

    def test_exit_can_require_repeated_outflow_confirmation(self) -> None:
        prices = np.asarray([100.0, 99.8, 100.0, 100.2, 100.4, 100.5, 100.6])
        capital = {
            "buy": np.zeros(7),
            "sell": np.asarray([0.0, 10.0, 0.0, 0.0, 0.0, 0.0, 10.0]),
            "net": np.asarray([0.0, -10.0, 0.0, 0.0, 0.0, 0.0, -10.0]),
        }

        result = grid.simulate_exit(
            prices,
            0,
            capital,
            threshold=10.0,
            stop_loss=0.02,
            trail_pullback=0.02,
            outflow_events=2,
            outflow_span=3,
            sell_events=capital["sell"],
        )

        self.assertAlmostEqual(result, 0.0035)

    def test_outflow_can_be_advisory_only(self) -> None:
        prices = np.asarray([100.0, 99.8, 101.6])
        capital = {
            "buy": np.zeros(3),
            "sell": np.asarray([0.0, 10.0, 0.0]),
            "net": np.asarray([0.0, -10.0, 0.0]),
        }

        result = grid.simulate_exit(
            prices,
            0,
            capital,
            threshold=10.0,
            stop_loss=0.02,
            trail_pullback=0.02,
            take_profit=0.015,
            outflow_events=0,
            sell_events=capital["sell"],
        )

        self.assertAlmostEqual(result, 0.0135)

    def test_trailing_waits_for_activation_profit(self) -> None:
        prices = np.asarray([100.0, 102.0, 100.8, 103.0])
        capital = {
            "buy": np.ones(4),
            "sell": np.zeros(4),
            "net": np.ones(4),
        }

        result = grid.simulate_exit(
            prices,
            0,
            capital,
            threshold=10.0,
            stop_loss=0.03,
            trail_pullback=0.01,
            trail_activation=0.03,
            outflow_events=0,
        )

        self.assertAlmostEqual(result, 0.0275)

    def test_tick_snapshot_requires_independent_event_span_and_flow(self) -> None:
        first = datetime(2026, 8, 31, 10, 0)
        aggregate = SimpleNamespace(
            independent_buy_events=3,
            first_independent_buy_at=first,
            last_independent_buy_at=first + timedelta(minutes=10),
            main_net=450.0,
            buy_sell_ratio=0.70,
        )
        spec = grid.FlowSpec(15, 4.0, 1.5, 0.65, 3, 10)

        self.assertTrue(tick_holdout.qualifies_snapshot(aggregate, spec, 100.0, 300.0))
        aggregate.last_independent_buy_at = first + timedelta(minutes=9, seconds=59)
        self.assertFalse(tick_holdout.qualifies_snapshot(aggregate, spec, 100.0, 300.0))

    def test_tick_holdout_selects_distinct_families_and_baseline(self) -> None:
        row = {
            "flow_key": "first",
            "flow": {},
            "overlay": {},
            "exit": {},
        }
        payload = {
            "final_top": [row, dict(row), {**row, "flow_key": "second"}],
            "baseline": {**row, "flow_key": "baseline"},
        }

        selected = tick_holdout.selected_configs(payload, 2)

        self.assertEqual([item["flow_key"] for item in selected], ["first", "second", "baseline"])
        row_selected = tick_holdout.selected_configs(payload, 2, distinct_flow=False)
        self.assertEqual([item["flow_key"] for item in row_selected], ["first", "first", "baseline"])

    def test_overlay_can_require_vwap_and_morning_cutoff(self) -> None:
        event = SimpleNamespace(
            pos20=0.40,
            breadth=0.50,
            confirm_vwap_distance=0.001,
            index=grid.flow.IDX["11:30"],
        )
        overlay = grid.OverlaySpec(0.50, 0.40, "above-vwap", "11:30")

        self.assertTrue(grid.passes_overlay(event, overlay))
        event.confirm_vwap_distance = -0.0001
        self.assertFalse(grid.passes_overlay(event, overlay))
        event.confirm_vwap_distance = 0.001
        event.index = grid.flow.IDX["11:31"]
        self.assertFalse(grid.passes_overlay(event, overlay))

    def test_tick_overlay_uses_same_morning_cutoff(self) -> None:
        overlay = grid.OverlaySpec(0.50, 0.40, "above-vwap", "11:30")

        self.assertTrue(
            tick_holdout.passes_tick_overlay(
                position=0.40,
                breadth=0.50,
                vwap_distance=0.001,
                index=grid.flow.IDX["11:30"],
                overlay=overlay,
            )
        )
        self.assertFalse(
            tick_holdout.passes_tick_overlay(
                position=0.40,
                breadth=0.50,
                vwap_distance=0.001,
                index=grid.flow.IDX["11:31"],
                overlay=overlay,
            )
        )

    def test_adaptive_exit_keeps_position_when_new_inflow_supports_pullback(self) -> None:
        prices = np.asarray([100.0, 101.5, 103.0, 101.0, 104.0])
        vwap = np.full(5, 100.0)
        spec = adaptive_exit.AdaptiveExitSpec(
            hard_stop=0.03,
            trail_activation=0.025,
            trail_pullback=0.015,
            vwap_break_minutes=3,
            support_grace=1,
            profit_floor=0.0,
            take_profit=None,
            vwap_tolerance=0.0,
        )

        supported = adaptive_exit.simulate_adaptive_exit(
            prices,
            start=0,
            watch=0,
            vwap=vwap,
            support_indices=[0, 3],
            outflow_indices=[],
            spec=spec,
        )
        unsupported = adaptive_exit.simulate_adaptive_exit(
            prices,
            start=0,
            watch=0,
            vwap=vwap,
            support_indices=[0],
            outflow_indices=[],
            spec=spec,
        )

        self.assertEqual(supported.reason, "EOD")
        self.assertAlmostEqual(supported.net_return, 0.0375)
        self.assertEqual(unsupported.reason, "TRAIL_AFTER_SUPPORT_LOST")
        self.assertAlmostEqual(unsupported.net_return, 0.0075)

    def test_adaptive_exit_requires_outflow_count_and_span(self) -> None:
        self.assertFalse(adaptive_exit.confirmed_outflow([2, 4, 6], 6, 3, 5))
        self.assertTrue(adaptive_exit.confirmed_outflow([1, 4, 6], 6, 3, 5))

    def test_tick_adaptive_exit_uses_exact_outflow_span(self) -> None:
        first = datetime(2026, 8, 31, 10, 0)
        now = first + timedelta(minutes=6)

        self.assertFalse(
            adaptive_tick.exact_outflow_confirmed(
                [first, first + timedelta(minutes=2), now], now, 3, 7
            )
        )
        self.assertTrue(
            adaptive_tick.exact_outflow_confirmed(
                [first, first + timedelta(minutes=2), now], now, 3, 5
            )
        )


if __name__ == "__main__":
    unittest.main()
