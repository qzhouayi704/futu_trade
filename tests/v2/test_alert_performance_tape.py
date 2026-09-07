from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from simple_trade.v2.application.read_models.alert_performance_tape import AlertPerformanceTapeReader


class TapeDatabase:
    def __init__(self, path):
        self.path = path

    def execute_query(self, query, params=()):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(query, params).fetchall()


class AlertPerformanceTapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_last_trade_uses_time_then_id_and_never_the_highest_price(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tape.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    "CREATE TABLE ticker_data (id INTEGER PRIMARY KEY, stock_code TEXT, "
                    "trade_date TEXT, trade_time TEXT, price REAL)"
                )
                connection.executemany("INSERT INTO ticker_data VALUES (?,?,?,?,?)", [
                    (1, "HK.00100", "2026-09-02", "2026-09-02 10:00:00", 150),
                    (2, "HK.00100", "2026-09-02", "2026-09-02 10:02:00", 105),
                    (3, "HK.00100", "2026-09-02", "2026-09-02T02:02:00Z", 101),
                    (4, "HK.00100", "2026-09-02", "2026-09-02 10:01:00", 90),
                    (5, "HK.00100", "2026-09-02", "2026-09-02 10:03:00", 1000),
                ])
                connection.commit()
            result = await AlertPerformanceTapeReader(TapeDatabase(path)).read([
                {"event_id": "a", "stock_code": "HK.00100", "signal_time": "2026-09-02T10:00:00+08:00"},
            ], datetime(2026, 9, 2, 2, 2, tzinfo=timezone.utc))
        self.assertEqual(result["a"].last_price, 101)
        self.assertEqual(result["a"].high_price, 150)
        self.assertEqual(result["a"].low_price, 90)
        self.assertEqual(result["a"].sample_count, 4)

    async def test_exact_seconds_timezone_and_trade_order_in_real_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tape.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    "CREATE TABLE ticker_data (id INTEGER PRIMARY KEY, stock_code TEXT, "
                    "trade_date TEXT, trade_time TEXT, price REAL)"
                )
                connection.execute("CREATE INDEX idx_ticker_stock_date ON ticker_data(stock_code,trade_date)")
                connection.executemany("INSERT INTO ticker_data VALUES (?,?,?,?,?)", [
                    (1, "HK.00100", "2026-09-02", "2026-09-02 10:00:20", 120),
                    (2, "HK.00100", "2026-09-02", "2026-09-02T02:00:30Z", 100),
                    (3, "HK.00100", "2026-09-02", "2026-09-02 10:00:40", 103),
                    (4, "HK.00100", "2026-09-02", "2026-09-02T10:02:00+08:00", 102),
                    (5, "HK.00100", "2026-09-03", "2026-09-02 10:01:00", 99),
                    (6, "HK.00100", "2026-09-02", "2026-09-02 10:03:00", 200),
                    (7, "HK.00100", "2026-09-02", "2026-09-02 10:02:00", -1),
                    (8, "HK.00200", "2026-09-02", "2026-09-02 10:02:00", 500),
                ])
                connection.commit()
            reader = AlertPerformanceTapeReader(TapeDatabase(path))
            result = await reader.read([
                {"event_id": "a", "stock_code": "HK.00100", "signal_time": "2026-09-02T10:00:30+08:00"},
                {"event_id": "b", "stock_code": "HK.00100", "signal_time": "2026-09-02T10:01:30+08:00"},
                {"event_id": "future", "stock_code": "HK.00100", "signal_time": "2026-09-02T10:03:00+08:00"},
            ], datetime(2026, 9, 2, 2, 2, tzinfo=timezone.utc))
        self.assertEqual(set(result), {"a", "b"})
        self.assertEqual(result["a"].last_price, 102)
        self.assertEqual(result["a"].high_price, 103)
        self.assertEqual(result["a"].low_price, 99)
        self.assertEqual(result["a"].sample_count, 4)
        self.assertEqual(result["a"].first_time, "2026-09-02T10:00:30+08:00")
        self.assertEqual(result["a"].last_time, "2026-09-02T10:02:00+08:00")
        self.assertEqual(result["b"].sample_count, 1)

    async def test_empty_requests_do_not_query_database(self):
        class NeverQuery:
            def execute_query(self, *args):
                raise AssertionError("Empty requests should not scan ticker_data")

        result = await AlertPerformanceTapeReader(NeverQuery()).read([], datetime.now(timezone.utc))
        self.assertEqual(result, {})
