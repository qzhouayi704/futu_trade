import asyncio
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from simple_trade.v2.application.book_capture.coordinator import BookCaptureCoordinator
from simple_trade.v2.application.book_capture.paper_input import to_paper_book
from simple_trade.v2.application.book_capture.recorder import BookRecorder
from simple_trade.v2.application.runtime import V2Runtime
from simple_trade.v2.config.models import V2Config
from simple_trade.v2.domain.capture import BookCaptureConfig
from simple_trade.v2.infrastructure.book_capture.archive import (
    CaptureCapacityError, SqliteBookArchive, decode_book, read_archive,
)
from simple_trade.v2.infrastructure.book_capture.futu_port import FutuBookCapturePort
from simple_trade.v2.infrastructure.book_capture.normalize import normalize_book
from tests.v2.test_stores_and_runtime import SqliteTestDatabase


NOW = datetime(2026, 9, 23, 10, 0, tzinfo=timezone(timedelta(hours=8)))


def raw(**kwargs):
    return {"code": "HK.00100", "svr_recv_time_bid": NOW.isoformat(), "svr_recv_time_ask": NOW.isoformat(),
            "Bid": [(100, 1000, 1, {})], "Ask": [(101, 1000, 1, {})], **kwargs}


def book(**kwargs):
    return normalize_book(raw(**kwargs), session_id="session", sequence=1, connection_id="conn",
                          received_at=NOW, loss_count=0)


def config(tmp_path, **kwargs):
    return BookCaptureConfig(path=tmp_path / "capture.db", **kwargs)


def recorder(tmp_path, **kwargs):
    cfg = config(tmp_path, **kwargs)
    return BookRecorder(cfg, SqliteBookArchive(cfg), normalize_book)


async def until(predicate):
    async with asyncio.timeout(4):
        while not predicate():
            await asyncio.sleep(0.01)


def test_capture_requires_opt_in_and_absolute_separate_path(monkeypatch):
    monkeypatch.delenv("V2_BOOK_CAPTURE_PATH", raising=False)
    assert BookCaptureConfig.from_env() is None
    monkeypatch.setenv("V2_BOOK_CAPTURE_PATH", "trade.db")
    with pytest.raises(ValueError, match="absolute"):
        BookCaptureConfig.from_env()


@pytest.mark.parametrize("values", [{"max_stocks": 21}, {"queue_capacity": 0}, {"max_bytes": 1},
                                   {"sample_interval_seconds": float("nan")}])
def test_invalid_limits_rejected(tmp_path, values):
    with pytest.raises(ValueError):
        config(tmp_path, **values)


@pytest.mark.parametrize("value", ["", "0", "n/a", None])
def test_missing_server_times_are_not_replaced_with_local_clock(value):
    result = book(svr_recv_time_bid=value)
    assert result.bid_time is None
    assert "SERVER_TIME_MISSING" in result.reasons
    with pytest.raises(ValueError):
        to_paper_book(result, market_open=True, allow_sampled_server_time=True)


@pytest.mark.parametrize("delta", [-4, 1])
def test_each_side_must_be_known_and_fresh(delta):
    result = book(svr_recv_time_ask=(NOW + timedelta(seconds=delta)).isoformat())
    assert "SERVER_TIME_FUTURE_OR_STALE" in result.reasons
    with pytest.raises(ValueError):
        to_paper_book(result, market_open=True, allow_sampled_server_time=True)


@pytest.mark.parametrize("changes", [{"Bid": []}, {"Ask": [(99, 1000)]}, {"Ask": [(100, 1000)]},
                                     {"Bid": [(float("nan"), 100)]}, {"Bid": [(100, 0)]},
                                     {"Ask": [(101, 2.5)]}, {"order_book_type": "AUCTION"}])
def test_invalid_books_are_recorded_but_cannot_fill(changes):
    result = book(**changes)
    assert result.reasons
    with pytest.raises(ValueError):
        to_paper_book(result, market_open=True, allow_sampled_server_time=True)


def test_paper_conversion_is_explicit_and_uses_older_server_side():
    result = book(svr_recv_time_bid=(NOW - timedelta(seconds=1)).replace(tzinfo=None).isoformat())
    assert not result.reasons
    with pytest.raises(ValueError, match="opt-in"):
        to_paper_book(result, market_open=True)
    converted = to_paper_book(result, market_open=False, allow_sampled_server_time=True)
    assert converted.exchange_time == NOW - timedelta(seconds=1)
    assert not converted.market_open
    assert converted.bid == Decimal("100")


def test_queue_sampling_loss_and_reconnect_are_visible_without_io(tmp_path):
    cfg = config(tmp_path, queue_capacity=1)
    archive = MagicMock()
    now = [0.0]
    capture = BookRecorder(cfg, archive, normalize_book, monotonic=lambda: now[0])
    capture._running = True
    capture.targets(("HK.00100",))
    capture.offer(raw(), NOW, "c1")
    capture.offer(raw(), NOW, "c1")
    assert capture.snapshot().sampled_out == 1
    now[0] = 1
    capture.offer(raw(), NOW, "c1")
    assert capture.snapshot().dropped == 1
    capture._queue.get_nowait()
    now[0] = 2
    capture.offer(raw(), NOW, "c2")
    captured = capture._queue.get_nowait()
    assert "CAPTURE_HAS_GAPS" in captured.reasons
    assert "CONNECTION_CHANGED" in captured.reasons
    assert capture.snapshot().connection_changes == 1
    archive.write.assert_not_called()
    with pytest.raises(ValueError):
        to_paper_book(captured, market_open=True, allow_sampled_server_time=True)


