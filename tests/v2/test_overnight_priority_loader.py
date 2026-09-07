import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from simple_trade.v2.infrastructure.overnight_priority_loader import (
    CalendarUnavailableError, OvernightPriorityLoader,
)
from simple_trade.v2.domain.candidates import OvernightStatus
from simple_trade.v2.infrastructure.db_read import SqliteReadDatabase


HK = timezone(timedelta(hours=8))


class FixedCalendar:
    def __init__(self, days=None):
        self.days = days if days is not None else (
            "2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
            "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
            "2026-09-14", "2026-09-15", "2026-09-16",
        )

    def known_trading_days(self, *args, **kwargs):
        return self.days


def loader(db, *, calendar=None):
    return OvernightPriorityLoader(db, calendar=calendar or FixedCalendar())


def payload(*, score=72, state="ACCUMULATING", day_net=5_000_000):
    return json.dumps({
        "candidate_score": {"total": score},
        "feature_snapshot": {
            "quote": {"last_price": 100},
            "price_position": {
                "daily_percentile": 0.45,
                "atr_percent": 4,
                "distance_to_ma20": 4,
            },
            "capital_memory": {
                "state": state,
                "score": 82,
                "day_main_net": day_net,
                "decayed_main_net": 3_000_000,
                "recent_15m_buy_events": 3,
            },
            "market_context": {"market_breadth": 0.55, "market_sample_size": 80},
            "activity": {"is_active": True},
            "liquidity": {"score": 80},
            "tick_windows": [{"independent_buy_events": 3}],
        },
    })


class FakeDatabase:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def execute_query(self, query, params=None):
        self.queries.append((query, params))
        return [row if len(row) == 8 else (*row, f"event-{index}", row[1], "v2") for index, row in enumerate(self.rows)]


class OvernightPriorityLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_loads_engaged_positive_flow_candidate(self):
        rows = [(
            "HK.00100",
            "2026-09-03T14:10:00+08:00",
            "WATCHING",
            "CAPITAL_MEMORY_REVERSAL_WATCH",
            payload(),
        )]

        database = FakeDatabase(rows)
        result = await loader(database).load(
            datetime(2026, 9, 4, 8, 0, tzinfo=HK)
        )

        self.assertEqual([item.stock_code for item in result], ["HK.00100"])
        self.assertEqual(result[0].source_date, "2026-09-03")
        self.assertEqual(result[0].independent_buy_events, 3)
        self.assertNotIn("substr(", database.queries[0][0])
        self.assertEqual(database.queries[0][1][-2:], ("2026-09-05", 30_001))
        self.assertEqual(result[0].age_sessions, 1)
        self.assertEqual(result[0].expires_date, "2026-09-08")

    async def test_late_outflow_removes_priority(self):
        rows = [
            (
                "HK.00100", "2026-09-03T14:10:00+08:00", "WATCHING",
                "CAPITAL_MEMORY_REVERSAL_WATCH", payload(),
            ),
            (
                "HK.00100", "2026-09-03T14:40:00+08:00", "INVALIDATED",
                "LARGE_OUTFLOW_OFFSETS_INFLOW",
                payload(state="DISTRIBUTING", day_net=-1_000_000),
            ),
        ]

        result = await loader(FakeDatabase(rows)).load(
            datetime(2026, 9, 4, 8, 0, tzinfo=HK)
        )

        self.assertEqual(result, ())

    async def test_rejects_unengaged_raw_snapshot(self):
        rows = [(
            "HK.00100",
            "2026-09-03T14:10:00+08:00",
            "IDLE",
            "TURNOVER_RANK_NOT_HOT",
            payload(),
        )]

        result = await loader(FakeDatabase(rows)).load(
            datetime(2026, 9, 4, 8, 0, tzinfo=HK)
        )

        self.assertEqual(result, ())

    async def test_latest_recovery_supersedes_earlier_higher_score(self):
        rows = [
            ("HK.00100", "2026-09-03T14:10:00+08:00", "WATCHING", "FLOW_WATCH", payload(score=85)),
            ("HK.00100", "2026-09-03T14:40:00+08:00", "INVALIDATED",
             "LARGE_OUTFLOW_OFFSETS_INFLOW", payload(state="DISTRIBUTING", day_net=-1_000_000)),
            ("HK.00100", "2026-09-03T07:10:00Z", "WATCHING", "FLOW_RECOVERED", payload(score=70)),
        ]
        result = await loader(FakeDatabase(list(reversed(rows)))).load(
            datetime(2026, 9, 4, 8, tzinfo=HK)
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].score, 70)
        self.assertEqual(result[0].source_time.hour, 15)
        self.assertEqual(result[0].source_reason, "FLOW_RECOVERED")

    async def test_structure_break_cannot_qualify_using_positive_snapshot(self):
        for reason in ("PRICE_ACCEPTANCE_BROKEN", "LARGE_OUTFLOW_OFFSETS_INFLOW"):
            with self.subTest(reason=reason):
                rows = [
                    ("HK.00100", "2026-09-03T14:10:00+08:00", "WATCHING", "FLOW_WATCH", payload()),
                    ("HK.00100", "2026-09-03T15:00:00+08:00", "INVALIDATED", reason, payload(score=90)),
                ]
                result = await loader(FakeDatabase(rows)).load(
                    datetime(2026, 9, 4, 8, tzinfo=HK)
                )
                self.assertEqual(result, ())

    async def test_recovery_below_existing_threshold_is_not_promoted(self):
        rows = [
            ("HK.00100", "2026-09-03T14:10:00+08:00", "WATCHING", "FLOW_WATCH", payload()),
            ("HK.00100", "2026-09-03T14:40:00+08:00", "INVALIDATED", "PRICE_ACCEPTANCE_BROKEN", payload()),
            ("HK.00100", "2026-09-03T15:00:00+08:00", "WATCHING", "FLOW_RECOVERED", payload(score=62.76)),
        ]
        result = await loader(FakeDatabase(rows)).load(datetime(2026, 9, 4, 8, tzinfo=HK))
        self.assertEqual(result, ())

    async def test_weekend_does_not_consume_observation_sessions(self):
        subject = loader(FakeDatabase([
            ("HK.00100", "2026-09-03T14:10:00+08:00", "WATCHING", "FLOW_WATCH", payload()),
        ]))
        result = await subject.load(datetime(2026, 9, 7, 8, tzinfo=HK))
        self.assertEqual(result[0].age_sessions, 2)
        self.assertEqual(result[0].expires_date, "2026-09-08")
        self.assertTrue(result[0].is_valid_on("2026-09-07"))
        self.assertFalse(result[0].is_valid_on("2026-09-08"))

    async def test_fourth_session_expires_and_derived_watch_cannot_renew(self):
        subject = loader(FakeDatabase([
            ("HK.00100", "2026-09-02T14:00:00+08:00", "WATCHING", "FLOW_WATCH", payload()),
            ("HK.00100", "2026-09-07T10:00:00+08:00", "WATCHING", "OVERNIGHT_PRIORITY_LOW_WATCH", payload(score=90)),
        ]))
        result = await subject.load(datetime(2026, 9, 8, 8, tzinfo=HK))
        self.assertEqual(result, ())
        self.assertEqual(subject.observations[0].status, OvernightStatus.EXPIRED)
        self.assertEqual(subject.observations[0].priority.source_date, "2026-09-02")

    async def test_intermediate_day_break_is_not_resurrected_by_later_watch(self):
        subject = loader(FakeDatabase([
            ("HK.00100", "2026-09-03T14:00:00+08:00", "WATCHING", "FLOW_WATCH", payload()),
            ("HK.00100", "2026-09-04T10:00:00+08:00", "INVALIDATED", "PRICE_ACCEPTANCE_BROKEN", payload()),
            ("HK.00100", "2026-09-04T11:00:00+08:00", "WATCHING", "OVERNIGHT_PRIORITY_LOW_WATCH", payload(score=90)),
        ]))
        self.assertEqual(await subject.load(datetime(2026, 9, 7, 8, tzinfo=HK)), ())
        self.assertEqual(subject.observations[0].status, OvernightStatus.INVALIDATED)

    async def test_confirmation_timeout_is_suspended_not_permanently_removed(self):
        subject = loader(FakeDatabase([
            ("HK.00100", "2026-09-03T14:00:00+08:00", "WATCHING", "FLOW_WATCH", payload()),
            ("HK.00100", "2026-09-04T11:00:00+08:00", "INVALIDATED", "FLOW_CONFIRMATION_EXPIRED", payload()),
        ]))
        self.assertEqual(len(await subject.load(datetime(2026, 9, 7, 8, tzinfo=HK))), 1)
        self.assertEqual(subject.observations[0].status, OvernightStatus.SUSPENDED)

    async def test_future_or_not_yet_received_events_cannot_change_selection(self):
        subject = loader(FakeDatabase([
            ("HK.00100", "2026-09-03T14:00:00+08:00", "WATCHING", "FLOW_WATCH", payload()),
            ("HK.00100", "2026-09-04T14:00:00+08:00", "INVALIDATED", "PRICE_ACCEPTANCE_BROKEN", payload()),
            ("HK.00100", "2026-09-03T15:00:00+08:00", "INVALIDATED", "PRICE_ACCEPTANCE_BROKEN", payload(),
             "late", "2026-09-04T14:01:00+08:00", "v2"),
        ]))
        result = await subject.load(datetime(2026, 9, 4, 8, tzinfo=HK))
        self.assertEqual(len(result), 1)

    async def test_known_holiday_does_not_consume_lifetime(self):
        days = ("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07")
        subject = loader(FakeDatabase([
            ("HK.00100", "2026-09-29T14:00:00+08:00", "WATCHING", "FLOW_WATCH", payload()),
        ]), calendar=FixedCalendar(days))
        result = await subject.load(datetime(2026, 10, 2, 8, tzinfo=HK))
        self.assertEqual(result[0].age_sessions, 2)
        self.assertEqual(result[0].expires_date, "2026-10-05")

    async def test_unknown_calendar_is_not_an_empty_successful_pool(self):
        with self.assertRaises(CalendarUnavailableError):
            await OvernightPriorityLoader(FakeDatabase([])).load(datetime(2026, 9, 4, 8, tzinfo=HK))

    async def test_missing_event_day_still_counts_as_a_trading_day(self):
        subject = loader(FakeDatabase([
            ("HK.00100", "2026-09-02T14:00:00+08:00", "WATCHING", "FLOW_WATCH", payload()),
        ]))
        result = await subject.load(datetime(2026, 9, 7, 8, tzinfo=HK))
        self.assertEqual(result[0].age_sessions, 3)

    async def test_compact_evidence_query_runs_against_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overnight.db"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE v2_decision_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, stock_code TEXT, exchange_time TEXT, "
                "new_state TEXT, reason_code TEXT, payload_json TEXT, event_id TEXT, "
                "received_time TEXT, strategy_version TEXT, source TEXT)"
            )
            connection.execute(
                "INSERT INTO v2_decision_events "
                "(stock_code, exchange_time, new_state, reason_code, payload_json, event_id, "
                "received_time, strategy_version, source) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "HK.00100", "2026-09-03T14:10:00+08:00", "WATCHING",
                    "CAPITAL_MEMORY_REVERSAL_WATCH", payload(), "event-real-sqlite",
                    "2026-09-03T14:10:01+08:00", "test-v2", OvernightPriorityLoader.SOURCE,
                ),
            )
            connection.commit()
            connection.close()

            subject = OvernightPriorityLoader(
                SqliteReadDatabase(path),
                calendar=FixedCalendar(),
                strategy_version="test-v2",
            )
            result = await subject.load(datetime(2026, 9, 4, 8, tzinfo=HK))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].setup_id, "event-real-sqlite")
        self.assertEqual(result[0].independent_buy_events, 3)


if __name__ == "__main__":
    unittest.main()
