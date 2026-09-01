from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from simple_trade.v2.infrastructure.ticker_replay_loader import TickerReplayLoader


class ReplayDatabase:
    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def execute_query(self, query: str, params: tuple | None = None) -> list:
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(query, params or ()).fetchall()


class TickerReplayLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_recent_ticks_are_loaded_without_unstable_sequence(self) -> None:
        hk = timezone(timedelta(hours=8))
        as_of = datetime(2026, 9, 1, 14, 0, tzinfo=hk)
        recent_ms = int((as_of - timedelta(minutes=30)).timestamp() * 1000)
        stale_ms = int((as_of - timedelta(minutes=90)).timestamp() * 1000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(
                    "CREATE TABLE ticker_data (id INTEGER PRIMARY KEY, "
                    "stock_code TEXT, trade_time TEXT, price REAL, volume INTEGER, "
                    "turnover REAL, direction TEXT, sequence INTEGER, "
                    "timestamp INTEGER, trade_date TEXT);"
                )
                connection.executemany(
                    "INSERT INTO ticker_data VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        (1, "HK.02706", "2026-09-01 12:30:00.000", 10, 100,
                         1000, "SELL", 8, stale_ms, "2026-09-01"),
                        (2, "HK.02706", "2026-09-01 13:30:00.000", 11, 200,
                         2200, "BUY", 2, recent_ms, "2026-09-01"),
                    ),
                )
                connection.commit()
            rows = await TickerReplayLoader(ReplayDatabase(path)).load(
                "2026-09-01", as_of
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], "BUY")
        self.assertEqual(rows[0]["time"], "2026-09-01 13:30:00.000")
        self.assertIsNone(rows[0]["sequence"])


if __name__ == "__main__":
    unittest.main()
