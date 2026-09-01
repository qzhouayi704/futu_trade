import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from simple_trade.database.core.schema_recovery import (
    TICKER_TARGET_UNIQUE,
    create_indexes_best_effort,
    migrate_ticker_data_schema,
)


OLD_TICKER_SCHEMA = """
CREATE TABLE ticker_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    price REAL NOT NULL,
    volume INTEGER NOT NULL,
    turnover REAL,
    direction TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    trade_date TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(stock_code, timestamp, price, volume)
)
"""


class TickerSchemaRecoveryTests(unittest.TestCase):
    def test_interrupted_migration_is_rebuilt_without_losing_source_rows(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(OLD_TICKER_SCHEMA)
        conn.execute(
            "INSERT INTO ticker_data "
            "(stock_code, price, volume, turnover, direction, timestamp, trade_date) "
            "VALUES ('HK.00100', 100, 200, 20000, 'BUY', 1, '2026-09-01')"
        )
        conn.execute("CREATE TABLE ticker_data_new (stale TEXT)")
        conn.commit()

        self.assertTrue(migrate_ticker_data_schema(conn))

        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='ticker_data'"
        ).fetchone()[0]
        self.assertIn(
            TICKER_TARGET_UNIQUE.replace(" ", ""), sql.replace(" ", "")
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ticker_data").fetchone()[0], 1)
        self.assertIsNone(
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name='ticker_data_new'"
            ).fetchone()
        )
        self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        conn.close()

    def test_completed_schema_removes_only_stale_migration_table(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(f"""
            CREATE TABLE ticker_data (
                id INTEGER PRIMARY KEY,
                stock_code TEXT NOT NULL,
                price REAL NOT NULL,
                volume INTEGER NOT NULL,
                turnover REAL,
                direction TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                trade_date TEXT NOT NULL,
                sequence INTEGER,
                trade_time TEXT,
                created_at TEXT,
                {TICKER_TARGET_UNIQUE}
            )
        """)
        conn.execute("CREATE TABLE ticker_data_new (stale TEXT)")

        self.assertFalse(migrate_ticker_data_schema(conn))
        self.assertIsNone(
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name='ticker_data_new'"
            ).fetchone()
        )
        conn.close()


class StartupIndexRecoveryTests(unittest.TestCase):
    def test_first_lock_defers_remaining_indexes_with_bounded_wait(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "locked.db")
            writer = sqlite3.connect(path, timeout=1)
            startup = sqlite3.connect(path, timeout=1)
            writer.execute("CREATE TABLE sample (id INTEGER, value INTEGER)")
            writer.commit()
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO sample VALUES (1, 1)")

            started = time.monotonic()
            results = create_indexes_best_effort(
                startup,
                [
                    "CREATE INDEX IF NOT EXISTS idx_sample_id ON sample(id)",
                    "CREATE INDEX IF NOT EXISTS idx_sample_value ON sample(value)",
                ],
                lock_timeout_ms=50,
            )
            elapsed = time.monotonic() - started

            self.assertEqual(results, {"idx_sample_id": False})
            self.assertLess(elapsed, 0.8)
            self.assertEqual(startup.execute("PRAGMA busy_timeout").fetchone()[0], 1000)
            writer.rollback()
            writer.close()
            startup.close()


if __name__ == "__main__":
    unittest.main()
