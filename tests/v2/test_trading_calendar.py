import unittest
from datetime import date, datetime

from simple_trade.utils.trading_calendar import TradingCalendar


class TradingCalendarKnownWindowTests(unittest.TestCase):
    @staticmethod
    def _calendar() -> TradingCalendar:
        calendar = TradingCalendar()
        calendar._cache["HK"] = {
            "2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08",
        }
        calendar._window["HK"] = ("2026-09-01", "2026-09-10")
        calendar._built_on["HK"] = datetime.now().date().isoformat()
        return calendar

    def test_returns_only_known_sessions_in_requested_range(self) -> None:
        result = self._calendar().known_trading_days(
            "HK", date(2026, 9, 3), date(2026, 9, 8)
        )

        self.assertEqual(
            result,
            ("2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08"),
        )

    def test_returns_unknown_when_request_exceeds_cached_window(self) -> None:
        result = self._calendar().known_trading_days(
            "HK", date(2026, 8, 31), date(2026, 9, 8)
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
