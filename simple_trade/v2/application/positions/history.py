"""Bounded in-memory feature and price history for held stocks."""

from collections import deque
from datetime import timedelta
import threading

from ...domain.events import FeatureSnapshotEvent
from ...domain.features import FeatureSnapshot
from .efficiency import PricePoint


class PositionFeatureHistory:
    def __init__(self) -> None:
        self._features: dict[str, FeatureSnapshot] = {}
        self._prices: dict[str, deque[PricePoint]] = {}
        self._lock = threading.RLock()

    def on_feature(self, event: FeatureSnapshotEvent) -> None:
        point = (event.exchange_time, event.snapshot.quote.last_price)
        with self._lock:
            self._features[event.stock_code] = event.snapshot
            history = self._prices.setdefault(event.stock_code, deque())
            if not history or point[0] >= history[-1][0]:
                history.append(point)
            cutoff = event.exchange_time - timedelta(hours=2)
            while history and history[0][0] < cutoff:
                history.popleft()

    def context(
        self,
        stock_code: str,
    ) -> tuple[FeatureSnapshot | None, tuple[PricePoint, ...], dict[str, FeatureSnapshot]]:
        with self._lock:
            return (
                self._features.get(stock_code),
                tuple(self._prices.get(stock_code, ())),
                dict(self._features),
            )
