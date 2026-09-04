import json
import unittest
from datetime import datetime, timedelta, timezone

from simple_trade.v2.infrastructure.overnight_priority_loader import (
    OvernightPriorityLoader,
)


HK = timezone(timedelta(hours=8))


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
        if "ORDER BY exchange_time DESC LIMIT 1" in query:
            return [("2026-09-03T15:59:00+08:00",)]
        return self.rows


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
        result = await OvernightPriorityLoader(database).load(
            datetime(2026, 9, 4, 8, 0, tzinfo=HK)
        )

        self.assertEqual([item.stock_code for item in result], ["HK.00100"])
        self.assertEqual(result[0].source_date, "2026-09-03")
        self.assertEqual(result[0].independent_buy_events, 3)
        self.assertNotIn("substr(", database.queries[0][0])
        self.assertEqual(
            database.queries[1][1],
            ("v2.candidate-coordinator", "2026-09-03", "2026-09-04"),
        )

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

        result = await OvernightPriorityLoader(FakeDatabase(rows)).load(
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

        result = await OvernightPriorityLoader(FakeDatabase(rows)).load(
            datetime(2026, 9, 4, 8, 0, tzinfo=HK)
        )

        self.assertEqual(result, ())


if __name__ == "__main__":
    unittest.main()
