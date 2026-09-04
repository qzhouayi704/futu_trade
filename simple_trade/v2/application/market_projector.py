"""Atomic in-memory read model for V2 market facts."""

from dataclasses import dataclass, replace
from datetime import datetime
import threading

from ..domain.enums import DataQuality, EventType
from ..domain.events import DataQualityEvent, OrderBookEvent, QuoteEvent, TickEvent
from ..domain.market import OrderBookSnapshot, QuoteSnapshot, TickAggregate, TickTrade
from .event_bus import EventBus


@dataclass(frozen=True, slots=True)
class MarketProjection:
    stock_code: str
    quote: QuoteSnapshot | None = None
    last_tick: TickTrade | None = None
    order_book: OrderBookSnapshot | None = None
    restored_capital: TickAggregate | None = None
    quality: DataQuality = DataQuality.GOOD
    quality_reasons: tuple[str, ...] = ()
    last_sequence: int | None = None
    sequence_gap_count: int = 0
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MarketProjectorStats:
    stocks: int
    quote_updates: int
    tick_updates: int
    order_book_updates: int
    quality_events: int
    restored_capital_stocks: int


class MarketProjector:
    """Replace one immutable stock snapshot under one lock per event."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stocks: dict[str, MarketProjection] = {}
        self._quote_updates = 0
        self._tick_updates = 0
        self._order_book_updates = 0
        self._quality_events = 0
        self._restored_capital_stocks = 0
        self._registered_bus: EventBus | None = None

    def register(self, bus: EventBus) -> None:
        if self._registered_bus is bus:
            return
        if self._registered_bus is not None:
            raise RuntimeError("MarketProjector already registered")
        bus.subscribe(EventType.QUOTE_UPDATED, self.on_quote)
        bus.subscribe(EventType.TICK_RECEIVED, self.on_tick)
        bus.subscribe(EventType.ORDER_BOOK_UPDATED, self.on_order_book)
        bus.subscribe(EventType.DATA_QUALITY_CHANGED, self.on_quality)
        self._registered_bus = bus

    def unregister(self) -> None:
        bus = self._registered_bus
        if bus is None:
            return
        bus.unsubscribe(EventType.QUOTE_UPDATED, self.on_quote)
        bus.unsubscribe(EventType.TICK_RECEIVED, self.on_tick)
        bus.unsubscribe(EventType.ORDER_BOOK_UPDATED, self.on_order_book)
        bus.unsubscribe(EventType.DATA_QUALITY_CHANGED, self.on_quality)
        self._registered_bus = None

    def on_quote(self, event) -> None:
        if not isinstance(event, QuoteEvent):
            return
        with self._lock:
            current = self._current(event.stock_code)
            quality, reasons = self._component_quality(
                event.quote,
                current.last_tick,
                current.order_book,
            )
            self._stocks[event.stock_code] = replace(
                current,
                quote=event.quote,
                quality=quality,
                quality_reasons=reasons,
                updated_at=event.received_time,
            )
            self._quote_updates += 1

    def on_tick(self, event) -> None:
        if not isinstance(event, TickEvent):
            return
        with self._lock:
            current = self._current(event.stock_code)
            quality, reasons = self._component_quality(
                current.quote,
                event.tick,
                current.order_book,
            )
            self._stocks[event.stock_code] = replace(
                current,
                last_tick=event.tick,
                quality=quality,
                quality_reasons=reasons,
                last_sequence=event.sequence if event.sequence is not None else current.last_sequence,
                sequence_gap_count=current.sequence_gap_count,
                updated_at=event.received_time,
            )
            self._tick_updates += 1

    def on_order_book(self, event) -> None:
        if not isinstance(event, OrderBookEvent):
            return
        with self._lock:
            current = self._current(event.stock_code)
            quality, reasons = self._component_quality(
                current.quote,
                current.last_tick,
                event.order_book,
            )
            self._stocks[event.stock_code] = replace(
                current,
                order_book=event.order_book,
                quality=quality,
                quality_reasons=reasons,
                updated_at=event.received_time,
            )
            self._order_book_updates += 1

    def on_quality(self, event) -> None:
        if not isinstance(event, DataQualityEvent):
            return
        with self._lock:
            current = self._current(event.stock_code)
            quality, reasons = self._merge_quality(current, event.quality, event.reason_codes)
            self._stocks[event.stock_code] = replace(
                current,
                quality=quality,
                quality_reasons=reasons,
                updated_at=event.received_time,
            )
            self._quality_events += 1

    def restore_capital(self, aggregates: tuple[TickAggregate, ...]) -> None:
        with self._lock:
            for aggregate in aggregates:
                current = self._current(aggregate.stock_code)
                quality, reasons = self._merge_quality(
                    current,
                    aggregate.quality,
                    ("CAPITAL_WINDOW_RESTORED_PARTIALLY",),
                )
                self._stocks[aggregate.stock_code] = replace(
                    current,
                    restored_capital=aggregate,
                    quality=quality,
                    quality_reasons=reasons,
                    last_sequence=aggregate.last_sequence,
                    updated_at=aggregate.as_of,
                )
            self._restored_capital_stocks += len(aggregates)

    def get(self, stock_code: str) -> MarketProjection | None:
        with self._lock:
            return self._stocks.get(stock_code.strip().upper())

    def all(self) -> tuple[MarketProjection, ...]:
        with self._lock:
            return tuple(self._stocks[code] for code in sorted(self._stocks))

    def snapshot(self) -> MarketProjectorStats:
        with self._lock:
            return MarketProjectorStats(
                stocks=len(self._stocks),
                quote_updates=self._quote_updates,
                tick_updates=self._tick_updates,
                order_book_updates=self._order_book_updates,
                quality_events=self._quality_events,
                restored_capital_stocks=self._restored_capital_stocks,
            )

    def _current(self, stock_code: str) -> MarketProjection:
        return self._stocks.get(stock_code) or MarketProjection(stock_code=stock_code)

    @staticmethod
    def _merge_quality(
        current: MarketProjection,
        incoming: DataQuality,
        reasons: tuple[str, ...],
    ) -> tuple[DataQuality, tuple[str, ...]]:
        rank = {DataQuality.GOOD: 0, DataQuality.DEGRADED: 1, DataQuality.INVALID: 2}
        quality = incoming if rank[incoming] > rank[current.quality] else current.quality
        merged = tuple(dict.fromkeys((*current.quality_reasons, *reasons)))
        return quality, merged[-20:]

    @staticmethod
    def _component_quality(
        quote: QuoteSnapshot | None,
        tick: TickTrade | None,
        order_book: OrderBookSnapshot | None,
    ) -> tuple[DataQuality, tuple[str, ...]]:
        components = (
            (quote, "QUOTE_DEGRADED"),
            (tick, "TICK_DEGRADED"),
            (order_book, "ORDER_BOOK_DEGRADED"),
        )
        available = [(item.quality, reason) for item, reason in components if item is not None]
        if not available:
            return DataQuality.GOOD, ()
        rank = {DataQuality.GOOD: 0, DataQuality.DEGRADED: 1, DataQuality.INVALID: 2}
        quality = max((value for value, _ in available), key=rank.__getitem__)
        reasons = tuple(reason for value, reason in available if value is not DataQuality.GOOD)
        return quality, reasons
