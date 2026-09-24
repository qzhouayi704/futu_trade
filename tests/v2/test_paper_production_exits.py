from dataclasses import asdict, replace
from datetime import timedelta
import json
from unittest.mock import Mock, patch

import pytest

from simple_trade.v2.application.paper_session.factory import research_plan
from simple_trade.v2.application.paper_session.service import PaperSessionService
from simple_trade.v2.application.paper_session.runner import PaperSessionRunner
from simple_trade.v2.application.positions.structural_exit import StructuralExitPolicy
from simple_trade.v2.domain.enums import DataQuality, EventType
from simple_trade.v2.domain.events import FeatureSnapshotEvent
from simple_trade.v2.domain.planning.codec import decode_account, encode, encode_account
from simple_trade.v2.domain.planning.models import PaperExitPolicy
from simple_trade.v2.infrastructure.paper.session_store import SqlitePaperSessionStore
from simple_trade.v2.infrastructure.paper.session_report import read_ledger_snapshot
from tests.v2.test_candidate_strategy import snapshot, window
from tests.v2.test_paper_session import D, NOW, book, config, experiment, signal, wait_for


def feature(seconds, price, *, complete=True, support=False, outflow=False, accepted=True):
    when = NOW + timedelta(seconds=seconds)
    flow = replace(window(900, buys=3 if support else 0, sells=3 if outflow else 0,
                          buy_amount=600_000 if support else 0, sell_amount=500_000 if outflow else 0),
                   as_of=when,
                   first_independent_buy_at=when - timedelta(minutes=5) if support else None,
                   last_independent_buy_at=when if support else None,
                   first_independent_sell_at=when - timedelta(seconds=301) if outflow else None,
                   last_independent_sell_at=when - timedelta(seconds=1) if outflow else None)
    view = snapshot(as_of=when, price=price, high_price=999, low_price=1,
                    windows=(flow,) if complete else (), accepted=accepted)
    return FeatureSnapshotEvent(event_type=EventType.FEATURE_SNAPSHOT_READY, stock_code="HK.00100",
                                exchange_time=when, received_time=when, source="test", strategy_version="test-v1",
                                event_id=f"feature:{seconds}", snapshot=view)


def opened(tmp_path, *, ask=D("10"), size=10000):
    cfg = config(tmp_path, experiment=replace(experiment(), exit_policy=PaperExitPolicy.PRODUCTION_RULES))
    store = SqlitePaperSessionStore(cfg)
    service = PaperSessionService(store, cfg.experiment)
    assert service.signal(signal(), NOW) == "PAPER_PLAN_APPROVED"
    service.book(book(2, ask=ask, ask_size=size), NOW + timedelta(seconds=2))
    assert store.read().orders[0].held
    return store, service


def evaluate(service, event):
    return service.feature(event, event.received_time)


def test_mode_is_explicit_and_production_budget_reuses_policy(monkeypatch):
    assert experiment().exit_policy is PaperExitPolicy.RESEARCH_ATR
    with pytest.raises(ValueError):
        replace(experiment(), exit_policy="unknown")
    cfg = replace(experiment(), exit_policy="PRODUCTION_RULES")
    assert research_plan(signal(), cfg, NOW).setup.stop_price == D("9.6515")
    monkeypatch.setattr(StructuralExitPolicy, "HARD_STOP_PCT", -4.0)
    assert research_plan(signal(), cfg, NOW).setup.stop_price == D("9.552")
    assert research_plan(signal(), experiment(), NOW).setup.stop_price == D("9.70")


@pytest.mark.parametrize("price,reason", [(9.68, "HARD_STOP_3_PCT"), (10.55, "TAKE_PROFIT_5_PCT")])
def test_shared_price_exits_wait_for_later_book_and_charge_fees(tmp_path, price, reason):
    store, service = opened(tmp_path)
    assert evaluate(service, feature(3, price)) == "PRODUCTION_POSITION_EVALUATED"
    order = store.read().orders[0]
    assert order.exit_reason == reason
    assert order.status == "EXIT_PENDING" and order.sold == 0
    service.book(book(3, bid=D(str(price)), ask=D(str(price)) + D(".01")), NOW + timedelta(seconds=3))
    assert store.read().orders[0].sold == 0
    service.book(book(4, bid=D(str(price)), ask=D(str(price)) + D(".01")), NOW + timedelta(seconds=4))
    account = store.read()
    order = account.orders[0]
    assert order.status == "CLOSED"
    assert order.buy_fee > 0 and order.sell_fee > 0
    assert account.cash - account.policy.initial_cash == (
        order.sell_notional - order.buy_notional - order.buy_fee - order.sell_fee)


