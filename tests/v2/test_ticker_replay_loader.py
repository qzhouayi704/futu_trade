from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from simple_trade.v2.infrastructure.ticker_replay_loader import TickerReplayLimitExceeded, TickerReplayLoader


class ReplayDatabase:
    def __init__(self, path: Path) -> None:
        self.path = str(path)
        self.last_query = ""
        self.last_params: tuple = ()

    def execute_query(self, query: str, params: tuple | None = None) -> list:
        self.last_query = query
        self.last_params = params or ()
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(query, params or ()).fetchall()


class TickerReplayLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ticks.db"
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "CREATE TABLE ticker_data (id INTEGER PRIMARY KEY, stock_code TEXT, "
                "trade_time TEXT, price REAL, volume INTEGER, turnover REAL, "
                "direction TEXT, sequence INTEGER, timestamp INTEGER, trade_date TEXT)"
            )
            connection.execute("CREATE INDEX idx_ticker_timestamp ON ticker_data(timestamp)")
        self.db = ReplayDatabase(self.path)

    def insert(self, rows):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executemany("INSERT INTO ticker_data VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            connection.commit()

    async def test_true_trade_time_filters_late_receipt_and_future_ticks(self):
        received_ms = int(datetime(2026, 9, 1, 5, 59, tzinfo=timezone.utc).timestamp() * 1000)
        self.insert([
            (1, "HK.00100", "2026-09-01 13:30:00", 10, 100, 1000, "BUY", 1, received_ms, "2026-09-01"),
            (2, "HK.00100", "2026-09-01 10:00:00", 10, 100, 1000, "BUY", 2, received_ms, "2026-09-01"),
            (3, "HK.00100", "2026-09-01 14:01:00", 10, 100, 500000, "BUY", 3, received_ms, "2026-09-01"),
            (4, "HK.00100", "2026-09-01T02:00:00Z", 10, 100, 80000, "SELL", 4, received_ms, "2026-09-02"),
        ])
        rows = await TickerReplayLoader(self.db).load(
            "2026-09-01", datetime(2026, 9, 1, 6, tzinfo=timezone.utc), minimum_large_turnover=50000,
        )
        self.assertEqual([row["direction"] for row in rows], ["SELL", "BUY"])
        self.assertEqual([row["time"][11:16] for row in rows], ["10:00", "13:30"])

    async def test_replay_limit_fails_instead_of_restoring_partial_state(self):
        received_ms = int(datetime(2026, 9, 1, 5, 32, tzinfo=timezone.utc).timestamp() * 1000)
        self.insert([
            (1, "HK.00100", "2026-09-01 13:30:00", 10, 100, 1000, "BUY", 1, received_ms, "2026-09-01"),
            (2, "HK.00100", "2026-09-01 13:31:00", 10, 100, 1000, "BUY", 2, received_ms, "2026-09-01"),
        ])
        with self.assertRaises(TickerReplayLimitExceeded):
            await TickerReplayLoader(self.db, row_limit=1).load(
                "2026-09-01", datetime(2026, 9, 1, 6, tzinfo=timezone.utc),
            )

    async def test_us_wall_time_is_not_interpreted_as_hong_kong_time(self):
        received_ms = int(datetime(2026, 9, 1, 14, 59, tzinfo=timezone.utc).timestamp() * 1000)
        self.insert([
            (1, "US.TEST", "2026-09-01 10:30:00", 10, 100, 1000, "BUY", 1, received_ms, "2026-09-01"),
        ])
        rows = await TickerReplayLoader(self.db).load(
            "2026-09-01", datetime(2026, 9, 1, 15, tzinfo=timezone.utc),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["time"], "2026-09-01T10:30:00-04:00")

    async def test_prefilter_uses_receipt_timestamp_index(self):
        received_ms = int(datetime(2026, 9, 1, 5, 30, tzinfo=timezone.utc).timestamp() * 1000)
        self.insert([
            (1, "HK.00100", "2026-09-01 13:30:00", 10, 100, 1000, "BUY", 1, received_ms, "2026-09-01"),
        ])
        await TickerReplayLoader(self.db).load(
            "2026-09-01", datetime(2026, 9, 1, 6, tzinfo=timezone.utc),
        )
        with closing(sqlite3.connect(self.path)) as connection:
            plan = connection.execute(
                "EXPLAIN QUERY PLAN " + self.db.last_query,
                self.db.last_params,
            ).fetchall()

        self.assertIn("idx_ticker_timestamp", " ".join(str(row[3]) for row in plan))
        self.assertNotIn("julianday", self.db.last_query.lower())

    async def test_recent_tape_and_older_large_ticks_are_loaded(self) -> None:
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
                         150_000, "SELL", 8, stale_ms, "2026-09-01"),
                        (2, "HK.02706", "2026-09-01 13:30:00.000", 11, 200,
                         2200, "BUY", 2, recent_ms, "2026-09-01"),
                        (3, "HK.02706", "2026-09-01 12:31:00.000", 10, 100,
                         50_000, "BUY", 9, stale_ms, "2026-09-01"),
                        (4, "HK.02706", "2026-09-01 13:31:00.000", 11, 200,
                         2200, "NEUTRAL", 3, recent_ms, "2026-09-01"),
                    ),
                )
                connection.commit()
            rows = await TickerReplayLoader(ReplayDatabase(path)).load(
                "2026-09-01", as_of
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual([row["direction"] for row in rows], ["SELL", "BUY"])
        self.assertTrue(all(row["sequence"] is None for row in rows))


if __name__ == "__main__":
    unittest.main()
