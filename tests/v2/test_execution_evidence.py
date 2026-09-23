import asyncio
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from simple_trade.utils.converters import parse_positive_int
from simple_trade.v2.application.features.feature_engine import FeatureEngine
from simple_trade.v2.application.market_projector import MarketProjector
from simple_trade.v2.application.planning.evidence import execution_evidence
from simple_trade.v2.application.strategy.coordinator import CandidateCoordinator
from simple_trade.v2.domain.enums import DataQuality
from simple_trade.v2.domain.events import QuoteEvent
from simple_trade.v2.domain.market import LotSizeObservation, OrderBookLevel, OrderBookSnapshot
from simple_trade.v2.domain.serialization import to_primitive
from simple_trade.v2.infrastructure.futu_market_adapter import FutuMarketAdapter
from simple_trade.v2.infrastructure.market_reference.lot_cache import LotObservationCache
from tests.v2.test_candidate_strategy import NOW, snapshot
from tests.v2.test_candidate_coordinator import MemoryStores, feature_event
from tests.v2.test_stores_and_runtime import SqliteTestDatabase
from simple_trade.v2.infrastructure.sqlite_event_store import SqliteEventStore
from simple_trade.v2.infrastructure.sqlite_state_store import SqliteStateStore


def resolve(cache, value, at=NOW, code="HK.00100", **kwargs):
    return cache.resolve(code, value, exchange_time=at, received_time=at,
                         source="futu.market_snapshot", realtime=True, **kwargs)


@pytest.mark.parametrize("value", [None, 0, -1, True, False, "", "NaN", "Infinity", 100.5, "1e100000000"])
def test_board_lot_never_guessed_or_truncated(value):
    assert parse_positive_int(value) is None
    assert resolve(LotObservationCache(), value) is None


@pytest.mark.parametrize("value", [100, 100.0, "100", "100.0"])
def test_observed_lot_normalized_to_native_json_integer(value):
    fact = resolve(LotObservationCache(), value)
    assert type(fact.lot_size) is int
    assert json.loads(json.dumps(to_primitive(fact)))["lot_size"] == 100


def test_lot_cache_retains_original_known_time_and_expires():
    cache = LotObservationCache(max_age_seconds=60)
    fact = resolve(cache, 500)
    assert resolve(cache, None, NOW + timedelta(seconds=59)) is fact
    assert resolve(cache, None, NOW + timedelta(seconds=61)) is None
    assert resolve(cache, None, NOW + timedelta(days=1)) is None


def test_lot_cache_never_uses_future_known_or_later_quote_for_past_decision():
    cache = LotObservationCache()
    assert resolve(cache, 100, NOW + timedelta(seconds=10)) is not None
    assert resolve(cache, None, NOW) is None
    assert resolve(cache, 500, NOW) is None
    assert resolve(cache, None, NOW + timedelta(seconds=11)).lot_size == 100
    assert cache.resolve("HK.00100", 500, exchange_time=NOW + timedelta(seconds=20),
                         received_time=NOW, source="test", realtime=True) is None
    assert cache.resolve("HK.00100", 500, exchange_time=NOW, received_time=NOW,
                         source="test", realtime=False) is None


def test_lot_cache_is_bounded_and_cross_day_cache_is_not_reused():
    cache = LotObservationCache(capacity=1, max_age_seconds=86400)
    resolve(cache, 100)
    resolve(cache, 200, code="HK.00700")
    assert resolve(cache, None) is None
    midnight = NOW.replace(hour=23, minute=59)
    resolve(cache, 100, midnight)
    assert resolve(cache, None, midnight + timedelta(minutes=2)) is None


def complete_snapshot():
    item = snapshot()
    fact = LotSizeObservation(stock_code=item.stock_code, lot_size=100,
                              observed_at=NOW, quote_exchange_time=NOW, source="test.snapshot")
    book = OrderBookSnapshot(stock_code=item.stock_code, exchange_time=NOW,
                            bid_levels=(OrderBookLevel(price=100.9, volume=1000),),
                            ask_levels=(OrderBookLevel(price=101.1, volume=1000),),
                            quality=DataQuality.GOOD)
    return replace(item, quote=replace(item.quote, lot_size_observation=fact),
                   order_book=book, order_book_received_at=NOW)


def test_even_complete_market_facts_do_not_authorize_order_without_plan():
    result = execution_evidence(complete_snapshot(), as_of=NOW)
    assert result.market_data_ready
    assert not result.execution_allowed
    assert result.entry_plan_status == "NOT_GENERATED"
    assert result.blockers == ("ENTRY_PLAN_NOT_GENERATED",)


def test_existing_numeric_lot_without_provenance_and_no_book_remain_missing():
    result = execution_evidence(snapshot(), as_of=NOW)
    assert not result.market_data_ready
    assert "LOT_SIZE_PROVENANCE_MISSING" in result.blockers
    assert "ORDER_BOOK_MISSING" in result.blockers


@pytest.mark.parametrize("change,reason", [
    ({"order_book_received_at": NOW + timedelta(seconds=1)}, "ORDER_BOOK_RECEIPT_INVALID_OR_STALE"),
    ({"order_book_received_at": None}, "ORDER_BOOK_RECEIPT_MISSING"),
    ({"computed_at": NOW + timedelta(seconds=1)}, "FEATURE_NOT_YET_KNOWN"),
])
def test_missing_or_future_knowledge_is_blocked(change, reason):
    result = execution_evidence(replace(complete_snapshot(), **change), as_of=NOW)
    assert reason in result.blockers


