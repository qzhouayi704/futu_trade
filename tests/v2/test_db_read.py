from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from simple_trade.v2.infrastructure.db_read import SqliteReadDatabase, strict_reader


class BoundedReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "read.db"
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TABLE data (value INTEGER)")
            connection.execute("INSERT INTO data VALUES (1)")
            connection.commit()

    def test_read_errors_are_not_empty_results_and_connection_cannot_write(self):
        reader = SqliteReadDatabase(self.path)
        self.assertEqual(reader.execute_query("SELECT * FROM data"), [(1,)])
        with self.assertRaises(sqlite3.OperationalError):
            reader.execute_query("SELECT * FROM missing_table")
        with self.assertRaises(sqlite3.OperationalError):
            reader.execute_query("DELETE FROM data")
        self.assertEqual(reader.execute_query("SELECT * FROM data"), [(1,)])

    def test_missing_file_is_not_created(self):
        path = self.path.with_name("missing.db")
        with self.assertRaises(sqlite3.OperationalError):
            SqliteReadDatabase(path).execute_query("SELECT 1")
        self.assertFalse(path.exists())

    def test_slow_query_is_interrupted_and_releases_capacity(self):
        reader = SqliteReadDatabase(self.path, timeout_seconds=0.01)
        with self.assertRaises(sqlite3.OperationalError):
            reader.execute_query(
                "WITH RECURSIVE numbers(n) AS (VALUES(1) UNION ALL "
                "SELECT n+1 FROM numbers WHERE n<100000000) SELECT SUM(n) FROM numbers"
            )
        self.assertEqual(reader.execute_query("SELECT 1"), [(1,)])

    def test_adapter_bypasses_legacy_error_swallowing(self):
        class LegacyDatabase:
            database_path = str(self.path)

            def execute_query(self, *args):
                return []

        self.assertEqual(strict_reader(LegacyDatabase()).execute_query("SELECT * FROM data"), [(1,)])