def test_exit_uses_fill_cost_not_signal_price_or_day_high(tmp_path):
    store, service = opened(tmp_path, ask=D("10.04"))
    evaluate(service, feature(3, 10.51))
    order = store.read().orders[0]
    assert order.exit_reason is None
    assert order.position_state.cost_price == 10.04
    assert order.position_state.peak_price == 10.51
    assert order.position_state.mfe_pct == pytest.approx((10.51 / 10.04 - 1) * 100)
    evaluate(service, feature(4, 10.55))
    assert store.read().orders[0].exit_reason == "TAKE_PROFIT_5_PCT"


def test_production_book_does_not_use_atr_exit_for_filled_position(tmp_path):
    store, service = opened(tmp_path)
    service.book(book(3, bid=D("9.5"), ask=D("9.51")), NOW + timedelta(seconds=3))
    assert store.read().orders[0].exit_reason is None
    evaluate(service, feature(4, 9.5, complete=False))
    assert store.read().orders[0].exit_reason == "HARD_STOP_3_PCT"


def test_missing_flow_is_not_treated_as_loss_of_support(tmp_path):
    store, service = opened(tmp_path)
    evaluate(service, feature(3, 10.4))
    evaluate(service, feature(4, 10.2, complete=False))
    order = store.read().orders[0]
    assert order.exit_reason is None
    assert order.position_state.metadata["last_reason"] == "PRODUCTION_EXIT_EVIDENCE_INCOMPLETE"
    evaluate(service, feature(5, 10.2))
    assert store.read().orders[0].exit_reason == "TRAIL_AFTER_SUPPORT_LOST"


def test_recent_inflow_protects_drawdown_then_lost_support_exits(tmp_path):
    store, service = opened(tmp_path)
    evaluate(service, feature(3, 10.4, support=True))
    evaluate(service, feature(4, 10.2, outflow=True))
    assert store.read().orders[0].exit_reason is None
    evaluate(service, feature(1300, 10.2, outflow=True))
    assert store.read().orders[0].exit_reason == "REPEATED_OUTFLOW_AND_STRUCTURE_BREAK"


def test_prefill_quote_stale_future_and_strategy_mismatch_do_not_evaluate(tmp_path):
    store, service = opened(tmp_path)
    event = feature(3, 9)
    pref = replace(event, snapshot=replace(event.snapshot, quote=replace(event.snapshot.quote, exchange_time=NOW)))
    assert evaluate(service, pref) == "POSITION_FEATURE_NOT_NEWER"
    assert store.read().orders[0].position_state is None
    assert evaluate(service, replace(feature(4, 9), strategy_version="wrong")) == "POSITION_FEATURE_STRATEGY_MISMATCH"
    stale = feature(5, 9)
    assert service.feature(stale, NOW + timedelta(seconds=11)) == "POSITION_FEATURE_STALE_OR_FUTURE"
    future = feature(12, 9)
    future = replace(future, snapshot=replace(future.snapshot, quote=replace(
        future.snapshot.quote, exchange_time=NOW + timedelta(seconds=13))))
    assert evaluate(service, future) == "POSITION_FEATURE_STALE_OR_FUTURE"
    assert store.read().orders[0].exit_reason is None


@pytest.mark.parametrize("bad_window", ["future", "stale", "invalid"])
def test_incomplete_flow_cannot_trigger_structural_exit(tmp_path, bad_window):
    store, service = opened(tmp_path)
    evaluate(service, feature(3, 10.4))
    event = feature(10, 10.2, outflow=True)
    flow = event.snapshot.tick_windows[0]
    if bad_window == "future":
        flow = replace(flow, last_independent_sell_at=event.exchange_time + timedelta(seconds=1))
    elif bad_window == "stale":
        flow = replace(flow, as_of=NOW)
    else:
        flow = replace(flow, quality=DataQuality.INVALID)
    evaluate(service, replace(event, snapshot=replace(event.snapshot, tick_windows=(flow,))))
    assert store.read().orders[0].exit_reason is None


