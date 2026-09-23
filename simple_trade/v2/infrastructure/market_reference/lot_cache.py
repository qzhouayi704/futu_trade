"""Reuse observed board lots without guessing values or rewriting their known time."""

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import threading

from ....utils.converters import parse_positive_int
from ...domain.market import LotSizeObservation


class LotObservationCache:
    def __init__(self, *, capacity: int = 10000, max_age_seconds: int = 21600) -> None:
        if capacity <= 0 or max_age_seconds <= 0:
            raise ValueError("lot cache capacity and age must be positive")
        self._capacity = capacity
        self._max_age = max_age_seconds
        self._facts: OrderedDict[str, LotSizeObservation] = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def _parse(value: object) -> int | None:
        size = parse_positive_int(value)
        return size if size is not None and size <= 100000000 else None

    def resolve(self, code: str, value: object, *, exchange_time: datetime,
                received_time: datetime, source: str, realtime: bool) -> LotSizeObservation | None:
        if not realtime or exchange_time > received_time:
            return None
        size = self._parse(value)
        with self._lock:
            current = self._facts.get(code)
            if size is not None and (current is None or (
                    exchange_time >= current.quote_exchange_time and received_time >= current.observed_at)):
                current = LotSizeObservation(stock_code=code, lot_size=size, observed_at=received_time,
                                             quote_exchange_time=exchange_time, source=source)
                self._facts[code] = current
                self._facts.move_to_end(code)
                while len(self._facts) > self._capacity:
                    self._facts.popitem(last=False)
            if current is None:
                return None
            market_zone = timezone(timedelta(hours=8)) if code.startswith("HK.") else exchange_time.tzinfo
            if (not 0 <= (received_time - current.observed_at).total_seconds() <= self._max_age
                    or current.quote_exchange_time > exchange_time
                    or current.quote_exchange_time.astimezone(market_zone).date() != exchange_time.astimezone(market_zone).date()):
                return None
            return current
