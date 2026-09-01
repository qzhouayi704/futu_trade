from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from simple_trade.v2.infrastructure.feature_reference_loader import FeatureReferenceLoader


class SqliteReferenceDatabase:
    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def execute_query(self, query: str, params: tuple | None = None) -> list:
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(query, params or ()).fetchall()


class FeatureReferenceLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_per_stock_capital_baselines_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baselines.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(
                    "CREATE TABLE market_baselines (stock_code TEXT, metric_key TEXT, "
                    "p50 REAL, sample_count INTEGER, computed_at TEXT);"
                    "INSERT INTO market_baselines VALUES "
                    "('HK.00100','big_order_threshold',200000,2,'2026-08-30'),"
                    "('HK.00100','big_order_threshold',300000,5,'2026-08-31'),"
                    "('HK.00100','window_net_scale',800000,5,'2026-08-31'),"
                    "('HK.00200','big_order_threshold',150000,1,'2026-08-31');"
                )
            baselines = await FeatureReferenceLoader(
                SqliteReferenceDatabase(path)
            ).load_capital_baselines()

        self.assertEqual(len(baselines), 2)
        self.assertEqual(baselines[0].large_order_threshold, 300_000)
        self.assertEqual(baselines[0].flow_scale, 800_000)
        self.assertEqual(baselines[0].quality.value, "GOOD")
        self.assertEqual(baselines[1].flow_scale, 150_000)
        self.assertEqual(baselines[1].quality.value, "DEGRADED")

    async def test_only_active_or_priority_universe_daily_bars_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "references.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(
                    "CREATE TABLE daily_active_stocks ("
                    "check_date TEXT, stock_code TEXT, is_active INTEGER);"
                    "CREATE TABLE stocks (code TEXT, is_manual INTEGER, "
                    "stock_priority INTEGER, heat_score REAL);"
                    "CREATE TABLE kline_data (stock_code TEXT, time_key TEXT, "
                    "open_price REAL, high_price REAL, low_price REAL, "
                    "close_price REAL, volume INTEGER, turnover REAL);"
                    "INSERT INTO daily_active_stocks VALUES "
                    "('2026-08-31', 'HK.00100', 1), "
                    "('2026-08-31', 'HK.00999', 0);"
                    "INSERT INTO stocks VALUES "
                    "('HK.00100', 0, 0, 1), "
                    "('HK.00200', 1, 0, 0), "
                    "('HK.00999', 0, 0, 0);"
                    "INSERT INTO kline_data VALUES "
                    "('HK.00100', '2026-08-29', 10, 12, 9, 11, 1000, 11000), "
                    "('HK.00200', '2026-08-29', 20, 22, 19, 21, 1000, 21000), "
                    "('HK.00999', '2026-08-29', 30, 32, 29, 31, 1000, 31000);"
                )
            bars = await FeatureReferenceLoader(
                SqliteReferenceDatabase(path)
            ).load_daily_bars()

        self.assertEqual({bar.stock_code for bar in bars}, {"HK.00100", "HK.00200"})
        self.assertTrue(all(bar.as_of.tzinfo is not None for bar in bars))

    async def test_dynamic_stock_daily_bars_load_outside_startup_universe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dynamic-references.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(
                    "CREATE TABLE kline_data (stock_code TEXT, time_key TEXT, "
                    "open_price REAL, high_price REAL, low_price REAL, "
                    "close_price REAL, volume INTEGER, turnover REAL);"
                    "INSERT INTO kline_data VALUES "
                    "('HK.02706', '2026-08-29', 10, 12, 9, 11, 1000, 11000);"
                )
            bars = await FeatureReferenceLoader(
                SqliteReferenceDatabase(path)
            ).load_daily_bars_for_codes(("HK.02706",))

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].stock_code, "HK.02706")


if __name__ == "__main__":
    unittest.main()