def test_writer_persists_exact_evidence_and_clean_shutdown(tmp_path):
    capture = recorder(tmp_path)
    capture.targets(("HK.00100",))
    capture.start()
    capture.offer(raw(), NOW, "c1")
    capture.stop()
    assert not capture.snapshot().running
    assert capture.snapshot().persisted == 1
    with closing(sqlite3.connect(capture.config.path)) as conn:
        stored = decode_book(conn.execute("SELECT payload FROM captured_books").fetchone()[0])
    assert stored.bid_time == NOW
    assert stored.bid == 100
    assert stored.connection_id == "c1"
    report = read_archive(capture.config.path)
    assert report["sessions"][0]["closed_cleanly"]
    assert report["stocks"][0]["records"] == 1
    with pytest.raises(RuntimeError):
        capture.start()


def test_archive_does_not_mutate_main_database(tmp_path):
    cfg = config(tmp_path)
    with closing(sqlite3.connect(cfg.path)) as conn:
        conn.execute("CREATE TABLE stocks (id INTEGER)")
        conn.commit()
    before = cfg.path.read_bytes()
    with pytest.raises(ValueError, match="non-capture"):
        SqliteBookArchive(cfg).start("s", NOW)
    assert cfg.path.read_bytes() == before


def test_archive_limit_and_identity_are_transactional(tmp_path):
    cfg = config(tmp_path, max_records=1)
    archive = SqliteBookArchive(cfg)
    archive.start("session", NOW)
    status = replace(BookRecorder(cfg, archive, normalize_book).snapshot(), session_id="session")
    first = book()
    archive.write((first,), status)
    archive.write((first,), status)
    with pytest.raises(ValueError, match="different content"):
        archive.write((replace(first, bid=Decimal("98")),), status)
    with pytest.raises(CaptureCapacityError):
        archive.write((replace(first, sequence=2),), status)
    with pytest.raises(ValueError, match="another session"):
        archive.write((replace(first, session_id="other"),), status)
    report = read_archive(cfg.path)
    assert report["stocks"][0]["records"] == 1
    assert not report["sessions"][0]["closed_cleanly"]


def test_fatal_archive_error_stops_accepting_and_reports_loss(tmp_path):
    async def run():
        capture = recorder(tmp_path, max_records=1, sample_interval_seconds=0.1)
        capture.targets(("HK.00100", "HK.00700"))
        capture.start()
        try:
            capture.offer(raw(), NOW, "c1")
            capture.offer(raw(code="HK.00700"), NOW, "c1")
            await until(lambda: bool(capture.snapshot().error))
            assert not capture.snapshot().running
            before = capture.snapshot().received
            capture.offer(raw(), NOW, "c1")
            assert capture.snapshot().received == before
        finally:
            await asyncio.to_thread(capture.stop)
        assert capture.snapshot().dropped == 2
        report = read_archive(capture.config.path)
        assert report["stocks"] == []
        assert not report["sessions"][0]["closed_cleanly"]
    asyncio.run(run())


class Port:
    def __init__(self):
        self.sink = None
        self.closed = False
        self.calls = []

    def set_sink(self, sink):
        self.sink = sink

    def sync(self, codes):
        self.calls.append(codes)
        return codes

    def close(self):
        self.closed = True
        self.sink = None


def test_coordinator_bounds_targets_and_detaches_on_stop(tmp_path):
    async def run():
        cfg = config(tmp_path, max_stocks=1, refresh_seconds=0.02)
        port = Port()
        capture = BookRecorder(cfg, SqliteBookArchive(cfg), normalize_book)
        runner = BookCaptureCoordinator(cfg, port, lambda: ("HK.00100", "HK.00700"), capture)
        await runner.start()
        try:
            await until(lambda: bool(port.calls))
            assert port.calls[0] == ("HK.00100",)
            port.sink(raw(), NOW, "c1")
        finally:
            await runner.stop()
        assert port.closed
        assert runner.snapshot().persisted == 1
    asyncio.run(run())


def test_runtime_capture_is_disabled_by_default_and_failure_does_not_stop_alerts(tmp_path):
    async def run():
        db = SqliteTestDatabase(tmp_path / "trades.db")
        runtime = V2Runtime(db, V2Config(enabled=True))
        assert runtime.snapshot().book_capture is None
        runtime.configure_book_capture(BookCaptureConfig(path=tmp_path / "trades.db"), Port())
        await runtime.start()
        try:
            assert runtime.started
            assert "non-capture" in runtime.snapshot().book_capture.error
            assert not runtime.snapshot().book_capture.running
        finally:
            await runtime.stop()
    asyncio.run(run())


def test_capture_cli_reports_readonly_and_rejects_foreign_db(tmp_path):
    capture = recorder(tmp_path)
    capture.start()
    capture.stop()
    script = Path(__file__).resolve().parents[2] / "scripts" / "inspect_book_capture.py"
    result = subprocess.run([sys.executable, str(script), "--db", str(capture.config.path)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["sampled_best_book_only"]
    missing = tmp_path / "missing.db"
    result = subprocess.run([sys.executable, str(script), "--db", str(missing)], capture_output=True, timeout=15)
    assert result.returncode == 1
    assert not missing.exists()
