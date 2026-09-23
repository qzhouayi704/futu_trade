import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading
from unittest.mock import MagicMock, patch

from simple_trade.api.futu_client import FutuClient
from simple_trade.api.subscription_manager import SubscriptionManager
from simple_trade.v2.application.book_capture.coordinator import BookCaptureCoordinator
from simple_trade.v2.application.book_capture.recorder import BookRecorder
from simple_trade.v2.application.runtime import V2Runtime
from simple_trade.v2.config.models import V2Config
from simple_trade.v2.domain.candidates import TradeCandidate
from simple_trade.v2.domain.enums import CandidateStatus, DataQuality
from simple_trade.v2.infrastructure.book_capture.archive import SqliteBookArchive
from simple_trade.v2.infrastructure.book_capture.futu_port import FutuBookCapturePort
from simple_trade.v2.infrastructure.book_capture.normalize import normalize_book
from tests.v2.test_book_capture import NOW, Port, config, raw, until
from tests.v2.test_stores_and_runtime import SqliteTestDatabase


def client_manager():
    client = MagicMock()
    client.book_connection_id = "connection-1"
    client.is_available.return_value = True
    client.subscribe_stocks.return_value = (0, None)
    client.unsubscribe_stocks.return_value = (0, None)
    return client, SubscriptionManager(futu_client=client)


@patch('simple_trade.utils.rate_limiter.wait_for_api')
def test_feed_uses_only_spare_quota_and_preserves_all_other_data(_wait):
    client, manager = client_manager()
    manager._total_quota = 300
    manager._quote_subscribed.update(f"HK.{i:05d}" for i in range(200))
    manager._ticker_subscribed.update(f"HK.{i:05d}" for i in range(100))
    port = FutuBookCapturePort(client, manager, max_stocks=8)
    quote_before, ticker_before = manager.subscribed_stocks, manager.ticker_subscribed_stocks
    assert port.sync(("HK.00100",)) == ()
    assert manager.subscribed_stocks == quote_before
    assert manager.ticker_subscribed_stocks == ticker_before
    client.unsubscribe_stocks.assert_not_called()


@patch('simple_trade.utils.rate_limiter.wait_for_api')
def test_feed_rotates_only_owned_books_after_minimum_age(_wait):
    client, manager = client_manager()
    manager._orderbook_subscribed.add("HK.00700")
    clock = [0.0]
    port = FutuBookCapturePort(client, manager, max_stocks=1, monotonic=lambda: clock[0])
    assert port.sync(("HK.00700",)) == ("HK.00700",)
    assert port.sync(("HK.00100",)) == ("HK.00100",)
    assert "HK.00700" in manager.orderbook_subscribed_stocks
    assert port.sync(("HK.00916",)) == ()
    assert "HK.00100" in manager.orderbook_subscribed_stocks
    clock[0] = 66
    assert port.sync(("HK.00916",)) == ("HK.00916",)
    assert "HK.00100" not in manager.orderbook_subscribed_stocks
    assert "HK.00700" in manager.orderbook_subscribed_stocks
    assert all(types == ['ORDER_BOOK'] for _, types in (call.args for call in client.unsubscribe_stocks.call_args_list))


@patch('simple_trade.utils.rate_limiter.wait_for_api')
def test_new_connection_reacquires_books_without_clearing_quote_or_ticker(_wait):
    client, manager = client_manager()
    manager._quote_subscribed.add("HK.00100")
    manager._ticker_subscribed.add("HK.00100")
    port = FutuBookCapturePort(client, manager, max_stocks=1)
    assert port.sync(("HK.00100",)) == ("HK.00100",)
    calls = client.subscribe_stocks.call_count
    client.book_connection_id = "connection-2"
    assert port.sync(("HK.00100",)) == ("HK.00100",)
    assert client.subscribe_stocks.call_count == calls + 1
    assert manager.subscribed_stocks == {"HK.00100"}
    assert manager.ticker_subscribed_stocks == {"HK.00100"}
    port.close()
    assert port.sync(("HK.00700",)) == ()
    client.set_order_book_sink.assert_called_with(None)


