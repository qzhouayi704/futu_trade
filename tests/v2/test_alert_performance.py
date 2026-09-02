import unittest

from simple_trade.v2.application.read_models.alert_performance import (
    AlertPerformanceReader,
)


class FakeAlertDatabase:
    def __init__(self) -> None:
        self.alert_rows = [
            (
                "buy-1", "BUY_CONFIRMED", "HK.00100",
                "2026-09-02T10:00:00+08:00", "FAST_15M_MULTI_INFLOW_CONFIRMED",
                "v2", "BUY", "APPROVED",
                '{"stock_code":"HK.00100","reference_price":100}', None,
                "2026-09-02T10:00:02+08:00", 2.5, -1.0, 1.0,
            ),
            (
                "buy-2", "BUY_CONFIRMED", "HK.00100",
                "2026-09-02T10:20:00+08:00", "FAST_15M_MULTI_INFLOW_CONFIRMED",
                "v2", "BUY", "APPROVED",
                '{"stock_code":"HK.00100","reference_price":101}', None,
                "2026-09-02T10:20:02+08:00", 1.5, -0.5, 0.5,
            ),
            (
                "sell-1", "EXIT_RISK_CONFIRMED", "HK.00200",
                "2026-09-02T14:00:00+08:00", "REPEATED_OUTFLOW_AND_STRUCTURE_BREAK",
                "v2", "SELL", "APPROVED", None,
                '{"stock_code":"HK.00200","reference_price":50}',
                "2026-09-02T14:00:02+08:00", None, None, None,
            ),
        ]
        days = [
            "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-07",
            "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
            "2026-09-14", "2026-09-15", "2026-09-16",
        ]
        self.kline_rows = []
        for index, day in enumerate(days):
            buy_close = 101 + index
            self.kline_rows.append(
                ("HK.00100", day, buy_close, buy_close + 2, buy_close - 2)
            )
        self.kline_rows.extend([
            ("HK.00200", "2026-09-02", 49, 51, 48),
            ("HK.00200", "2026-09-03", 45, 52, 44),
        ])

    def execute_query(self, query: str, params: tuple = ()) -> list:
        if "FROM v2_notification_log" in query:
            self.last_alert_params = params
            return self.alert_rows
        if "FROM kline_data" in query:
            return self.kline_rows
        if "FROM stocks" in query:
            return [("HK.00100", "测试买入"), ("HK.00200", "测试卖出")]
        raise AssertionError(f"unexpected query: {query}")


class AlertPerformanceReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_tracks_trading_day_horizons_and_collapses_repeat_alerts(self) -> None:
        database = FakeAlertDatabase()
        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02"
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual(database.last_alert_params, ("2026-09-02",))
        buy = next(item for item in result["items"] if item["action"] == "BUY")
        self.assertEqual(buy["alert_count"], 2)
        self.assertEqual(buy["signal_price"], 100)
        self.assertEqual(buy["same_day"]["close_return_pct"], 1)
        self.assertEqual(buy["periods"]["1"]["trading_day"], "2026-09-03")
        self.assertEqual(buy["periods"]["1"]["close_return_pct"], 2)
        self.assertEqual(buy["periods"]["1"]["max_return_pct"], 4)
        self.assertEqual(buy["periods"]["3"]["trading_day"], "2026-09-07")
        self.assertEqual(buy["periods"]["10"]["status"], "READY")

    async def test_sell_direction_treats_post_alert_decline_as_profit(self) -> None:
        result = await AlertPerformanceReader(FakeAlertDatabase()).history(
            trade_date="2026-09-02"
        )
        sell = next(item for item in result["items"] if item["action"] == "SELL")

        self.assertEqual(sell["same_day"]["close_return_pct"], 2)
        self.assertEqual(sell["periods"]["1"]["close_return_pct"], 10)
        self.assertEqual(sell["periods"]["1"]["max_return_pct"], 12)
        self.assertEqual(sell["periods"]["1"]["max_drawdown_pct"], -4)
        self.assertEqual(sell["periods"]["3"]["status"], "PENDING")

    async def test_empty_day_and_invalid_date_are_explicit(self) -> None:
        database = FakeAlertDatabase()
        database.alert_rows = []
        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-01"
        )
        self.assertEqual(result["items"], [])
        self.assertIsNone(result["summary"]["periods"]["1"]["win_ratio"])

        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            await AlertPerformanceReader(database).history(trade_date="2026/09/01")

    async def test_rebases_adjusted_klines_to_the_observed_signal_day_close(self) -> None:
        database = FakeAlertDatabase()
        database.alert_rows = [database.alert_rows[0]]
        database.kline_rows = [
            ("HK.00100", "2026-09-02", 50.5, 51, 50),
            ("HK.00100", "2026-09-03", 51.5, 52, 50.5),
        ]
        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02"
        )

        item = result["items"][0]
        self.assertEqual(item["same_day"]["close_return_pct"], 1)
        self.assertEqual(item["periods"]["1"]["close_return_pct"], 3)


if __name__ == "__main__":
    unittest.main()
