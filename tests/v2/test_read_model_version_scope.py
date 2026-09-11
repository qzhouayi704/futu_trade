import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from simple_trade.v2.application.read_models.service import V2ReadModelService


NOW = datetime(2026, 9, 11, 10, tzinfo=timezone(timedelta(hours=8)))


class RecordingDatabase:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def execute_query(self, query: str, params: tuple | None = None) -> list:
        self.calls.append((query, params or ()))
        return []


class CandidateDatabase:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.executescript(
            """
            CREATE TABLE stocks (code TEXT PRIMARY KEY, name TEXT);
            CREATE TABLE v2_strategy_states (
                stock_code TEXT,
                strategy_version TEXT,
                status TEXT,
                version INTEGER,
                last_event_id TEXT,
                confirmed_price REAL,
                peak_price REAL,
                updated_at TEXT,
                metadata_json TEXT
            );
            CREATE TABLE v2_decision_events (
                event_id TEXT,
                reason_code TEXT,
                payload_json TEXT,
                exchange_time TEXT
            );
            """
        )

    def execute_query(self, query: str, params: tuple | None = None) -> list:
        return self.connection.execute(query, params or ()).fetchall()

    def candidate(
        self,
        code: str,
        updated_at: str,
        payload: dict | None = None,
    ) -> None:
        event_id = f"event-{code}"
        self.connection.execute("INSERT INTO stocks VALUES (?, ?)", (code, code))
        self.connection.execute(
            "INSERT INTO v2_decision_events VALUES (?, ?, ?, ?)",
            (
                event_id,
                "TEST_CONFIRMED",
                json.dumps(payload or {"candidate_score": {"total": 70}}),
                updated_at,
            ),
        )
        self.connection.execute(
            "INSERT INTO v2_strategy_states VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                code,
                "capital-flow-v2-current",
                "CONFIRMED",
                1,
                event_id,
                10,
                11,
                updated_at,
                "{}",
            ),
        )
        self.connection.commit()


class ReadModelVersionScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidates_exclude_previous_session_states(self) -> None:
        database = CandidateDatabase()
        database.candidate("HK.00100", "2026-09-10T15:00:00+08:00")
        database.candidate("HK.00200", "2026-09-11T09:35:00+08:00")
        runtime = SimpleNamespace(
            config=SimpleNamespace(strategy_version="capital-flow-v2-current")
        )
        service = V2ReadModelService(database, runtime, now_provider=lambda: NOW)

        result = await service.candidates(limit=50)

        self.assertEqual(result["trade_date"], "2026-09-11")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["stock_code"], "HK.00200")

    async def test_candidates_are_scoped_to_runtime_strategy_version(self) -> None:
        database = RecordingDatabase()
        runtime = SimpleNamespace(
            config=SimpleNamespace(strategy_version="capital-flow-v2-current")
        )
        service = V2ReadModelService(database, runtime, now_provider=lambda: NOW)

        await service.candidates(limit=12, stock_code="hk.00522")

        query, params = database.calls[-1]
        self.assertIn("s.strategy_version=?", query)
        self.assertIn("s.stock_code=?", query)
        self.assertEqual(
            params,
            (
                "capital-flow-v2-current",
                "HK.00522",
                "2026-09-11",
                "2026-09-12",
                12,
            ),
        )
        self.assertIn("s.updated_at>=? AND s.updated_at<?", query)

    async def test_candidates_include_lifecycle_strategy_source(self) -> None:
        database = CandidateDatabase()
        database.candidate(
            "HK.02685",
            "2026-09-11T09:39:00+08:00",
            {
                "candidate_score": {"total": 72},
                "strategy_portfolio": {
                    "strategy_sources": [],
                    "consensus_count": 0,
                },
                "lifecycle_strategy_source": "post_invalidation_flow_recovery",
            },
        )
        runtime = SimpleNamespace(
            config=SimpleNamespace(strategy_version="capital-flow-v2-current")
        )
        service = V2ReadModelService(database, runtime, now_provider=lambda: NOW)

        result = await service.candidates(limit=50)

        self.assertEqual(
            result["items"][0]["strategy_sources"],
            ["post_invalidation_flow_recovery"],
        )
        self.assertEqual(result["items"][0]["consensus_count"], 1)

    async def test_positions_are_scoped_to_runtime_strategy_version(self) -> None:
        database = RecordingDatabase()
        runtime = SimpleNamespace(
            config=SimpleNamespace(strategy_version="capital-flow-v2-current")
        )
        service = V2ReadModelService(database, runtime)

        await service.positions()

        query, params = database.calls[-1]
        self.assertIn("p.strategy_version=?", query)
        self.assertEqual(params, ("capital-flow-v2-current",))

    async def test_cockpit_counts_all_current_candidates_but_returns_top_eight(self) -> None:
        class CockpitService(V2ReadModelService):
            requested_limit = 0

            async def candidates(self, limit=50, stock_code=None):
                self.requested_limit = limit
                return {
                    "items": [
                        {"stock_code": f"HK.{index:05d}", "status": "CONFIRMED"}
                        for index in range(10)
                    ],
                    "count": 10,
                }

            async def positions(self):
                return {"items": []}

            async def decisions(self, limit=100, event_id=None):
                return {"items": []}

            async def outcome_distribution(self):
                return {
                    "sample_count": 0,
                    "milestones": {"reached_5_ratio": None},
                }

        service = CockpitService(RecordingDatabase(), now_provider=lambda: NOW)

        result = await service.cockpit()

        self.assertEqual(service.requested_limit, 200)
        self.assertEqual(result["summary"]["confirmed_candidates"], 10)
        self.assertEqual(len(result["candidates"]), 8)


if __name__ == "__main__":
    unittest.main()
