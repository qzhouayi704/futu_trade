import unittest
from datetime import datetime, timezone
from unittest.mock import patch

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
        self.raw_rows = []
        self.candidate_lifecycle_rows = []

    def execute_query(self, query: str, params: tuple = ()) -> list:
        if "FROM v2_decision_events e WHERE" in query and "e.stock_code IN" in query:
            return [row[:8] for row in self.candidate_rows] + self.candidate_lifecycle_rows
        if "FROM v2_decision_events e LEFT JOIN v2_outcomes" in query:
            states = set(params[:-2])
            return [row for row in self.candidate_rows if row[6] in states]
        if "FROM v2_notification_log" in query:
            self.last_alert_params = params
            return self.alert_rows
        if "FROM kline_data" in query:
            return self.kline_rows
        if "FROM ticker_minute" in query:
            return self.ticker_rows
        if "WITH bounds" in query:
            return self.raw_rows
        if "FROM stocks" in query:
            return [("HK.00100", "测试买入"), ("HK.00200", "测试卖出")]
        raise AssertionError(f"unexpected query: {query}")


class AlertPerformanceReaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.clock = patch(
            "simple_trade.v2.application.read_models.alert_performance.market_now",
            return_value=datetime(2026, 9, 17, 2, tzinfo=timezone.utc),
        )
        self.mock_now = self.clock.start()
        self.addCleanup(self.clock.stop)

    async def test_tracks_trading_day_horizons_and_collapses_repeat_alerts(self) -> None:
        database = FakeAlertDatabase()
        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02", scope="alerts"
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual(database.last_alert_params, ("2026-09-01", "2026-09-03"))
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
        self.assertEqual(item["current_status"], "WATCHING")
        self.assertEqual(item["alert_permission"], "TRACKING")
        self.assertEqual(result["lifecycle_summary"]["current_status"], {"WATCHING": 1})
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
        self.assertEqual(item["same_day"]["status"], "PARTIAL")
        self.assertEqual(item["same_day"]["latest_return_pct"], 5.102)
        self.assertIsNone(item["same_day"]["close_return_pct"])
        self.assertEqual(result["summary"]["same_day"]["completed_count"], 0)
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

    async def test_last_raw_trade_is_not_mislabelled_as_a_settled_close(self) -> None:
        database = FakeAlertDatabase()
        database.candidate_rows = [database.candidate_rows[0]]
        database.kline_rows = []
        database.ticker_rows = [
            ("HK.00100", "15:59", 102, 104, 101),
        ]
        database.ticker_close_rows = [("HK.00100", 103)]
        database.raw_rows = [
            ("setup-1", 103, 104, 101, "2026-09-02 15:59:00", "2026-09-02 15:59:59", 3),
        ]

        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02"
        )

        same_day = result["items"][0]["same_day"]
        self.assertEqual(same_day["status"], "PARTIAL")
        self.assertIsNone(same_day["close_return_pct"])
        self.assertEqual(same_day["latest_return_pct"], 5.102)
        self.assertEqual(same_day["max_return_pct"], 6.1224)

    async def test_utc_alert_is_included_but_lunch_is_excluded(self) -> None:
        database = FakeAlertDatabase()
        row = list(database.alert_rows[0])
        row[3] = "2026-09-02T02:00:00+00:00"
        lunch = list(row)
        lunch[0], lunch[3] = "lunch", "2026-09-02T04:30:00+00:00"
        database.alert_rows = [tuple(row), tuple(lunch)]
        result = await AlertPerformanceReader(database).history(trade_date="2026-09-02", scope="alerts")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["signal_time"], "2026-09-02T10:00:00+08:00")
        self.assertEqual(result["excluded"]["by_reason"]["OUTSIDE_REGULAR_SESSION"], 1)

    async def test_live_raw_tape_is_visible_without_being_counted_as_a_close(self) -> None:
        self.mock_now.return_value = datetime(2026, 9, 2, 3, tzinfo=timezone.utc)
        database = FakeAlertDatabase()
        database.candidate_rows = [database.candidate_rows[0]]
        database.raw_rows = [("setup-1", 101, 103, 97, "2026-09-02 09:41:00", "2026-09-02 10:59:30", 4)]
        result = await AlertPerformanceReader(database).history(trade_date="2026-09-02")
        value = result["items"][0]["same_day"]
        self.assertEqual(value["status"], "LIVE")
        self.assertEqual(value["source"], "TICKER_DATA")
        self.assertEqual(value["latest_return_pct"], 3.0612)
        self.assertIsNone(value["close_return_pct"])
        self.assertFalse(value["is_stale"])
        self.assertEqual(value["lag_seconds"], 30)
        self.assertEqual(result["summary"]["same_day"]["completed_count"], 0)
        self.assertEqual(result["items"][0]["periods"]["1"]["status"], "PENDING")

    async def test_live_raw_tape_marks_an_intraday_subscription_gap(self) -> None:
        self.mock_now.return_value = datetime(2026, 9, 2, 6, tzinfo=timezone.utc)
        database = FakeAlertDatabase()
        database.candidate_rows = [database.candidate_rows[0]]
        database.raw_rows = [
            (
                "setup-1",
                101,
                103,
                97,
                "2026-09-02 09:41:00",
                "2026-09-02 13:50:00",
                4,
            )
        ]

        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02"
        )

        value = result["items"][0]["same_day"]
        self.assertTrue(value["is_stale"])
        self.assertEqual(value["lag_seconds"], 600)

    async def test_signal_minute_extremes_before_confirmation_are_not_used(self) -> None:
        database = FakeAlertDatabase()
        database.candidate_rows = [list(database.candidate_rows[0])]
        database.candidate_rows[0][3] = "2026-09-02T09:40:45+08:00"
        database.ticker_rows = [
            ("HK.00100", "09:40", 98, 130, 60),
            ("HK.00100", "09:41", 100, 101, 99),
        ]
        result = await AlertPerformanceReader(database).history(trade_date="2026-09-02")
        value = result["items"][0]["same_day"]
        self.assertEqual(value["max_return_pct"], 3.0612)
        self.assertEqual(value["max_drawdown_pct"], 1.0204)

    async def test_stage_upgrade_does_not_overwrite_original_outcome_basis(self) -> None:
        result = await AlertPerformanceReader(FakeAlertDatabase()).history(trade_date="2026-09-02")
        self.assertIsNone(result["items"][0]["intraday_mfe_pct"])
        self.assertIsNone(result["items"][0]["intraday_mae_pct"])

    async def test_candidate_lifecycle_exposes_later_invalidation(self) -> None:
        database = FakeAlertDatabase()
        database.candidate_lifecycle_rows.append((
            "invalid-1", "CANDIDATE_INVALIDATED", "HK.00100",
            "2026-09-02T14:30:00+08:00", "PRICE_ACCEPTANCE_BROKEN",
            "v2", "INVALIDATED",
            '{"alert_eligible":false,"strategy_portfolio":'
            '{"strategy_sources":["capital_absorption"]}}',
        ))

        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02", scope="candidates"
        )

        item = result["items"][0]
        self.assertEqual(item["entry_stage"], "SETUP")
        self.assertEqual(item["max_stage"], "WATCHING")
        self.assertEqual(item["current_status"], "INVALIDATED")
        self.assertEqual(item["current_reason_code"], "PRICE_ACCEPTANCE_BROKEN")
        self.assertEqual(item["current_state_time"], "2026-09-02T14:30:00+08:00")
        self.assertEqual(item["alert_permission"], "NONE")
        self.assertEqual(item["strategy_sources"], [])
        self.assertEqual(item["ever_strategy_sources"], ["capital_absorption"])
        self.assertEqual(item["current_strategy_sources"], ["capital_absorption"])
        self.assertEqual(result["lifecycle_summary"]["current_status"], {"INVALIDATED": 1})
        self.assertEqual(result["summary_by_strategy_source"], {})

    async def test_delivered_alert_has_delivery_permission(self) -> None:
        result = await AlertPerformanceReader(FakeAlertDatabase()).history(
            trade_date="2026-09-02", scope="alerts"
        )

        self.assertTrue(all(
            item["alert_permission"] == "DELIVERED" for item in result["items"]
        ))

    async def test_delivered_buy_keeps_history_but_shows_later_invalidation(self) -> None:
        database = FakeAlertDatabase()
        database.candidate_lifecycle_rows.extend([
            (
                "buy-1", "BUY_CONFIRMED", "HK.00100",
                "2026-09-02T10:00:00+08:00", "FAST_15M_MULTI_INFLOW_CONFIRMED",
                "v2", "CONFIRMED", '{"alert_eligible":true}',
            ),
            (
                "invalid-1", "BUY_INVALIDATED", "HK.00100",
                "2026-09-02T10:30:00+08:00", "PRICE_ACCEPTANCE_BROKEN",
                "v2", "INVALIDATED", '{"alert_eligible":false}',
            ),
        ])

        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02", scope="alerts"
        )

        buy = next(item for item in result["items"] if item["action"] == "BUY")
        self.assertEqual(buy["current_status"], "INVALIDATED")
        self.assertEqual(buy["current_reason_code"], "PRICE_ACCEPTANCE_BROKEN")
        self.assertEqual(buy["alert_permission"], "DELIVERED")
        self.assertEqual(buy["signal_price"], 100)
        self.assertEqual(buy["delivered_at"], "2026-09-02T10:00:02+08:00")

    async def test_strategy_summary_uses_only_sources_known_at_the_scope_basis(self) -> None:
        database = FakeAlertDatabase()
        row = list(database.candidate_rows[0])
        row[7] = (
            '{"alert_eligible":false,"feature_snapshot":{"quote":{"last_price":98}},'
            '"strategy_portfolio":{"strategy_sources":[],"nominations":['
            '{"strategy_id":"capital_absorption","stage":"WATCH"}]}}'
        )
        database.candidate_rows = [tuple(row)]

        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02", scope="candidates"
        )

        self.assertEqual(result["items"][0]["strategy_sources"], ["capital_absorption"])
        self.assertEqual(
            result["summary_by_strategy_source"]["capital_absorption"]["alert_count"],
            1,
        )

    async def test_lifecycle_strategy_source_is_included_in_performance(self) -> None:
        database = FakeAlertDatabase()
        row = list(database.candidate_rows[0])
        row[7] = (
            '{"alert_eligible":true,"feature_snapshot":{"quote":{"last_price":98}},'
            '"strategy_portfolio":{"strategy_sources":[]},'
            '"lifecycle_strategy_source":"post_invalidation_flow_recovery"}'
        )
        database.candidate_rows = [tuple(row)]

        result = await AlertPerformanceReader(database).history(
            trade_date="2026-09-02", scope="candidates"
        )

        self.assertEqual(
            result["items"][0]["strategy_sources"],
            ["post_invalidation_flow_recovery"],
        )


if __name__ == "__main__":
    unittest.main()
