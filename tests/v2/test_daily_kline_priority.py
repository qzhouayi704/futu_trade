import unittest

from simple_trade.services.market_data.kline.daily_kline_updater import (
    DailyKlineUpdater,
)


class DailyKlinePriorityTests(unittest.TestCase):
    def test_candidates_and_positions_are_updated_before_market_expansion(self) -> None:
        codes = {"US.AAPL", "HK.00700", "HK.00100", "SH.600000"}

        result = DailyKlineUpdater._sort_target_codes(codes, {"HK.00100"})

        self.assertEqual(result[0], "HK.00100")
        self.assertEqual(result[1:], ["HK.00700", "SH.600000", "US.AAPL"])


if __name__ == "__main__":
    unittest.main()
