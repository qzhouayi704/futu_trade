import unittest
from types import SimpleNamespace

from simple_trade.v2.application.read_models.service import V2ReadModelService


class RecordingDatabase:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def execute_query(self, query: str, params: tuple | None = None) -> list:
        self.calls.append((query, params or ()))
        return []


class ReadModelVersionScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidates_are_scoped_to_runtime_strategy_version(self) -> None:
        database = RecordingDatabase()
        runtime = SimpleNamespace(
            config=SimpleNamespace(strategy_version="capital-flow-v2-current")
        )
        service = V2ReadModelService(database, runtime)

        await service.candidates(limit=12, stock_code="hk.00522")

        query, params = database.calls[-1]
        self.assertIn("s.strategy_version=?", query)
        self.assertIn("s.stock_code=?", query)
        self.assertEqual(
            params,
            ("capital-flow-v2-current", "HK.00522", 12),
        )

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


if __name__ == "__main__":
    unittest.main()