@pytest.mark.parametrize("change,reason", [
    ({"timestamp_basis": "LOCAL_RECEIPT"}, "ORDER_BOOK_EXCHANGE_TIME_UNVERIFIED"),
    ({"bid_levels": ()}, "ORDER_BOOK_NOT_EXECUTABLE"),
    ({"ask_levels": (OrderBookLevel(price=100, volume=1000),)}, "ORDER_BOOK_NOT_EXECUTABLE"),
    ({"ask_levels": (OrderBookLevel(price=101.1, volume=0),)}, "ORDER_BOOK_NOT_EXECUTABLE"),
    ({"quality": DataQuality.DEGRADED}, "ORDER_BOOK_QUALITY_INCOMPLETE"),
])
def test_book_quality_and_liquidity_are_not_assumed(change, reason):
    item = complete_snapshot()
    result = execution_evidence(replace(item, order_book=replace(item.order_book, **change)), as_of=NOW)
    assert reason in result.blockers


def test_stale_market_and_lot_evidence_block_execution_only():
    item = complete_snapshot()
    result = execution_evidence(item, as_of=NOW + timedelta(seconds=4))
    assert "QUOTE_TIME_INVALID_OR_STALE" in result.blockers
    assert "ORDER_BOOK_TIME_INVALID_OR_STALE" in result.blockers
    result = execution_evidence(item, as_of=NOW + timedelta(days=1))
    assert "LOT_SIZE_TIME_INVALID_OR_STALE" in result.blockers


def test_adapter_cache_and_projector_preserve_book_receipt_and_lot_provenance():
    adapter = FutuMarketAdapter(strategy_version="test")
    row = {"code": "HK.00100", "last_price": 101, "prev_close": 100,
           "data_date": NOW.date().isoformat(), "data_time": "10:00:00",
           "lot_size": 500, "lot_size_source": "futu.market_snapshot"}
    first = next(e for e in adapter.adapt_quote(row, received_time=NOW) if isinstance(e, QuoteEvent))
    later = NOW + timedelta(seconds=2)
    second = next(e for e in adapter.adapt_quote({**row, "data_time": "10:00:02", "lot_size": None},
                                               received_time=later) if isinstance(e, QuoteEvent))
    assert second.quote.lot_size == 500
    assert second.quote.lot_size_observation.observed_at == NOW
    assert second.quote.lot_size_observation.source == "futu.market_snapshot"
    events = adapter.adapt_order_book("HK.00100", {"Bid": [(100.9, 1000, 1)], "Ask": [(101.1, 1000, 1)]},
                                      received_time=NOW)
    projector = MarketProjector()
    projector.on_quote(first)
    for event in events:
        projector.on_order_book(event)
    projector.on_quote(second)
    projection = projector.get("HK.00100")
    assert projection.order_book_received_at == NOW
    assert projection.order_book.timestamp_basis == "LOCAL_RECEIPT"
    engine = FeatureEngine(projector, strategy_version="test")
    result = engine.build_snapshot(projection, later)
    assert result.order_book is projection.order_book
    assert result.order_book_received_at == NOW
    older = replace(events[0], received_time=NOW - timedelta(seconds=1))
    projector.on_order_book(older)
    assert projector.get("HK.00100").order_book_received_at == NOW


def test_candidate_transaction_contains_evidence_without_promoting_signal():
    async def run():
        stores = MemoryStores()
        coordinator = CandidateCoordinator(stores, stores, strategy_version="test-v2")
        await coordinator.start()
        coordinator.on_feature_snapshot(feature_event(complete_snapshot(), "evidence"))
        await coordinator.stop(drain=True)
        event = stores.events[0]
        assert event.payload["entry_plan"] is None
        assert event.payload["execution_evidence"]["execution_allowed"] is False
        assert event.payload["execution_evidence"]["entry_plan_status"] == "NOT_GENERATED"
        assert event.payload["feature_snapshot"]["quote"]["lot_size_observation"]["lot_size"] == 100
        assert event.payload["feature_snapshot"]["order_book"]["timestamp_basis"] == "EXCHANGE"
        assert not event.payload["alert_eligible"]
    asyncio.run(run())


def test_decision_evidence_round_trips_in_existing_atomic_transaction(tmp_path):
    async def run():
        db = SqliteTestDatabase(tmp_path / "evidence.db")
        store, states = SqliteEventStore(db), SqliteStateStore(db)
        coordinator = CandidateCoordinator(store, states, strategy_version="test-v2")
        await coordinator.start()
        coordinator.on_feature_snapshot(feature_event(complete_snapshot(), "durable-evidence"))
        await coordinator.stop(drain=True)
        loaded = await store.load("HK.00100", "test-v2")
        assert len(loaded) == 1
        payload = loaded[0].payload
        assert payload["execution_evidence"]["blockers"] == ("ENTRY_PLAN_NOT_GENERATED",)
        assert payload["feature_snapshot"]["order_book_received_at"] == NOW.isoformat()
        assert payload["feature_snapshot"]["quote"]["lot_size_observation"]["observed_at"] == NOW.isoformat()
        state = await states.get("HK.00100", "test-v2")
        assert state.last_event_id == loaded[0].event_id
    asyncio.run(run())