def test_position_state_survives_service_restart_and_idempotent_audit(tmp_path):
    store, service = opened(tmp_path)
    event = feature(3, 10, accepted=False)
    evaluate(service, event)
    before = encode_account(store.read())
    assert encode_account(decode_account(before)) == before
    evaluate(service, event)
    assert encode_account(store.read()) == before
    with pytest.raises(ValueError, match="different content"):
        evaluate(service, replace(event, source="changed"))
    assert encode_account(store.read()) == before
    service = PaperSessionService(store, service.experiment)
    evaluate(service, feature(63, 10, accepted=False))
    assert store.read().orders[0].position_state.metadata["exit_vwap_below_minutes"] == 2


def test_partial_buys_update_cost_without_resetting_price_path(tmp_path):
    store, service = opened(tmp_path, size=1000)
    evaluate(service, feature(3, 10.3, support=True))
    service.book(book(4, ask=D("10.04"), ask_size=1000), NOW + timedelta(seconds=4))
    evaluate(service, feature(5, 10.2, support=True))
    order = store.read().orders[0]
    assert order.position_state.cost_price == float(order.buy_notional / order.bought)
    assert order.position_state.peak_price == 10.3
    assert order.position_state.mfe_pct == pytest.approx((10.3 / order.position_state.cost_price - 1) * 100)


def test_no_position_and_research_mode_do_not_create_production_state(tmp_path):
    cfg = config(tmp_path)
    store = SqlitePaperSessionStore(cfg)
    service = PaperSessionService(store, cfg.experiment)
    assert evaluate(service, feature(3, 11)) == "PRODUCTION_EXIT_MODE_DISABLED"
    assert not store.read().orders


def test_shared_additions_are_disabled_without_changing_production_defaults(tmp_path):
    store, service = opened(tmp_path)
    with patch("simple_trade.v2.application.positions.addition.PositionAddPolicy.assess",
               side_effect=AssertionError("paper must not run additions")):
        evaluate(service, feature(3, 10.1, support=True))
    assert store.read().orders[0].position_state.metadata["last_action"] == "HOLD"


def test_position_mutations_rollback_on_failed_exit_command(tmp_path):
    store, service = opened(tmp_path)
    before = encode_account(store.read())
    with patch("simple_trade.v2.application.paper_session.positions.PaperEngine.request_exit",
               side_effect=RuntimeError("transaction failure")):
        with pytest.raises(RuntimeError, match="transaction failure"):
            evaluate(service, feature(3, 11))
    assert encode_account(store.read()) == before
    evaluate(service, feature(3, 11))
    assert store.read().orders[0].exit_reason == "TAKE_PROFIT_5_PCT"


def test_legacy_json_defaults_to_research_and_has_no_analysis_state(tmp_path):
    cfg = config(tmp_path)
    store = SqlitePaperSessionStore(cfg)
    PaperSessionService(store, cfg.experiment).signal(signal(), NOW)
    payload = json.loads(encode_account(store.read()))
    order = payload["account"]["orders"][0]
    del order["plan"]["setup"]["exit_policy"]
    del order["position_state"]
    del order["price_history"]
    decoded = decode_account(json.dumps(payload)).orders[0]
    assert decoded.plan.setup.exit_policy is PaperExitPolicy.RESEARCH_ATR
    assert decoded.position_state is None and not decoded.price_history


