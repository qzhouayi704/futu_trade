import asyncio
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import pytest

from simple_trade.v2.application.book_capture.recorder import BookRecorder
from simple_trade.v2.application.paper_session.factory import research_plan
from simple_trade.v2.application.paper_session.runner import PaperSessionRunner
from simple_trade.v2.application.paper_session.service import PaperSessionService
from simple_trade.v2.application.runtime import V2Runtime
from simple_trade.v2.config.models import V2Config
from simple_trade.v2.domain.capture import BookCaptureConfig, CapturedBook
from simple_trade.v2.domain.decisions import DecisionEvent
from simple_trade.v2.domain.enums import EventType
from simple_trade.v2.domain.paper_session import PaperExperiment, PaperSessionConfig, PaperSessionInterval
from simple_trade.v2.domain.planning.codec import encode
from simple_trade.v2.domain.planning.models import PaperPolicy
from simple_trade.v2.domain.serialization import to_primitive
from simple_trade.v2.infrastructure.book_capture.normalize import normalize_book
from simple_trade.v2.infrastructure.paper.session_store import SqlitePaperSessionStore
from simple_trade.v2.infrastructure.paper.session_report import read_session_report
from tests.v2.test_book_capture import Port, until
from tests.v2.test_stores_and_runtime import SqliteTestDatabase


D = Decimal
NOW = datetime(2026, 9, 23, 10, tzinfo=timezone(timedelta(hours=8)))


def experiment():
    return PaperExperiment(
        experiment_id="test-only", strategy_id="capital_absorption", strategy_version="test-v1",
        stock_codes=("HK.00100",), schedule_source="explicit-test-fixture-not-official-calendar",
        intervals=(PaperSessionInterval(NOW.replace(hour=9, minute=30), NOW.replace(hour=12)),
                   PaperSessionInterval(NOW.replace(hour=13), NOW.replace(hour=16))),
        allow_sampled_server_time=True,
        policy=PaperPolicy(initial_cash=D("100000"), fee_rate=D("0.001"), minimum_fee=D("3")),
        atr_stop_multiple=D("1"), minimum_stop_fraction=D("0.02"), maximum_stop_fraction=D("0.10"),
        pullback_fraction=D("0.005"), chase_fraction=D("0.005"), entry_ttl_seconds=120,
        exit_before_close_seconds=300, maximum_signal_age_seconds=5,
    )


def config(tmp_path, **changes):
    return replace(PaperSessionConfig(path=tmp_path / "paper.db", account_id="paper:session",
                                      experiment=experiment()), **changes)


def signal(when=NOW, *, eligible=True, event_id="signal-1", snapshot_changes=None, **changes):
    stamp = when.isoformat()
    snapshot = {
        "stock_code": "HK.00100", "computed_at": stamp, "quality": "GOOD",
        "quote": {"stock_code": "HK.00100", "last_price": 10, "quality": "GOOD", "exchange_time": stamp,
                  "lot_size_observation": {"stock_code": "HK.00100", "lot_size": 100, "source": "test",
                                           "observed_at": stamp, "quote_exchange_time": stamp}},
        "price_position": {"quality": "GOOD", "atr_percent": 3, "as_of": stamp},
    }
    snapshot.update(snapshot_changes or {})
    return replace(DecisionEvent(
        event_type=EventType.BUY_CONFIRMED, stock_code="HK.00100", exchange_time=when, received_time=when,
        source="v2.candidate-coordinator", strategy_version="test-v1", event_id=event_id,
        new_state="CONFIRMED", old_state="WATCHING", reason_code="test",
        payload={"alert_eligible": eligible, "lifecycle_strategy_source": "capital_absorption",
                 "feature_snapshot": snapshot},
    ), **changes)


def book(seconds=2, **changes):
    when = NOW + timedelta(seconds=seconds)
    return replace(CapturedBook(
        session_id="capture-session", sequence=seconds + 1, connection_id="connection-1", stock_code="HK.00100",
        received_at=when, bid_time=when, ask_time=when, bid=D("9.99"), ask=D("10"),
        bid_size=10000, ask_size=10000,
    ), **changes)


