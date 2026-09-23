import asyncio
from contextlib import closing
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal
import json
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from simple_trade.v2.application.paper_session.read_model import PaperLedgerReader
from simple_trade.v2.application.paper_session.service import PaperSessionService
from simple_trade.v2.domain.paper_session import PaperSessionStats
from simple_trade.v2.domain.planning.codec import encode
from simple_trade.v2.domain.serialization import to_primitive
from simple_trade.v2.infrastructure.paper.session_report import read_ledger_snapshot
from simple_trade.v2.infrastructure.paper.session_store import SqlitePaperSessionStore
from tests.v2.test_paper_session import NOW, config, signal, book


def initialized(tmp_path):
    cfg = config(tmp_path)
    store = SqlitePaperSessionStore(cfg)
    store.begin_run("run-test", encode({**asdict(cfg), "path": str(cfg.path)}))
    return cfg, store, PaperSessionService(store, cfg.experiment)


def stats(**changes):
    return replace(PaperSessionStats(
        True, "paper:session", "test-only", 0, 0, 0, 0, (), 0, 0, "100000", "100000", (),
        NOW, None, None,
    ), **changes)


def test_report_read_only_decimal_and_signal_not_hidden_by_books(tmp_path):
    cfg, store, service = initialized(tmp_path)
    service.signal(signal(eligible=False), NOW)
    service.signal(signal(event_id="approved"), NOW)
    service.book(book(), book().received_at)
    for i in range(70):
        item = book(i + 3)
        service.book(item, item.received_at)
    before = cfg.path.read_bytes()
    report = read_ledger_snapshot(cfg.path)
    assert cfg.path.read_bytes() == before
    assert len(report.recent_signals) == 2
    assert report.recent_signals[-1].reason == "NOT_FORMAL_CONFIRMATION"
    assert report.orders[0].held > 0
    assert report.orders[0].entry_limit == "10.050"
    assert report.orders[0].closed_net_pnl is None
    assert report.closed_order_count == 0
    assert report.fill_count == 1
    assert report.recent_fills[0].stock_code == "HK.00100"
    payload = to_primitive(report)
    assert isinstance(payload["cash"], str)
    assert isinstance(payload["recent_fills"][0]["fee"], str)
    assert "path" not in json.dumps(payload)
    store.finish_run("run-test", None)


def test_missing_db_is_not_created_and_wrong_db_not_accepted(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        read_ledger_snapshot(path)
    assert not path.exists()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE live_data (value TEXT)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="not a paper ledger"):
        read_ledger_snapshot(path)
    assert path.read_bytes() == before


def test_report_stale_held_marks_and_closed_pnl(tmp_path):
    cfg, store, service = initialized(tmp_path)
    service.signal(signal(), NOW)
    service.book(book(), book().received_at)
    assert read_ledger_snapshot(cfg.path, now=NOW + timedelta(minutes=2)).stale_position_codes == ("HK.00100",)
    stop = book(3, bid=Decimal("9"), ask=Decimal("9.01"))
    service.book(stop, stop.received_at)
    service.book(replace(stop, sequence=20, received_at=book(5).received_at,
                         bid_time=book(5).received_at, ask_time=book(5).received_at), book(5).received_at)
    report = read_ledger_snapshot(cfg.path)
    assert report.closed_order_count == 1
    assert report.orders[0].closed_net_pnl == report.closed_order_net_pnl
    assert report.stale_position_codes == ()
    assert report.orders[0].status == "CLOSED"


@pytest.mark.parametrize("table,field,size", [
    ("paper_account", "state_json", 4194305),
    ("paper_session_run", "configuration", 262145),
    ("paper_commands", "result_json", 262145),
])
def test_report_json_bounded_before_decode(tmp_path, table, field, size):
    cfg, _, service = initialized(tmp_path)
    service.signal(signal(), NOW)
    with closing(sqlite3.connect(cfg.path)) as conn, conn:
        conn.execute(f"UPDATE {table} SET {field}=?", ("x" * size,))
    with pytest.raises(ValueError, match="read budget"):
        read_ledger_snapshot(cfg.path)


def test_disabled_and_uninitialized_without_file_writes(tmp_path):
    inspect = Mock(side_effect=AssertionError("should not read"))
    disabled = asyncio.run(PaperLedgerReader(None, inspect).read())
    assert disabled.status == "DISABLED" and not disabled.execution_enabled
    session = SimpleNamespace(config=config(tmp_path), snapshot=lambda: stats(cash=None))
    result = asyncio.run(PaperLedgerReader(session, inspect).read())
    assert result.status == "NOT_INITIALIZED" and result.ledger is None
    assert not session.config.path.exists()
    inspect.assert_not_called()


