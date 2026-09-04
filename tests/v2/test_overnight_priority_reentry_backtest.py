import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "analysis"
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

import overnight_priority_reentry_backtest as backtest  # noqa: E402


def event(code, day, index, **overrides):
    values = {
        "code": code,
        "day": day,
        "index": index,
        "pos20": 0.45,
        "extension_atr": 1.0,
        "breadth": 0.55,
        "confirm_vwap_distance": 0.002,
        "day_change": 0.02,
        "confirm_drawdown": -0.01,
        "eod": 0.02,
        "mfe_eod": 0.04,
        "mae60": -0.01,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class OvernightPriorityReentryBacktestTests(unittest.TestCase):
    def test_pairs_only_previous_trading_day_same_stock(self):
        prior = event("HK.00100", "2026-09-01", 10)
        stale = event("HK.03690", "2026-08-31", 10)
        trigger = event("HK.00100", "2026-09-02", 20)
        other = event("HK.03690", "2026-09-02", 20)

        result = backtest.pair_events(
            [prior, stale],
            [trigger, other],
            ["2026-08-31", "2026-09-01", "2026-09-02"],
        )

        self.assertEqual(result, [(prior, trigger)])

    def test_trigger_rejects_overheated_price(self):
        item = event("HK.00100", "2026-09-02", 20, day_change=0.061)

        self.assertFalse(backtest.passes_trigger(item))

    def test_summary_uses_intraday_high_distribution(self):
        result = backtest.summarize([
            event("HK.00100", "2026-09-02", 20, mfe_eod=0.02),
            event("HK.03690", "2026-09-03", 20, mfe_eod=0.06),
        ])

        self.assertEqual(result["mfe_distribution"]["1.5~3%"]["count"], 1)
        self.assertEqual(result["mfe_distribution"][">=5%"]["count"], 1)

    def test_selection_score_penalizes_large_early_drawdown(self):
        stable = backtest.summarize([
            event("HK.00100", "2026-09-02", 20, mae60=-0.01),
            event("HK.03690", "2026-09-03", 20, mae60=-0.01),
        ])
        risky = dict(stable)
        risky["mae60_le_minus2"] = 1.0

        self.assertGreater(
            backtest.selection_score(stable),
            backtest.selection_score(risky),
        )


if __name__ == "__main__":
    unittest.main()
