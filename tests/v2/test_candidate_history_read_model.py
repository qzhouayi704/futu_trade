import json
import sqlite3
import unittest

from simple_trade.v2.application.read_models.service import V2ReadModelService


class SqliteReadDatabase:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.executescript(
            """
            CREATE TABLE stocks (code TEXT PRIMARY KEY, name TEXT);
            CREATE TABLE v2_decision_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT,
                event_type TEXT,
                stock_code TEXT,
                exchange_time TEXT,
                old_state TEXT,
                new_state TEXT,
                reason_code TEXT,
                payload_json TEXT,
                strategy_version TEXT
            );
            """
        )
        self.connection.executemany(
            "INSERT INTO stocks(code,name) VALUES (?,?)",
            (("HK.00100", "测试科技"), ("HK.00200", "普通股票")),
        )

    def execute_query(self, query: str, params: tuple | None = None) -> list:
        return self.connection.execute(query, params or ()).fetchall()

    def event(
        self,
        stock_code: str,
        event_type: str,
        exchange_time: str,
        old_state: str,
        new_state: str,
        reason: str,
        score: float,
        version: str,
    ) -> None:
        payload = json.dumps({
            "candidate_score": {"total": score},
            "feature_snapshot": {
                "quote": {"last_price": 10.5, "prev_close": 10},
                "capital_memory": {"state": "ACCUMULATING", "day_main_net": 1_000_000},
            },
        })
        self.connection.execute(
            "INSERT INTO v2_decision_events "
            "(event_id,event_type,stock_code,exchange_time,old_state,new_state,"
            "reason_code,payload_json,strategy_version) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{stock_code}-{exchange_time}", event_type, stock_code, exchange_time,
             old_state, new_state, reason, payload, version),
        )
        self.connection.commit()


class CandidateHistoryReadModelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = SqliteReadDatabase()
        self.database.event(
            "HK.00100", "CANDIDATE_ENTERED", "2026-09-02T09:30:00+08:00",
            "SETUP", "WATCHING", "FIRST_STRONG_INFLOW_WATCH", 72, "strategy-old",
        )
        self.database.event(
            "HK.00100", "CANDIDATE_INVALIDATED", "2026-09-02T10:30:00+08:00",
            "WATCHING", "INVALIDATED", "PRICE_ACCEPTANCE_BROKEN", 61, "strategy-new",
        )
        self.database.event(
            "HK.00200", "CANDIDATE_REJECTED", "2026-09-02T10:40:00+08:00",
            "IDLE", "IDLE", "TURNOVER_RANK_NOT_HOT", 35, "strategy-new",
        )
        self.service = V2ReadModelService(self.database)

    async def test_entered_scope_groups_stock_across_strategy_versions(self) -> None:
        result = await self.service.candidate_history(
            trade_date="2026-09-02", scope="entered", page=1, page_size=50
        )

        self.assertEqual(result["total"], 1)
        item = result["items"][0]
        self.assertEqual(item["stock_code"], "HK.00100")
        self.assertEqual(item["event_count"], 2)
        self.assertEqual(item["strategy_version_count"], 2)
        self.assertEqual(item["max_stage"], "WATCHING")
        self.assertEqual(item["latest_score"], 61)
        self.assertEqual(item["latest_status"], "INVALIDATED")

    async def test_all_scope_includes_rejected_only_stocks_and_filters(self) -> None:
        all_items = await self.service.candidate_history(
            trade_date="2026-09-02", scope="all", page=1, page_size=50
        )
        rejected = await self.service.candidate_history(
            trade_date="2026-09-02", scope="all", status="IDLE",
            search="普通", page=1, page_size=50,
        )

        self.assertEqual(all_items["total"], 2)
        self.assertEqual(rejected["total"], 1)
        self.assertEqual(rejected["items"][0]["stock_code"], "HK.00200")

    async def test_timeline_keeps_cross_version_order(self) -> None:
        result = await self.service.candidate_timeline(
            "hk.00100", trade_date="2026-09-02"
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual(
            [item["strategy_version"] for item in result["items"]],
            ["strategy-old", "strategy-new"],
        )


if __name__ == "__main__":
    unittest.main()
