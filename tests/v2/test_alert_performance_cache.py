import asyncio
from dataclasses import replace
from types import SimpleNamespace
import time
import unittest
from unittest.mock import AsyncMock

from simple_trade.routers.v2.read_models import _service
from simple_trade.v2.application.read_models.alert_performance import AlertPerformanceReader


class PerformanceCacheTests(unittest.IsolatedAsyncioTestCase):
    def reader(self):
        reader = AlertPerformanceReader(object())
        reader._history = AsyncMock(return_value={
            "trade_date": "2026-09-07", "scope": "candidates",
            "as_of": "2026-09-07T10:00:00+08:00", "items": [{"signal_price": 100}],
        })
        return reader

    async def test_fresh_cache_avoids_queries_and_does_not_share_mutable_output(self):
        reader = self.reader()
        first = await reader.history(trade_date="2026-09-07")
        first["items"][0]["signal_price"] = 0
        second = await reader.history(trade_date="2026-09-07")
        self.assertEqual(second["items"][0]["signal_price"], 100)
        self.assertEqual(second["refresh_status"], "READY")
        reader._history.assert_awaited_once()

    async def test_concurrent_requests_share_one_computation(self):
        reader = self.reader()
        started, finish = asyncio.Event(), asyncio.Event()

        async def read(**_kwargs):
            started.set()
            await finish.wait()
            return {"count": 1}

        reader._history.side_effect = read
        tasks = [asyncio.create_task(reader.history(trade_date="2026-09-07")) for _ in range(8)]
        await started.wait()
        finish.set()
        results = await asyncio.gather(*tasks)
        reader._history.assert_awaited_once()
        self.assertTrue(all(result["count"] == 1 for result in results))
        self.assertEqual(reader._pending, {})

    async def test_disconnected_caller_does_not_cancel_shared_work(self):
        reader = self.reader()
        started, finish = asyncio.Event(), asyncio.Event()

        async def read(**_kwargs):
            started.set()
            await finish.wait()
            return {"count": 1}

        reader._history.side_effect = read
        caller = asyncio.create_task(reader.history(trade_date="2026-09-07"))
        await started.wait()
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        follower = asyncio.create_task(reader.history(trade_date="2026-09-07"))
        finish.set()
        self.assertEqual((await follower)["count"], 1)
        reader._history.assert_awaited_once()

    async def test_dates_and_scopes_are_isolated_and_cache_is_bounded(self):
        reader = self.reader()
        reader.MAX_CACHE_ENTRIES = 2
        await reader.history(trade_date="2026-09-07")
        await reader.history(trade_date="2026-09-07", scope="alerts")
        await reader.history(trade_date="2026-09-08")
        self.assertEqual(reader._history.await_count, 3)
        self.assertEqual(len(reader._cache), 2)
        self.assertNotIn(("2026-09-07", "candidates"), reader._cache)

    async def test_failed_refresh_marks_recent_snapshot_stale_without_changing_as_of(self):
        reader = self.reader()
        first = await reader.history(trade_date="2026-09-07")
        key = ("2026-09-07", "candidates")
        reader._cache[key] = replace(reader._cache[key], started_at=time.monotonic() - 31)
        reader._history.side_effect = RuntimeError("interrupted")
        result = await reader.history(trade_date="2026-09-07")
        self.assertEqual(result["refresh_status"], "STALE")
        self.assertEqual(result["as_of"], first["as_of"])
        self.assertGreaterEqual(result["cache_age_seconds"], 31)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(reader._pending, {})

    async def test_old_snapshot_cannot_hide_a_database_failure(self):
        reader = self.reader()
        await reader.history(trade_date="2026-09-07")
        key = ("2026-09-07", "candidates")
        reader._cache[key] = replace(reader._cache[key], started_at=time.monotonic() - 121)
        reader._history.side_effect = RuntimeError("interrupted")
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            await reader.history(trade_date="2026-09-07")

    async def test_cold_failure_is_not_cached_and_next_request_can_recover(self):
        reader = self.reader()
        reader._history.side_effect = [RuntimeError("interrupted"), {"count": 3}]
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            await reader.history(trade_date="2026-09-07")
        self.assertEqual(reader._cache, {})
        self.assertEqual((await reader.history(trade_date="2026-09-07"))["count"], 3)

    async def test_total_read_budget_ends_waiting_and_releases_slot(self):
        reader = self.reader()
        reader.REFRESH_TIMEOUT_SECONDS = 0.02

        async def hang(**_kwargs):
            await asyncio.Event().wait()

        reader._history.side_effect = hang
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(reader.history(trade_date="2026-09-07"), timeout=0.5)
        self.assertEqual(reader._pending, {})
        reader._history.side_effect = None
        self.assertEqual((await reader.history(trade_date="2026-09-07"))["refresh_status"], "READY")

    async def test_pending_capacity_rejects_extra_distinct_work(self):
        reader = self.reader()
        reader.MAX_PENDING = 1
        started, finish = asyncio.Event(), asyncio.Event()

        async def read(**_kwargs):
            started.set()
            await finish.wait()
            return {"count": 1}

        reader._history.side_effect = read
        caller = asyncio.create_task(reader.history(trade_date="2026-09-07"))
        await started.wait()
        with self.assertRaisesRegex(TimeoutError, "繁忙"):
            await reader.history(trade_date="2026-09-07", scope="alerts")
        finish.set()
        await caller

    async def test_route_services_reuse_reader_only_for_the_same_database(self):
        container = SimpleNamespace(db_manager=object(), v2_runtime=None)
        first = _service(container)
        second = _service(container)
        self.assertIs(first._alert_performance, second._alert_performance)
        container.db_manager = object()
        third = _service(container)
        self.assertIsNot(first._alert_performance, third._alert_performance)

    async def test_invalid_scope_does_not_start_background_work(self):
        reader = self.reader()
        with self.assertRaises(ValueError):
            await reader.history(trade_date="2026-09-07", scope="unknown")
        reader._history.assert_not_awaited()