def test_push_sink_survives_reconnect_and_old_connection_is_ignored():
    client = FutuClient()
    client.client = MagicMock()
    client.is_connected = True
    sink = MagicMock()
    client.set_order_book_sink(sink)
    first = client._order_book_push_handler
    first.parse_rsp_pb = MagicMock(return_value=(0, raw()))
    first.on_recv_rsp(None)
    assert sink.call_count == 1
    assert sink.call_args.args[2] == first.connection_id
    client._cleanup()
    client.client = MagicMock()
    client.is_connected = True
    client._register_order_book_handler()
    second = client._order_book_push_handler
    assert first.connection_id != second.connection_id
    first.on_recv_rsp(None)
    assert sink.call_count == 1
    second.parse_rsp_pb = MagicMock(return_value=(0, raw()))
    second.on_recv_rsp(None)
    assert sink.call_count == 2
    client.set_order_book_sink(None)
    second.on_recv_rsp(None)
    assert sink.call_count == 2


def test_target_selection_prefers_exposure_and_ignores_previous_day_candidates(tmp_path):
    runtime = V2Runtime(SqliteTestDatabase(tmp_path / "main.db"), V2Config(enabled=True))
    runtime.exposure_subscription_coordinator._positions = {"HK.00916"}
    now = datetime.now(timezone.utc)
    def candidate(code, at, score=90, status=CandidateStatus.BUY_CONFIRMED):
        return TradeCandidate(stock_code=code, as_of=at, status=status, score=score,
                              quality=DataQuality.GOOD, reason_codes=("test",), invalidation_conditions=())
    runtime.candidate_coordinator._latest = {
        "HK.00100": candidate("HK.00100", now),
        "HK.00700": candidate("HK.00700", now - timedelta(days=1), score=100),
        "HK.00981": candidate("HK.00981", now, score=95, status=CandidateStatus.BUY_INVALIDATED),
    }
    assert runtime._book_capture_targets() == ("HK.00916", "HK.00100")


def test_runtime_end_to_end_capture_does_not_feed_strategy_bus(tmp_path):
    async def run():
        runtime = V2Runtime(SqliteTestDatabase(tmp_path / "main.db"), V2Config(enabled=True))
        port = Port()
        cfg = config(tmp_path, refresh_seconds=0.02)
        runtime.exposure_subscription_coordinator._positions = {"HK.00100"}
        runtime.configure_book_capture(cfg, port)
        await runtime.start()
        try:
            await until(lambda: port.calls)
            port.sink(raw(), NOW, "connection-1")
            assert runtime.market_projector.snapshot().order_book_updates == 0
        finally:
            await runtime.stop()
        assert runtime.snapshot().book_capture.persisted == 1
        assert not runtime.snapshot().book_capture.running
        assert port.closed
    asyncio.run(run())


def test_slow_subscription_has_only_one_inflight_call(tmp_path):
    async def run():
        cfg = config(tmp_path, refresh_seconds=0.02, io_timeout_seconds=0.03)
        port = Port()
        release = threading.Event()
        def blocked(codes):
            port.calls.append(codes)
            release.wait(2)
            return codes
        port.sync = blocked
        capture = BookRecorder(cfg, SqliteBookArchive(cfg), normalize_book)
        runner = BookCaptureCoordinator(cfg, port, lambda: ("HK.00100",), capture)
        await runner.start()
        try:
            await until(lambda: runner.snapshot().subscription_failures >= 2)
            assert len(port.calls) == 1
        finally:
            release.set()
            await runner.stop()
    asyncio.run(run())


def test_low_disk_space_fails_before_creating_archive(tmp_path):
    from simple_trade.v2.infrastructure.book_capture.archive import CaptureCapacityError
    import pytest
    cfg = config(tmp_path)
    with patch('simple_trade.v2.infrastructure.book_capture.archive.shutil.disk_usage',
               return_value=SimpleNamespace(free=1)):
        with pytest.raises(CaptureCapacityError, match="free disk"):
            SqliteBookArchive(cfg).start("session", NOW)
    assert not cfg.path.exists()
