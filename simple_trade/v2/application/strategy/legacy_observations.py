"""Bounded legacy-signal observations used only to open V2 watch states."""

from collections import defaultdict, deque
from datetime import datetime
import threading

from ...domain.enums import EventType
from ...domain.events import MarketEvent
from .models import LegacySignalContext


class LegacyObservationBook:
    def __init__(self, window_seconds: int = 900, max_per_stock: int = 32) -> None:
        if window_seconds <= 0 or max_per_stock <= 0:
            raise ValueError("legacy observation limits must be positive")
        self._window_seconds = window_seconds
        self._max_per_stock = max_per_stock
        self._items: dict[str, deque[LegacySignalContext]] = defaultdict(deque)
        self._lock = threading.RLock()

    def on_event(self, event) -> None:
        if not isinstance(event, MarketEvent):
            return
        if event.event_type is not EventType.LEGACY_SIGNAL_RECEIVED:
            return
        payload = event.payload
        observation = LegacySignalContext(
            observed_at=event.exchange_time,
            source=str(payload.get("signal_source") or "unknown"),
            direction=str(payload.get("direction") or "UNKNOWN").upper(),
            severity=str(payload.get("severity") or "").lower(),
            duration_minutes=self._integer(payload.get("duration_minutes")),
            price_change_pct=self._number(payload.get("price_change_pct")),
            net_buy_amount=self._number(payload.get("net_buy_amount")),
            position=str(payload.get("position") or "unknown").lower(),
            signal_price=self._number(payload.get("signal_price")),
        )
        with self._lock:
            items = self._items[event.stock_code]
            items.append(observation)
            while len(items) > self._max_per_stock:
                items.popleft()
            self._prune(items, event.exchange_time)

    def latest(self, stock_code: str, as_of: datetime) -> LegacySignalContext | None:
        with self._lock:
            items = self._items.get(stock_code)
            if not items:
                return None
            self._prune(items, as_of)
            return items[-1] if items else None

    def _prune(self, items: deque[LegacySignalContext], as_of: datetime) -> None:
        while items and (as_of - items[0].observed_at).total_seconds() > self._window_seconds:
            items.popleft()

    @staticmethod
    def _number(value: object) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError, OverflowError):
            return 0.0

    @staticmethod
    def _integer(value: object) -> int:
        try:
            return int(float(value or 0))
        except (TypeError, ValueError, OverflowError):
            return 0