def test_report_distinguishes_evaluation_staleness_from_mark_staleness(tmp_path):
    cfg = config(tmp_path, experiment=replace(experiment(), exit_policy="PRODUCTION_RULES"))
    store = SqlitePaperSessionStore(cfg)
    store.begin_run("report", encode({**asdict(cfg), "path": str(cfg.path)}))
    service = PaperSessionService(store, cfg.experiment)
    service.signal(signal(), NOW)
    service.book(book(2), NOW + timedelta(seconds=2))
    report = read_ledger_snapshot(cfg.path, now=NOW + timedelta(seconds=2))
    assert report.exit_policy == "PRODUCTION_RULES"
    assert report.stale_analysis_codes == ("HK.00100",)
    assert not report.stale_position_codes
    assert report.orders[0].average_buy_price == "10"
    evaluate(service, feature(3, 10.1))
    report = read_ledger_snapshot(cfg.path, now=NOW + timedelta(seconds=3))
    assert not report.stale_analysis_codes
    assert report.orders[0].position_evaluated_at == NOW + timedelta(seconds=3)
    assert report.orders[0].position_reason == "POSITION_EFFICIENT"
    assert read_ledger_snapshot(cfg.path, now=NOW + timedelta(seconds=9)).stale_analysis_codes == ("HK.00100",)
    evaluate(service, feature(10, 11))
    report = read_ledger_snapshot(cfg.path, now=NOW + timedelta(seconds=10))
    assert report.orders[0].exit_reason == "TAKE_PROFIT_5_PCT"
    assert report.orders[0].exit_triggered_at == NOW + timedelta(seconds=10)
    assert report.orders[0].closed_net_pnl is None
    store.finish_run("report", None)


def test_production_runner_consumes_features_without_publishing_trade_commands(tmp_path):
    cfg = config(tmp_path, experiment=replace(experiment(), exit_policy=PaperExitPolicy.PRODUCTION_RULES))
    store = SqlitePaperSessionStore(cfg)
    clock = [NOW]
    bus = Mock()
    runner = PaperSessionRunner(cfg, lambda: store, lambda: None, clock=lambda: clock[0])
    runner.register(bus)
    bus.subscribe.assert_any_call(EventType.FEATURE_SNAPSHOT_READY, runner.offer_feature)
    runner.start()
    try:
        wait_for(lambda: runner.snapshot().running)
        runner.offer_signal(signal())
        wait_for(lambda: runner.snapshot().plans == 1)
        clock[0] += timedelta(seconds=2)
        runner.offer_book(book(2))
        wait_for(lambda: runner.snapshot().fills == 1)
        clock[0] += timedelta(seconds=1)
        runner.offer_feature(feature(3, 11))
        wait_for(lambda: runner.snapshot().last_result == "PRODUCTION_POSITION_EVALUATED")
        assert store.read().orders[0].status == "EXIT_PENDING"
        clock[0] += timedelta(seconds=1)
        runner.offer_book(book(4, bid=D("10.9"), ask=D("11")))
        wait_for(lambda: runner.snapshot().fills == 2)
        assert store.read().orders[0].status == "CLOSED"
        bus.publish.assert_not_called()
    finally:
        runner.stop()
    assert not runner.snapshot().error
    bus.unsubscribe.assert_any_call(EventType.FEATURE_SNAPSHOT_READY, runner.offer_feature)


def test_research_runner_does_not_subscribe_to_feature_stream(tmp_path):
    runner = PaperSessionRunner(config(tmp_path), lambda: None, lambda: None)
    bus = Mock()
    runner.register(bus)
    assert EventType.FEATURE_SNAPSHOT_READY not in [call.args[0] for call in bus.subscribe.call_args_list]
    runner.stop()


def test_history_budget_failure_does_not_silently_drop_observations(tmp_path):
    store, service = opened(tmp_path)
    evaluate(service, feature(3, 10.1))

    def seed(account):
        account.orders[0].price_history = tuple(
            (NOW + timedelta(seconds=2, microseconds=i * 100), 10.0) for i in range(2048))
        return "{}"

    store.apply("test-history", "test-history", seed)
    before = encode_account(store.read())
    with pytest.raises(RuntimeError, match="HISTORY_BUDGET_EXCEEDED"):
        evaluate(service, feature(4, 10.1))
    assert encode_account(store.read()) == before


def test_partial_exit_does_not_report_final_pnl_or_allow_reentry(tmp_path):
    store, service = opened(tmp_path)
    evaluate(service, feature(3, 11))
    service.book(book(4, bid=D("10.9"), ask=D("11"), bid_size=1000), NOW + timedelta(seconds=4))
    order = store.read().orders[0]
    assert 0 < order.sold < order.bought and order.status == "EXIT_PENDING"
    held, bought = order.held, order.bought
    service.book(book(5), NOW + timedelta(seconds=5))
    order = store.read().orders[0]
    assert order.bought == bought and order.held < held
    assert order.status == "CLOSED"