def test_failed_start_preserves_existing_ledger_and_sanitizes_error(tmp_path):
    cfg, _, service = initialized(tmp_path)
    service.signal(signal(), NOW)
    service.book(book(), book().received_at)
    session = SimpleNamespace(config=cfg, snapshot=lambda: stats(
        running=False, cash=None, error="PAPER_SESSION_FAILED:ValueError:/private/path",
    ))
    result = asyncio.run(PaperLedgerReader(session, read_ledger_snapshot).read())
    assert result.status == "ERROR" and result.ledger.orders[0].held > 0
    assert result.runtime.error == "PAPER_SESSION_FAILED"
    assert not result.execution_enabled


def test_read_coalesces_and_caller_cancellation_does_not_cancel_query(tmp_path):
    cfg, _, _ = initialized(tmp_path)
    snapshot = read_ledger_snapshot(cfg.path)
    entered, release = threading.Event(), threading.Event()

    def inspect(path):
        entered.set()
        assert release.wait(3)
        return snapshot

    inspect = Mock(side_effect=inspect)
    reader = PaperLedgerReader(SimpleNamespace(config=cfg, snapshot=stats), inspect)

    async def run():
        first = asyncio.create_task(reader.read())
        assert await asyncio.to_thread(entered.wait, 2)
        second = asyncio.create_task(reader.read())
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert (await second).status == "RUNNING"
        assert (await reader.read()).ledger == snapshot

    asyncio.run(run())
    inspect.assert_called_once()


def test_identity_mismatch_and_missing_initialized_ledger_fail(tmp_path):
    cfg, _, _ = initialized(tmp_path)
    session = SimpleNamespace(config=cfg, snapshot=lambda: stats(account_id="paper:other"))
    with pytest.raises(ValueError, match="identity mismatch"):
        asyncio.run(PaperLedgerReader(session, read_ledger_snapshot).read())
    session.config = replace(cfg, path=tmp_path / "absent.db")
    with pytest.raises(ValueError, match="ledger is missing"):
        asyncio.run(PaperLedgerReader(session, read_ledger_snapshot).read())


def test_orders_bounded_with_old_active_exposure_first(tmp_path, monkeypatch):
    from simple_trade.v2.infrastructure.paper import session_report

    cfg, _, service = initialized(tmp_path)
    service.signal(signal(), NOW)
    source = session_report.read_session_report(cfg.path)
    active = source["orders"][0]
    closed = [{**active, "plan": replace(active["plan"], plan_id=f"closed-{i}",
               approved_at=NOW + timedelta(milliseconds=i + 1)), "entry_remaining": 0,
               "bought": 100, "sold": 100, "closed_net_pnl": Decimal("0"), "status": "CLOSED"}
              for i in range(150)]
    source["orders"] = [active, *closed]
    monkeypatch.setattr(session_report, "read_session_report", lambda path, **kw: source)
    result = read_ledger_snapshot(cfg.path)
    assert result.order_count == 151 and len(result.orders) == 100
    assert result.orders[0].plan_id == active["plan"].plan_id
    assert result.orders[1].plan_id == "closed-149"


def test_status_is_refreshed_after_slow_read(tmp_path):
    cfg, _, _ = initialized(tmp_path)
    current = stats()

    def inspect(path):
        nonlocal current
        current = stats(running=False, error="PAPER_CAPTURE_UNAVAILABLE")
        return read_ledger_snapshot(path)

    reader = PaperLedgerReader(SimpleNamespace(config=cfg, snapshot=lambda: current), inspect)
    assert asyncio.run(reader.read()).status == "ERROR"


def test_route_contract_and_read_failure_do_not_leak_path(tmp_path, monkeypatch):
    from simple_trade.routers.v2 import read_models

    container = SimpleNamespace(v2_runtime=None)
    response = asyncio.run(read_models.get_paper_ledger(container))
    assert response.success and response.data["status"] == "DISABLED"
    cfg, _, _ = initialized(tmp_path)
    container.v2_runtime = SimpleNamespace(paper_session=SimpleNamespace(config=cfg, snapshot=stats))
    monkeypatch.setattr(read_models, "read_ledger_snapshot", Mock(side_effect=ValueError("/private/path")))
    response = asyncio.run(read_models.get_paper_ledger(container))
    assert not response.success and response.data is None
    assert "/private/path" not in response.model_dump_json()
