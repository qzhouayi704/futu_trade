"""Shadow feature projector that assembles one immutable snapshot per quote."""

from dataclasses import dataclass
from datetime import datetime
import threading

from ...domain.enums import DataQuality, EventType, TickDirection
from ...domain.events import FeatureSnapshotEvent, OrderBookEvent, QuoteEvent, TickEvent
from ...domain.features import BreadthMember, CapitalBaseline, DailyBar, FeatureSnapshot
from ...domain.market import QuoteSnapshot, TickAggregate
from ..event_bus import EventBus
from ..market_projector import MarketProjection, MarketProjector
from .base_features import (
    ActivityFeature,
    BreadthFeature,
    LiquidityFeature,
    PricePositionFeature,
)
from .capital_windows import CapitalWindowEngine
from .price_acceptance import PriceAcceptanceFeature, PriceTape
from .quality import worst_quality


@dataclass(frozen=True, slots=True)
class FeatureEngineStats:
    stocks: int
    quote_updates: int
    tick_updates: int
    snapshots_built: int
    feature_events_published: int
    invalid_snapshots: int


class FeatureEngine:
    def __init__(
        self,
        projector: MarketProjector,
        *,
        strategy_version: str,
        schema_version: int = 1,
    ) -> None:
        self._projector = projector
        self._strategy_version = strategy_version
        self._schema_version = schema_version
        self.capital = CapitalWindowEngine()
        self.price_tape = PriceTape()
        self._activity = ActivityFeature()
        self._liquidity = LiquidityFeature()
        self._position = PricePositionFeature()
        self._breadth = BreadthFeature()
        self._acceptance = PriceAcceptanceFeature()
        self._daily_bars: dict[str, tuple[DailyBar, ...]] = {}
        self._universe: dict[str, QuoteSnapshot] = {}
        self._latest: dict[str, FeatureSnapshot] = {}
        self._lock = threading.RLock()
        self._bus: EventBus | None = None
        self._quote_updates = 0
        self._tick_updates = 0
        self._snapshots_built = 0
        self._feature_events_published = 0
        self._invalid_snapshots = 0

    def register(self, bus: EventBus) -> None:
        if self._bus is bus:
            return
        if self._bus is not None:
            raise RuntimeError("FeatureEngine already registered")
        bus.subscribe(EventType.QUOTE_UPDATED, self.on_quote)
        bus.subscribe(EventType.TICK_RECEIVED, self.on_tick)
        bus.subscribe(EventType.ORDER_BOOK_UPDATED, self.on_order_book)
        self._bus = bus

    def unregister(self) -> None:
        bus = self._bus
        if bus is None:
            return
        bus.unsubscribe(EventType.QUOTE_UPDATED, self.on_quote)
        bus.unsubscribe(EventType.TICK_RECEIVED, self.on_tick)
        bus.unsubscribe(EventType.ORDER_BOOK_UPDATED, self.on_order_book)
        self._bus = None

    def stage_quote_universe(self, quotes: tuple[QuoteSnapshot, ...]) -> None:
        with self._lock:
            for quote in quotes:
                self._universe[quote.stock_code] = quote

    def seed_daily_bars(self, bars: tuple[DailyBar, ...]) -> None:
        grouped: dict[str, list[DailyBar]] = {}
        for bar in bars:
            grouped.setdefault(bar.stock_code, []).append(bar)
        with self._lock:
            for code, rows in grouped.items():
                self._daily_bars[code] = tuple(sorted(rows, key=lambda row: row.as_of)[-30:])

    def missing_daily_bar_codes(self, stock_codes: tuple[str, ...]) -> tuple[str, ...]:
        with self._lock:
            return tuple(
                code for code in dict.fromkeys(stock_codes)
                if code and code not in self._daily_bars
            )

    def seed_capital(self, aggregates: tuple[TickAggregate, ...]) -> None:
        for aggregate in aggregates:
            self.capital.seed(aggregate)

    def seed_capital_baselines(self, baselines: tuple[CapitalBaseline, ...]) -> None:
        self.capital.set_baselines(baselines)

    def on_tick(self, event) -> None:
        if not isinstance(event, TickEvent):
            return
        self.price_tape.on_tick(event.tick)
        update = self.capital.on_tick(event.tick)
        if (
            update.is_large_order
            and update.is_independent_event
            and event.tick.direction is TickDirection.BUY
        ):
            self.price_tape.confirm(
                event.stock_code,
                event.tick.price,
                event.exchange_time,
            )
        with self._lock:
            self._tick_updates += 1

    def on_quote(self, event) -> None:
        if not isinstance(event, QuoteEvent):
            return
        self.price_tape.observe_price(
            event.stock_code,
            event.quote.last_price,
            event.exchange_time,
        )
        with self._lock:
            self._universe[event.stock_code] = event.quote
            self._quote_updates += 1
        projection = self._projector.get(event.stock_code)
        if projection is None:
            return
        snapshot = self.build_snapshot(projection, event.exchange_time)
        with self._lock:
            self._latest[event.stock_code] = snapshot
            self._snapshots_built += 1
            if snapshot.quality is DataQuality.INVALID:
                self._invalid_snapshots += 1
        bus = self._bus
        if bus is None:
            return
        published = bus.publish_nowait(
            FeatureSnapshotEvent(
                event_type=EventType.FEATURE_SNAPSHOT_READY,
                stock_code=event.stock_code,
                exchange_time=event.exchange_time,
                received_time=event.received_time,
                source="v2.feature-engine",
                schema_version=self._schema_version,
                strategy_version=self._strategy_version,
                sequence=event.sequence,
                correlation_id=event.correlation_id,
                snapshot=snapshot,
            )
        )
        if published:
            with self._lock:
                self._feature_events_published += 1

    def on_order_book(self, event) -> None:
        if not isinstance(event, OrderBookEvent):
            return
        # Liquidity is rebuilt on the next quote cycle, keeping feature event volume bounded.

    def build_snapshot(
        self,
        projection: MarketProjection,
        as_of: datetime,
    ) -> FeatureSnapshot:
        quote = projection.quote
        if quote is None:
            raise ValueError("FeatureSnapshot requires a quote")
        activity = self._activity.calculate(quote)
        liquidity = self._liquidity.calculate(quote, projection.order_book)
        with self._lock:
            bars = self._daily_bars.get(quote.stock_code, ())
            members = self._breadth_members(as_of, quote.stock_code)
        price_position = self._position.calculate(
            quote.stock_code,
            as_of,
            quote.last_price,
            bars,
        )
        market_context = self._breadth.calculate(
            quote.stock_code,
            quote.sector_code,
            as_of,
            members,
        )
        windows = self.capital.snapshots(quote.stock_code, as_of)
        tape = self.price_tape.snapshot(quote.stock_code, as_of)
        acceptance = self._acceptance.calculate(
            as_of=as_of,
            current_price=quote.last_price,
            tape=tape,
        )

        missing: list[str] = []
        if activity.turnover_rate is None:
            missing.append("activity.turnover_rate")
        if liquidity.spread_pct is None:
            missing.append("liquidity.spread")
        if liquidity.lot_size is None:
            missing.append("liquidity.lot_size")
        if price_position.quality is DataQuality.INVALID:
            missing.append("price_position.daily_bars")
        if market_context.quality is DataQuality.INVALID:
            missing.append("market_context.universe")
        elif market_context.sector_breadth is None:
            missing.append("market_context.sector")
        if all(window.quality is DataQuality.INVALID for window in windows):
            missing.append("capital_windows.tick_stream")
        if acceptance.confirmation_price is None:
            missing.append("price_acceptance.confirmation_price")
        if acceptance.vwap is None:
            missing.append("price_acceptance.vwap")

        quality = worst_quality(
            projection.quality,
            quote.quality,
            activity.quality,
            liquidity.quality,
            price_position.quality,
            market_context.quality,
            *(window.quality for window in windows),
            acceptance.quality,
        )
        return FeatureSnapshot(
            stock_code=quote.stock_code,
            computed_at=as_of,
            quote=quote,
            tick_windows=windows,
            market_context=market_context,
            price_position=price_position,
            activity_score=activity.score,
            liquidity_score=liquidity.score,
            price_acceptance_score=acceptance.score,
            quality=quality,
            activity=activity,
            liquidity=liquidity,
            price_acceptance=acceptance,
            missing_fields=tuple(dict.fromkeys(missing)),
        )

    def latest(self, stock_code: str) -> FeatureSnapshot | None:
        with self._lock:
            return self._latest.get(stock_code.strip().upper())

    def snapshot(self) -> FeatureEngineStats:
        with self._lock:
            return FeatureEngineStats(
                stocks=len(self._latest),
                quote_updates=self._quote_updates,
                tick_updates=self._tick_updates,
                snapshots_built=self._snapshots_built,
                feature_events_published=self._feature_events_published,
                invalid_snapshots=self._invalid_snapshots,
            )

    def _breadth_members(
        self,
        as_of: datetime,
        stock_code: str,
    ) -> tuple[BreadthMember, ...]:
        market = "US" if stock_code.startswith("US.") else "HK"
        rows: list[BreadthMember] = []
        for quote in self._universe.values():
            quote_market = "US" if quote.stock_code.startswith("US.") else "HK"
            age = abs((as_of - quote.exchange_time).total_seconds())
            if quote_market != market or quote.exchange_time.date() != as_of.date() or age > 180:
                continue
            change = (
                (quote.last_price / quote.prev_close - 1.0) * 100.0
                if quote.prev_close > 0
                else 0.0
            )
            rows.append(
                BreadthMember(
                    stock_code=quote.stock_code,
                    change_pct=change,
                    turnover=quote.turnover,
                    sector_code=quote.sector_code,
                    eligible=quote.quality is not DataQuality.INVALID,
                )
            )
        return tuple(rows)