def wait_for(predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("paper worker did not reach expected state")


def test_disabled_and_strict_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("V2_PAPER_SESSION_CONFIG", raising=False)
    assert PaperSessionConfig.from_env() is None
    for changes in ({"allow_sampled_server_time": False}, {"minimum_stop_fraction": D("NaN")},
                    {"maximum_stop_fraction": D("1")}, {"stock_codes": ()},
                    {"stock_codes": ("US.AAPL",)}, {"maximum_signal_age_seconds": 31},
                    {"intervals": (experiment().intervals[0], experiment().intervals[0])}):
        with pytest.raises(ValueError):
            replace(experiment(), **changes)
    with pytest.raises(ValueError):
        config(tmp_path, path="relative.db")
    with pytest.raises(ValueError):
        config(tmp_path, account_id="real:123")


def test_research_plan_uses_point_in_time_price_atr_and_lot():
    result = research_plan(signal(), experiment(), NOW)
    assert result.reason == "RESEARCH_SETUP_CREATED"
    assert result.setup.entry_min == D("9.950")
    assert result.setup.entry_limit == D("10.050")
    assert result.setup.stop_price == D("9.70")
    assert result.setup.lot_size == 100
    assert result.setup.valid_until == NOW + timedelta(seconds=120)
    assert result.setup.exit_at == NOW.replace(hour=15, minute=55)


@pytest.mark.parametrize("event,when,reason", [
    (signal(eligible=False), NOW, "NOT_FORMAL_CONFIRMATION"),
    (signal(strategy_version="other"), NOW, "EXPERIMENT_STRATEGY_MISMATCH"),
    (signal(stock_code="HK.00700"), NOW, "OUTSIDE_EXPERIMENT_UNIVERSE"),
    (signal(), NOW - timedelta(seconds=1), "SIGNAL_NOT_YET_KNOWN_OR_STALE"),
    (signal(), NOW + timedelta(seconds=6), "SIGNAL_NOT_YET_KNOWN_OR_STALE"),
    (signal(NOW.replace(hour=12)), NOW.replace(hour=12), "TRADING_INTERVAL_UNAVAILABLE_OR_CLOSED"),
    (signal(NOW + timedelta(days=1)), NOW + timedelta(days=1), "TRADING_INTERVAL_UNAVAILABLE_OR_CLOSED"),
    (signal(snapshot_changes={"price_position": {"quality": "GOOD", "atr_percent": 20, "as_of": NOW.isoformat()}}), NOW,
     "RESEARCH_STOP_TOO_WIDE"),
    (signal(snapshot_changes={"price_position": {"quality": "GOOD", "atr_percent": 0, "as_of": NOW.isoformat()}}), NOW,
     "SIGNAL_EVIDENCE_MISSING_OR_INVALID"),
])
def test_plan_rejection_reasons(event, when, reason):
    result = research_plan(event, experiment(), when)
    assert result.reason == reason
    assert result.setup is None


def test_half_day_schedule_and_lunch_expiry_are_explicit():
    cfg = replace(experiment(), intervals=(experiment().intervals[0],))
    when = NOW.replace(hour=11, minute=58)
    assert research_plan(signal(when), cfg, when).setup is None
    when = NOW.replace(hour=11, minute=59)
    result = research_plan(signal(when), experiment(), when)
    assert result.setup.valid_until == NOW.replace(hour=12)


def test_missing_mismatched_or_future_lot_evidence_cannot_use_default_lot():
    quote = dict(signal().payload["feature_snapshot"]["quote"])
    for lot in (None, {**quote["lot_size_observation"], "stock_code": "HK.00700"},
                {**quote["lot_size_observation"], "observed_at": (NOW + timedelta(seconds=1)).isoformat()}):
        item = signal(snapshot_changes={"quote": {**quote, "lot_size_observation": lot}})
        assert research_plan(item, experiment(), NOW).setup is None


def test_future_position_evidence_is_rejected_even_when_quote_is_current():
    position = {"quality": "GOOD", "atr_percent": 3, "as_of": (NOW + timedelta(seconds=1)).isoformat()}
    result = research_plan(signal(snapshot_changes={"price_position": position}), experiment(), NOW)
    assert result.reason == "SIGNAL_EVIDENCE_NOT_YET_KNOWN_OR_STALE"


def test_signal_plan_fill_stop_and_later_exit_are_causal_and_audited(tmp_path):
    cfg = config(tmp_path)
    store = SqlitePaperSessionStore(cfg)
    service = PaperSessionService(store, cfg.experiment)
    item = signal()
    assert service.signal(item, NOW) == "PAPER_PLAN_APPROVED"
    assert service.signal(item, NOW + timedelta(seconds=30)) == "PAPER_PLAN_APPROVED"
    assert len(store.read().orders) == 1
    service.book(book(0), NOW + timedelta(milliseconds=100))
    assert not store.read().fills
    service.book(book(2), NOW + timedelta(seconds=2))
    assert store.read().orders[0].held > 0
    service.book(book(3, bid=D("9.60"), ask=D("9.61")), NOW + timedelta(seconds=3))
    assert store.read().orders[0].status == "EXIT_PENDING"
    assert not any(fill.side == "SELL" for fill in store.read().fills)
    service.book(book(4, bid=D("9.59"), ask=D("9.60")), NOW + timedelta(seconds=4))
    assert store.read().orders[0].status == "CLOSED"
    assert store.read().cash < cfg.experiment.policy.initial_cash
    assert service.signal(signal(NOW + timedelta(seconds=5), event_id="new-confirm"),
                          NOW + timedelta(seconds=5)) == "EXPERIMENT_STOCK_DAY_ALREADY_PLANNED"
    with closing(sqlite3.connect(cfg.path)) as conn:
        audit = json.loads(conn.execute("SELECT result_json FROM paper_commands WHERE event_id=?",
                                       ("paper-signal:signal-1",)).fetchone()[0])
    assert audit["input"]["payload"]["feature_snapshot"]["quote"]["last_price"] == 10
    assert audit["result"]["assessment"]["plan"]["setup"]["stop_price"] == "9.70"


def test_changed_duplicate_input_rejected_without_account_mutation(tmp_path):
    cfg = config(tmp_path)
    store = SqlitePaperSessionStore(cfg)
    service = PaperSessionService(store, cfg.experiment)
    item = signal()
    service.signal(item, NOW)
    before = encode(store.read())
    with pytest.raises(ValueError, match="different content"):
        service.signal(replace(item, reason_code="changed"), NOW)
    assert encode(store.read()) == before


def test_stale_closed_or_invalid_book_never_fills(tmp_path):
    cfg = config(tmp_path)
    store = SqlitePaperSessionStore(cfg)
    service = PaperSessionService(store, cfg.experiment)
    service.signal(signal(), NOW)
    assert service.book(book(1), NOW + timedelta(seconds=6)) == "CAPTURE_DELIVERY_STALE_OR_FUTURE"
    assert service.book(book(7, reasons=("SERVER_TIME_MISSING",)), NOW + timedelta(seconds=7)) == "CAPTURE_NOT_EXECUTABLE"
    service.book(book(8), NOW.replace(hour=12))
    assert not store.read().fills
    assert store.read().reserved_cash == 0


def test_deadline_without_book_preserves_unsold_position(tmp_path):
    cfg = config(tmp_path)
    store = SqlitePaperSessionStore(cfg)
    service = PaperSessionService(store, cfg.experiment)
    service.signal(signal(), NOW)
    service.book(book(), NOW + timedelta(seconds=2))
    service.clock(NOW.replace(hour=15, minute=55))
    order = store.read().orders[0]
    assert order.status == "EXIT_PENDING"
    assert order.held > 0 and not order.sold


def test_run_ownership_and_incomplete_restart_require_review(tmp_path):
    cfg = config(tmp_path)
    one, two = SqlitePaperSessionStore(cfg), SqlitePaperSessionStore(cfg)
    one.begin_run("one", "frozen-config")
    with pytest.raises(RuntimeError, match="manual review"):
        two.begin_run("two", "frozen-config")
    one.finish_run("one", None)
    with pytest.raises(ValueError, match="immutable"):
        two.begin_run("two", "changed")
    two.begin_run("two", "frozen-config")
    two.finish_run("two", "test-fault")
    with pytest.raises(RuntimeError, match="manual review"):
        one.begin_run("three", "frozen-config")


def test_clean_restart_with_active_exposure_still_requires_review(tmp_path):
    cfg = config(tmp_path)
    store = SqlitePaperSessionStore(cfg)
    store.begin_run("one", "config")
    PaperSessionService(store, cfg.experiment).signal(signal(), NOW)
    store.finish_run("one", None)
    with pytest.raises(RuntimeError, match="exposure"):
        store.begin_run("two", "config")


def test_nonpaper_database_is_not_modified(tmp_path):
    cfg = config(tmp_path)
    with closing(sqlite3.connect(cfg.path)) as conn, conn:
        conn.execute("CREATE TABLE production (value TEXT)")
        conn.execute("INSERT INTO production VALUES ('untouched')")
    before = cfg.path.read_bytes()
    with pytest.raises(ValueError, match="non-paper"):
        SqlitePaperSessionStore(cfg)
    assert cfg.path.read_bytes() == before


def test_low_disk_and_command_budget(tmp_path):
    cfg = config(tmp_path, max_commands=1)
    with patch("simple_trade.v2.infrastructure.paper.session_store.shutil.disk_usage",
               return_value=SimpleNamespace(free=1)):
        with pytest.raises(RuntimeError, match="free disk"):
            SqlitePaperSessionStore(cfg)
    assert not cfg.path.exists()
    store = SqlitePaperSessionStore(cfg)
    service = PaperSessionService(store, cfg.experiment)
    service.signal(signal(), NOW)
    with pytest.raises(RuntimeError, match="budget"):
        service.book(book(), NOW + timedelta(seconds=2))
    assert not store.read().fills


def test_runner_receives_signal_and_committed_book(tmp_path):
    cfg = config(tmp_path)
    clock = [NOW]
    runner = PaperSessionRunner(cfg, lambda: SqlitePaperSessionStore(cfg), lambda: None, clock=lambda: clock[0])
    runner.start()
    try:
        wait_for(lambda: runner.snapshot().running)
        runner.offer_signal(signal())
        wait_for(lambda: runner.snapshot().plans == 1)
        clock[0] = NOW + timedelta(seconds=2)
        runner.offer_book(book())
        wait_for(lambda: runner.snapshot().fills == 1)
        assert runner.snapshot().active_codes == ("HK.00100",)
        runner.offer_book(book(3, loss_count=1))
        wait_for(lambda: runner.snapshot().error is not None)
        assert runner.snapshot().error == "PAPER_CAPTURE_DISCONTINUITY"
    finally:
        runner.stop()
    assert not runner.snapshot().running


def test_queue_overflow_and_capture_health_halt_without_blocking_producer(tmp_path):
    cfg = config(tmp_path, queue_capacity=1)
    runner = PaperSessionRunner(cfg, lambda: None, lambda: None)
    runner._running = True
    runner.offer_signal(signal())
    runner.offer_signal(signal())
    assert runner.snapshot().error == "PAPER_INPUT_QUEUE_OVERFLOW"
    assert runner.snapshot().dropped == 1
    runner = PaperSessionRunner(cfg, lambda: SqlitePaperSessionStore(cfg), lambda: "CAPTURE_FAILED")
    runner.start()
    wait_for(lambda: runner.snapshot().error == "CAPTURE_FAILED")
    runner.stop()


def test_archive_callback_runs_only_after_commit(tmp_path):
    calls = []
    done = threading.Event()
    class Archive:
        def start(self, session, when):
            pass
        def write(self, books, stats, **kwargs):
            if books:
                calls.append("commit")
    recorder = BookRecorder(BookCaptureConfig(path=tmp_path / "capture.db"), Archive(), normalize_book)
    recorder.set_committed_sink(lambda item: (calls.append("consumer"), done.set()))
    recorder.targets(("HK.00100",))
    recorder.start()
    try:
        recorder.offer({"code": "HK.00100", "Bid": [(9.99, 10000)], "Ask": [(10, 10000)],
                        "svr_recv_time_bid": NOW.isoformat(), "svr_recv_time_ask": NOW.isoformat()}, NOW, "conn")
        assert done.wait(3)
        assert calls == ["commit", "consumer"]
    finally:
        recorder.stop()


def test_runtime_default_disabled_and_optional_paper_start_failure_isolated(tmp_path):
    async def run():
        runtime = V2Runtime(SqliteTestDatabase(tmp_path / "main.db"), V2Config(enabled=True))
        assert runtime.snapshot().paper_session is None
        with pytest.raises(RuntimeError):
            runtime.configure_paper_session(config(tmp_path))
        runtime.configure_book_capture(BookCaptureConfig(path=tmp_path / "capture.db", refresh_seconds=0.02), Port())
        runtime.configure_paper_session(config(tmp_path, experiment=replace(
            experiment(), strategy_version=runtime.config.strategy_version)))
        runtime.paper_session._factory = lambda: (_ for _ in ()).throw(RuntimeError("disk error"))
        await runtime.start()
        try:
            await until(lambda: runtime.snapshot().paper_session.error)
            assert runtime.started and runtime.event_bus.snapshot().running
            assert "HK.00100" in runtime._book_capture_targets()
        finally:
            await runtime.stop()
    asyncio.run(run())


def test_invalidation_cancels_only_remaining_entry_and_preserves_bought_shares(tmp_path):
    cfg = config(tmp_path)
    store = SqlitePaperSessionStore(cfg)
    service = PaperSessionService(store, cfg.experiment)
    service.signal(signal(), NOW)
    service.book(book(2, ask_size=1000), NOW + timedelta(seconds=2))
    held = store.read().orders[0].held
    assert held > 0 and store.read().orders[0].entry_remaining > 0
    invalid = signal(NOW + timedelta(seconds=3), event_id="invalid", event_type=EventType.BUY_INVALIDATED,
                     new_state="INVALIDATED")
    assert service.signal(invalid, NOW + timedelta(seconds=3)) == "SIGNAL_INVALIDATED_ENTRY_CANCELLED"
    service.book(book(4), NOW + timedelta(seconds=4))
    assert store.read().orders[0].held == held
    assert store.read().orders[0].entry_remaining == 0


def test_plan_never_fills_on_book_that_was_available_before_approval(tmp_path):
    cfg = config(tmp_path)
    store = SqlitePaperSessionStore(cfg)
    service = PaperSessionService(store, cfg.experiment)
    service.signal(signal(), NOW + timedelta(seconds=1))
    service.book(book(0), NOW + timedelta(seconds=2))
    assert not store.read().fills
    service.book(book(3), NOW + timedelta(seconds=3))
    assert store.read().fills


def test_explicit_configuration_file_roundtrip(tmp_path, monkeypatch):
    from dataclasses import asdict
    cfg = config(tmp_path)
    payload = {**asdict(cfg), "path": str(cfg.path), "schema_version": 1}
    path = tmp_path / "experiment.json"
    path.write_text(encode(payload), encoding="utf-8")
    monkeypatch.setenv("V2_PAPER_SESSION_CONFIG", str(path))
    assert PaperSessionConfig.from_env() == cfg


def test_report_is_read_only_and_flags_stale_marks(tmp_path):
    cfg = config(tmp_path)
    store = SqlitePaperSessionStore(cfg)
    store.begin_run("one", encode({"experiment": "fixture"}))
    service = PaperSessionService(store, cfg.experiment)
    service.signal(signal(), NOW)
    service.book(book(2), NOW + timedelta(seconds=2))
    before = cfg.path.read_bytes()
    result = read_session_report(cfg.path, now=NOW + timedelta(seconds=6))
    assert result["stale_position_codes"] == ("HK.00100",)
    assert result["run_record_status"] == "OPEN_OR_UNCLEAN"
    assert result["closed_order_net_pnl"] == 0
    assert result["fill_count"] == 1 and result["fees"] > 0
    assert cfg.path.read_bytes() == before
    with pytest.raises(sqlite3.OperationalError):
        read_session_report(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()


def test_inspection_cli_does_not_initialize_broker_or_create_missing_db(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "inspect_paper_session.py"
    result = subprocess.run([sys.executable, str(script), "--db", str(tmp_path / "missing.db")],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 1 and "inspection failed" in result.stderr
    assert not (tmp_path / "missing.db").exists()


def test_two_threads_cannot_claim_the_same_run(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    cfg = config(tmp_path)
    one, two = SqlitePaperSessionStore(cfg), SqlitePaperSessionStore(cfg)
    def claim(store, owner):
        try:
            store.begin_run(owner, "same-config")
        except RuntimeError:
            return False
        return True
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(claim, one, "one")
        second = pool.submit(claim, two, "two")
        assert sorted((first.result(), second.result())) == [False, True]


def test_archive_failure_never_notifies_paper_consumer(tmp_path):
    calls = []
    class Archive:
        def start(self, session, when):
            pass
        def write(self, books, stats, **kwargs):
            if books:
                raise OSError("disk full")
    recorder = BookRecorder(BookCaptureConfig(path=tmp_path / "capture.db"), Archive(), normalize_book)
    recorder.set_committed_sink(calls.append)
    recorder.targets(("HK.00100",))
    recorder.start()
    try:
        recorder.offer({"code": "HK.00100"}, NOW, "conn")
        wait_for(lambda: recorder.snapshot().error)
        assert calls == []
    finally:
        recorder.stop()


def test_paper_write_failure_halts_and_leaves_no_phantom_plan(tmp_path):
    cfg = config(tmp_path)
    store = SqlitePaperSessionStore(cfg)
    runner = PaperSessionRunner(cfg, lambda: store, lambda: None, clock=lambda: NOW)
    runner.start()
    try:
        wait_for(lambda: runner.snapshot().running)
        with patch.object(store, "apply", side_effect=sqlite3.OperationalError("disk full")):
            runner.offer_signal(signal())
            wait_for(lambda: runner.snapshot().error)
        assert store.read().orders == []
        assert not runner.snapshot().running
    finally:
        runner.stop()


def test_runtime_end_to_end_signal_capture_fill_deadline_without_live_trading(tmp_path):
    async def run():
        runtime = V2Runtime(SqliteTestDatabase(tmp_path / "main.db"), V2Config(enabled=True))
        port = Port()
        runtime.configure_book_capture(BookCaptureConfig(path=tmp_path / "capture.db", refresh_seconds=0.02), port)
        cfg = config(tmp_path, experiment=replace(experiment(), strategy_version=runtime.config.strategy_version))
        runtime.configure_paper_session(cfg)
        clock = [NOW]
        runtime.paper_session._clock = lambda: clock[0]
        await runtime.start()
        try:
            await until(lambda: runtime.snapshot().paper_session.running and port.calls)
            runtime.event_bus.publish_nowait(signal(strategy_version=runtime.config.strategy_version))
            await until(lambda: runtime.snapshot().paper_session.plans == 1)
            clock[0] = NOW + timedelta(seconds=2)
            stamp = clock[0].isoformat()
            port.sink({"code": "HK.00100", "Bid": [(9.99, 10000)], "Ask": [(10, 10000)],
                       "svr_recv_time_bid": stamp, "svr_recv_time_ask": stamp}, clock[0], "conn")
            await until(lambda: runtime.snapshot().paper_session.fills == 1)
            assert runtime.snapshot().book_capture.persisted == 1
            assert runtime.market_projector.snapshot().order_book_updates == 0
            assert runtime.execution_port is None
            clock[0] = NOW.replace(hour=15, minute=55)
            await until(lambda: runtime.snapshot().paper_session.last_result == "CLOCK_ADVANCED")
            assert runtime.snapshot().paper_session.stale_position_codes == ("HK.00100",)
            state = SqlitePaperSessionStore(cfg).read()
            assert state.orders[0].status == "EXIT_PENDING" and state.orders[0].held > 0
            json.dumps(to_primitive(runtime.snapshot()))
        finally:
            await runtime.stop()
    asyncio.run(run())
