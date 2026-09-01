"""Pure Futu payload adapter for V2 market events.

The adapter has no Futu SDK dependency and performs no I/O. It only validates,
normalizes, deduplicates, and creates immutable domain events.
"""

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import threading

from ..domain.enums import DataQuality, EventType, TickDirection
from ..domain.events import (
    DataQualityEvent,
    DomainEvent,
    OrderBookEvent,
    QuoteEvent,
    TickEvent,
)
from ..domain.market import (
    OrderBookLevel,
    OrderBookSnapshot,
    QuoteSnapshot,
    TickTrade,
)
from ..domain.serialization import require_aware, require_stock_code


@dataclass(frozen=True, slots=True)
class FutuAdapterStats:
    quotes: int
    ticks: int
    order_books: int
    duplicates: int
    sequence_gaps: int
    out_of_order: int
    invalid: int


class FutuMarketAdapter:
    """Convert Futu-shaped mappings into deterministic V2 market events."""

    def __init__(
        self,
        *,
        strategy_version: str,
        schema_version: int = 1,
        no_sequence_dedupe_capacity: int = 20_000,
    ) -> None:
        if not strategy_version.strip():
            raise ValueError("strategy_version cannot be empty")
        if schema_version < 1 or no_sequence_dedupe_capacity < 1:
            raise ValueError("schema_version and dedupe capacity must be positive")
        self._strategy_version = strategy_version
        self._schema_version = schema_version
        self._dedupe_capacity = no_sequence_dedupe_capacity
        self._lock = threading.RLock()
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._seen_without_sequence: dict[tuple[str, str], set[tuple[object, ...]]] = defaultdict(set)
        self._seen_order: dict[tuple[str, str], deque[tuple[object, ...]]] = defaultdict(deque)
        self._quotes = 0
        self._ticks = 0
        self._order_books = 0
        self._duplicates = 0
        self._sequence_gaps = 0
        self._out_of_order = 0
        self._invalid = 0

    def adapt_quote(
        self,
        row: Mapping[str, object],
        *,
        received_time: datetime | None = None,
    ) -> tuple[DomainEvent, ...]:
        received = self._received_time(received_time)
        try:
            code = require_stock_code(str(row.get("code") or row.get("stock_code") or ""))
            exchange_time, used_fallback = self._quote_time(row, code, received)
            last_price = self._float(row, "last_price", "current_price", "price")
            prev_close = self._float(row, "prev_close", "prev_close_price")
            if last_price <= 0 or prev_close < 0:
                raise ValueError("invalid quote price")
            quality = DataQuality.DEGRADED if used_fallback or row.get("is_realtime") is False else DataQuality.GOOD
            quote = QuoteSnapshot(
                stock_code=code,
                exchange_time=exchange_time,
                last_price=last_price,
                prev_close=prev_close,
                open_price=self._float(row, "open_price"),
                high_price=self._float(row, "high_price"),
                low_price=self._float(row, "low_price"),
                volume=self._int(row, "volume"),
                turnover=self._float(row, "turnover"),
                turnover_rate=self._optional_nonnegative_float(row.get("turnover_rate")),
                amplitude=self._optional_nonnegative_float(row.get("amplitude")),
                lot_size=self._optional_positive_int(row.get("lot_size")),
                sector_code=str(
                    row.get("plate_code") or row.get("plate_name") or ""
                ).strip() or None,
                quality=quality,
            )
            event = QuoteEvent(
                event_type=EventType.QUOTE_UPDATED,
                stock_code=code,
                exchange_time=exchange_time,
                received_time=received,
                source="futu.quote",
                schema_version=self._schema_version,
                strategy_version=self._strategy_version,
                quote=quote,
            )
        except (TypeError, ValueError, OverflowError):
            with self._lock:
                self._invalid += 1
            return ()

        events: list[DomainEvent] = []
        if quality is not DataQuality.GOOD:
            reason = "QUOTE_TIME_FALLBACK" if used_fallback else "QUOTE_NOT_REALTIME"
            events.append(self._quality_event(event, quality, (reason,)))
        events.append(event)
        with self._lock:
            self._quotes += 1
        return tuple(events)

    def adapt_ticker(
        self,
        row: Mapping[str, object],
        *,
        stock_code: str | None = None,
        received_time: datetime | None = None,
    ) -> tuple[DomainEvent, ...]:
        received = self._received_time(received_time)
        try:
            code = require_stock_code(stock_code or str(row.get("code") or row.get("stock_code") or ""))
            exchange_time, used_fallback = self._parse_time(row.get("time"), code, received)
            price = self._float(row, "price", "last_price")
            volume = self._int(row, "volume")
            if price <= 0 or volume <= 0:
                raise ValueError("invalid ticker price or volume")
            turnover = self._float(row, "turnover") or price * volume
            sequence = self._optional_positive_int(row.get("sequence"))
            direction = self._direction(row.get("ticker_direction", row.get("direction")))
        except (TypeError, ValueError, OverflowError):
            with self._lock:
                self._invalid += 1
            return ()

        quality = DataQuality.DEGRADED if used_fallback else DataQuality.GOOD
        reasons: list[str] = ["TICK_TIME_FALLBACK"] if used_fallback else []
        day_key = (code, exchange_time.date().isoformat())
        with self._lock:
            self._discard_previous_days(code, day_key)
            last_sequence = self._last_sequence.get(day_key)
            if sequence is not None:
                if last_sequence is not None and sequence == last_sequence:
                    self._duplicates += 1
                    return ()
                if last_sequence is not None and sequence < last_sequence:
                    self._out_of_order += 1
                    quality_event = self._standalone_quality_event(
                        code=code,
                        exchange_time=exchange_time,
                        received_time=received,
                        sequence=sequence,
                        reason_codes=("OUT_OF_ORDER_SEQUENCE",),
                    )
                    return (quality_event,)
                if last_sequence is not None and sequence > last_sequence + 1:
                    missing = sequence - last_sequence - 1
                    self._sequence_gaps += missing
                    quality = DataQuality.DEGRADED
                    reasons.append(f"SEQUENCE_GAP:{last_sequence + 1}-{sequence - 1}")
                self._last_sequence[day_key] = sequence
            else:
                business_key = (
                    exchange_time.isoformat(),
                    price,
                    volume,
                    direction.value,
                )
                if business_key in self._seen_without_sequence[day_key]:
                    self._duplicates += 1
                    return ()
                self._remember_business_key(day_key, business_key)

        tick = TickTrade(
            stock_code=code,
            exchange_time=exchange_time,
            price=price,
            volume=volume,
            turnover=turnover,
            direction=direction,
            sequence=sequence,
            quality=quality,
        )
        event = TickEvent(
            event_type=EventType.TICK_RECEIVED,
            stock_code=code,
            exchange_time=exchange_time,
            received_time=received,
            source="futu.ticker",
            schema_version=self._schema_version,
            strategy_version=self._strategy_version,
            sequence=sequence,
            tick=tick,
        )
        events: list[DomainEvent] = []
        if quality is not DataQuality.GOOD:
            events.append(self._quality_event(event, quality, tuple(reasons)))
        events.append(event)
        with self._lock:
            self._ticks += 1
        return tuple(events)

    def adapt_order_book(
        self,
        stock_code: str,
        data: object,
        *,
        received_time: datetime | None = None,
    ) -> tuple[DomainEvent, ...]:
        received = self._received_time(received_time)
        try:
            code = require_stock_code(stock_code)
            bids = self._levels(data, "Bid", "bid_levels")
            asks = self._levels(data, "Ask", "ask_levels")
            if not bids and not asks:
                quality = DataQuality.INVALID
                reasons = ("ORDER_BOOK_EMPTY",)
            elif not bids or not asks:
                quality = DataQuality.DEGRADED
                reasons = ("ORDER_BOOK_ONE_SIDED",)
            else:
                quality = DataQuality.GOOD
                reasons = ()
            snapshot = OrderBookSnapshot(
                stock_code=code,
                exchange_time=received,
                bid_levels=bids,
                ask_levels=asks,
                quality=quality,
            )
            event = OrderBookEvent(
                event_type=EventType.ORDER_BOOK_UPDATED,
                stock_code=code,
                exchange_time=received,
                received_time=received,
                source="futu.order_book",
                schema_version=self._schema_version,
                strategy_version=self._strategy_version,
                order_book=snapshot,
            )
        except (TypeError, ValueError, OverflowError):
            with self._lock:
                self._invalid += 1
            return ()

        events: list[DomainEvent] = []
        if quality is not DataQuality.GOOD:
            events.append(self._quality_event(event, quality, reasons))
        events.append(event)
        with self._lock:
            self._order_books += 1
        return tuple(events)

    def snapshot(self) -> FutuAdapterStats:
        with self._lock:
            return FutuAdapterStats(
                quotes=self._quotes,
                ticks=self._ticks,
                order_books=self._order_books,
                duplicates=self._duplicates,
                sequence_gaps=self._sequence_gaps,
                out_of_order=self._out_of_order,
                invalid=self._invalid,
            )

    def _remember_business_key(
        self,
        day_key: tuple[str, str],
        business_key: tuple[object, ...],
    ) -> None:
        seen = self._seen_without_sequence[day_key]
        order = self._seen_order[day_key]
        seen.add(business_key)
        order.append(business_key)
        while len(order) > self._dedupe_capacity:
            seen.discard(order.popleft())

    def _discard_previous_days(self, code: str, current_key: tuple[str, str]) -> None:
        stale_keys = {
            key
            for key in (
                *self._last_sequence.keys(),
                *self._seen_without_sequence.keys(),
            )
            if key[0] == code and key != current_key
        }
        for key in stale_keys:
            self._last_sequence.pop(key, None)
            self._seen_without_sequence.pop(key, None)
            self._seen_order.pop(key, None)

    def _quality_event(
        self,
        event: DomainEvent,
        quality: DataQuality,
        reason_codes: tuple[str, ...],
    ) -> DataQualityEvent:
        return self._standalone_quality_event(
            code=event.stock_code,
            exchange_time=event.exchange_time,
            received_time=event.received_time,
            sequence=event.sequence,
            reason_codes=reason_codes,
        )

    def _standalone_quality_event(
        self,
        *,
        code: str,
        exchange_time: datetime,
        received_time: datetime,
        sequence: int | None,
        reason_codes: tuple[str, ...],
    ) -> DataQualityEvent:
        return DataQualityEvent(
            event_type=EventType.DATA_QUALITY_CHANGED,
            stock_code=code,
            exchange_time=exchange_time,
            received_time=received_time,
            source="futu.adapter",
            schema_version=self._schema_version,
            strategy_version=self._strategy_version,
            sequence=sequence,
            quality=DataQuality.DEGRADED,
            reason_codes=reason_codes,
        )

    @staticmethod
    def _received_time(value: datetime | None) -> datetime:
        received = value or datetime.now(timezone.utc)
        require_aware(received, "received_time")
        return received

    def _quote_time(
        self,
        row: Mapping[str, object],
        code: str,
        received: datetime,
    ) -> tuple[datetime, bool]:
        raw = row.get("exchange_time")
        if raw:
            return self._parse_time(raw, code, received)
        data_date = str(row.get("data_date") or "").strip()
        data_time = str(row.get("data_time") or row.get("update_time") or "").strip()
        if data_date and data_time:
            return self._parse_time(f"{data_date} {data_time}", code, received)
        if data_time:
            parsed, _ = self._parse_time(data_time, code, received)
            return parsed, True
        parsed, _ = self._parse_time(row.get("last_update"), code, received)
        return parsed, True

    @classmethod
    def _parse_time(
        cls,
        value: object,
        code: str,
        received: datetime,
    ) -> tuple[datetime, bool]:
        market_tz = cls._market_timezone(code)
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value or "").strip()
            if not text or text.lower() in {"none", "nan", "nat", "null"}:
                return received.astimezone(market_tz), True
            try:
                parsed = datetime.fromisoformat(text.replace("T", " ", 1))
            except ValueError:
                try:
                    parsed_time = time.fromisoformat(text)
                except ValueError:
                    return received.astimezone(market_tz), True
                local_day = received.astimezone(market_tz).date()
                parsed = datetime.combine(local_day, parsed_time)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=market_tz)
        return parsed.astimezone(market_tz), False

    @staticmethod
    def _market_timezone(code: str):
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo("America/New_York" if code.startswith("US.") else "Asia/Hong_Kong")
        except Exception:
            return timezone(timedelta(hours=-5 if code.startswith("US.") else 8))

    @staticmethod
    def _float(row: Mapping[str, object], *names: str) -> float:
        for name in names:
            value = row.get(name)
            if value is not None and str(value).lower() not in {"", "nan", "none"}:
                return float(value)
        return 0.0

    @staticmethod
    def _int(row: Mapping[str, object], *names: str) -> int:
        for name in names:
            value = row.get(name)
            if value is not None and str(value).lower() not in {"", "nan", "none"}:
                return int(float(value))
        return 0

    @staticmethod
    def _optional_positive_int(value: object) -> int | None:
        if value is None or str(value).lower() in {"", "nan", "none"}:
            return None
        parsed = int(float(value))
        return parsed if parsed > 0 else None

    @staticmethod
    def _optional_nonnegative_float(value: object) -> float | None:
        if value is None or str(value).lower() in {"", "nan", "none"}:
            return None
        parsed = float(value)
        return parsed if parsed >= 0 else None

    @staticmethod
    def _direction(value: object) -> TickDirection:
        direction = str(value or "").upper()
        if direction in {"BUY", "BULL"}:
            return TickDirection.BUY
        if direction in {"SELL", "BEAR"}:
            return TickDirection.SELL
        return TickDirection.NEUTRAL

    @classmethod
    def _levels(
        cls,
        data: object,
        mapping_key: str,
        attribute_name: str,
    ) -> tuple[OrderBookLevel, ...]:
        if isinstance(data, Mapping):
            raw_levels = data.get(mapping_key, ())
        else:
            raw_levels = getattr(data, attribute_name, ())
        levels: list[OrderBookLevel] = []
        if not isinstance(raw_levels, Sequence):
            return ()
        for item in raw_levels[:10]:
            if isinstance(item, Mapping):
                price = float(item.get("price") or 0)
                volume = int(item.get("volume") or 0)
                order_count = int(item.get("order_count") or 0)
            elif hasattr(item, "price"):
                price = float(getattr(item, "price", 0) or 0)
                volume = int(getattr(item, "volume", 0) or 0)
                order_count = int(getattr(item, "order_count", 0) or 0)
            else:
                price = float(item[0])
                volume = int(item[1])
                order_count = int(item[2] or 0) if len(item) > 2 else 0
            if price > 0 and volume >= 0:
                levels.append(
                    OrderBookLevel(
                        price=price,
                        volume=volume,
                        order_count=order_count,
                    )
                )
        return tuple(levels)
