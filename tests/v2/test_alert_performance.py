import unittest

from simple_trade.v2.application.read_models.alert_performance import (
    AlertPerformanceReader,
)


class FakeAlertDatabase:
    def __init__(self) -> None:
        self.candidate_rows = [
            (
                "setup-1", "CANDIDATE_ENTERED", "HK.00100",
                "2026-09-02T09:40:00+08:00", "LOW_POSITION_SETUP",
                "v2", "SETUP",
                '{"feature_snapshot":{"quote":{"last_price":98}}}',
                None, None, None,
            ),
            (
                "watch-1", "CANDIDATE_UPDATED", "HK.00100",
                "2026-09-02T10:05:00+08:00", "FAST_15M_MULTI_INFLOW_WATCHING",
                "v2", "WATCHING",
                '{"feature_snapshot":{"quote":{"last_price":100}}}',
                2.5, -1.0, 1.0,
            ),
        ]
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
        self.ticker_rows = []
        self.ticker_close_rows = []

    def execute_query(self, query: str, params: tuple = ()) -> list:
        if "FROM v2_decision_events e LEFT JOIN v2_outcomes" in query:
            states = set(params[:-1])
            return [row for row in self.candidate_rows if row[6] in states]
        if "FROM v2_notification_log" in query:
            self.last_alert_params = params
            return self.alert_rows
        if "FROM kline_data" in query:
            return self.kline_rows
        if "FROM ticker_minute" in query:
            return self.ticker_rows
        if "FROM ticker_data" in query:
            return self.ticker_close_rows
        if "FROM stocks" in query:
            return [("HK.00100", "测试买入"), ("HK.00200", "测试卖出")]
        raise AssertionError(f"unexpected query: {query}")


class AlertPerformanceReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_tracks_trading_day_horizons_and_collapses_repeat_alerts(self) -> None:
        database = FakeAlertDatabase()
        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02", scope="alerts"
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
            trade_date="2026-09-02", scope="alerts"
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
            trade_date="2026-09-01", scope="alerts"
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
            trade_date="2026-09-02", scope="alerts"
        )

        item = result["items"][0]
        self.assertEqual(item["same_day"]["close_return_pct"], 1)
        self.assertEqual(item["periods"]["1"]["close_return_pct"], 3)

    async def test_candidates_use_first_stage_price_and_merge_stage_upgrades(self) -> None:
        result = await AlertPerformanceReader(FakeAlertDatabase()).history(
            trade_date="2026-09-02"
        )

        self.assertEqual(result["scope"], "candidates")
        self.assertEqual(result["count"], 1)
        item = result["items"][0]
        self.assertEqual(item["action"], "CANDIDATE")
        self.assertEqual(item["signal_price"], 98)
        self.assertEqual(item["entry_stage"], "SETUP")
        self.assertEqual(item["max_stage"], "WATCHING")
        self.assertEqual(item["alert_count"], 2)
        self.assertEqual(item["stage_points"]["SETUP"]["price"], 98)
        self.assertEqual(item["stage_points"]["WATCHING"]["price"], 100)
        self.assertEqual(item["same_day"]["source"], "DAILY_KLINE")
        self.assertEqual(item["same_day"]["close_return_pct"], 3.0612)

    async def test_watching_scope_starts_at_first_fund_confirmation(self) -> None:
        result = await AlertPerformanceReader(FakeAlertDatabase()).history(
            trade_date="2026-09-02", scope="watching"
        )

        item = result["items"][0]
        self.assertEqual(result["scope"], "watching")
        self.assertEqual(item["signal_price"], 100)
        self.assertEqual(item["entry_stage"], "WATCHING")
        self.assertEqual(item["max_stage"], "WATCHING")
        self.assertEqual(item["alert_count"], 1)

    async def test_confirmed_scope_uses_actual_confirmation_price_and_time(self) -> None:
        database = FakeAlertDatabase()
        database.candidate_rows.append((
            "confirmed-1", "BUY_CONFIRMED", "HK.00100",
            "2026-09-02T10:30:00+08:00", "FAST_15M_MULTI_INFLOW_CONFIRMED",
            "v2", "CONFIRMED",
            '{"feature_snapshot":{"quote":{"last_price":102}}}',
            1.5, -0.5, 0.2,
        ))

        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02", scope="confirmed"
        )

        self.assertEqual(result["count"], 1)
        item = result["items"][0]
        self.assertEqual(item["signal_price"], 102)
        self.assertEqual(item["signal_time"], "2026-09-02T10:30:00+08:00")
        self.assertEqual(item["entry_stage"], "CONFIRMED")
        self.assertEqual(item["stage_points"]["CONFIRMED"]["price"], 102)

    async def test_same_stock_from_different_strategy_versions_is_not_merged(self) -> None:
        database = FakeAlertDatabase()
        database.candidate_rows.append((
            "setup-v3", "CANDIDATE_ENTERED", "HK.00100",
            "2026-09-02T09:45:00+08:00", "LOW_POSITION_SETUP",
            "v3", "SETUP",
            '{"feature_snapshot":{"quote":{"last_price":99}}}',
            None, None, None,
        ))

        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02", scope="candidates"
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual(set(result["summary_by_strategy_version"]), {"v2", "v3"})

    async def test_formal_alerts_exclude_rejected_and_after_hours_records(self) -> None:
        database = FakeAlertDatabase()
        database.alert_rows.extend([
            (
                "rejected", "BUY_CONFIRMED", "HK.00300",
                "2026-09-02T11:00:00+08:00", "CONFIRMED", "v2",
                "BUY", "REJECTED",
                '{"stock_code":"HK.00300","reference_price":20}', None,
                "2026-09-02T11:00:01+08:00", None, None, None,
            ),
            (
                "after-hours", "EXIT_RISK_CONFIRMED", "HK.00400",
                "2026-09-02T16:25:00+08:00", "TAKE_PROFIT_5_PCT", "v2",
                "SELL", "APPROVED", None,
                '{"stock_code":"HK.00400","reference_price":30}',
                "2026-09-02T16:25:01+08:00", None, None, None,
            ),
        ])

        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02", scope="alerts"
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["excluded"]["total"], 2)
        self.assertEqual(result["excluded"]["by_reason"]["RISK_NOT_APPROVED"], 1)
        self.assertEqual(
            result["excluded"]["by_reason"]["OUTSIDE_REGULAR_SESSION"], 1
        )

    async def test_invalid_scope_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "复盘范围"):
            await AlertPerformanceReader(FakeAlertDatabase()).history(
                trade_date="2026-09-02", scope="rejected"
            )

    async def test_uses_post_signal_ticker_minutes_when_daily_kline_is_missing(self) -> None:
        database = FakeAlertDatabase()
        database.candidate_rows = [database.candidate_rows[0]]
        database.kline_rows = []
        database.ticker_rows = [
            ("HK.00100", "09:39", 120, 121, 119),
            ("HK.00100", "09:40", 98, 99, 97),
            ("HK.00100", "10:05", 101, 102, 100),
            ("HK.00100", "15:59", 103, 104, 102),
        ]
        database.ticker_close_rows = [("HK.00100", 103)]

        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02"
        )

        item = result["items"][0]
        self.assertEqual(result["intraday_coverage_count"], 1)
        self.assertEqual(item["same_day"]["source"], "TICKER_MINUTE")
        self.assertEqual(item["same_day"]["close_return_pct"], 5.102)
        self.assertEqual(item["same_day"]["max_return_pct"], 6.1224)
        self.assertEqual(item["same_day"]["max_drawdown_pct"], -1.0204)

    async def test_does_not_use_pre_signal_trade_as_post_signal_performance(self) -> None:
        database = FakeAlertDatabase()
        database.candidate_rows = [database.candidate_rows[0]]
        database.kline_rows = []
        database.ticker_rows = [
            ("HK.00100", "09:39", 97, 97, 97),
        ]
        database.ticker_close_rows = [("HK.00100", 97)]

        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02"
        )

        same_day = result["items"][0]["same_day"]
        self.assertEqual(same_day["status"], "OBSERVING")
        self.assertIsNone(same_day["source"])
        self.assertIsNone(same_day["close_return_pct"])
        self.assertIsNone(same_day["max_return_pct"])
        self.assertIsNone(same_day["max_drawdown_pct"])
        self.assertFalse(same_day["intraday_covered"])

    async def test_uses_last_raw_trade_instead_of_last_minute_average_for_close(self) -> None:
        database = FakeAlertDatabase()
        database.candidate_rows = [database.candidate_rows[0]]
        database.kline_rows = []
        database.ticker_rows = [
            ("HK.00100", "15:59", 102, 104, 101),
        ]
        database.ticker_close_rows = [("HK.00100", 103)]

        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02"
        )

        same_day = result["items"][0]["same_day"]
        self.assertEqual(same_day["close_return_pct"], 5.102)
        self.assertEqual(same_day["max_return_pct"], 6.1224)


if __name__ == "__main__":
    unittest.main()
