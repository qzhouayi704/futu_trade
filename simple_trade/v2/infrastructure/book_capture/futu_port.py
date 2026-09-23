"""Borrow existing books or allocate spare quota, never displace trading feeds."""

import threading
import time

from ...ports.book_capture import BookSink


class FutuBookCapturePort:
    def __init__(self, client, manager, *, max_stocks: int, monotonic=time.monotonic) -> None:
        self.client = client
        self.manager = manager
        self._max = max_stocks
        self._clock = monotonic
        self._owned: dict[str, float] = {}
        self._borrowed: set[str] = set()
        self._generation: str | None = None
        self._verified: set[str] = set()
        self._sink: BookSink | None = None
        self._closed = threading.Event()

    def set_sink(self, sink: BookSink | None) -> None:
        self._closed.clear()
        self._sink = sink
        self.client.set_order_book_sink(sink)

    def sync(self, stock_codes: tuple[str, ...]) -> tuple[str, ...]:
        from futu import SubType

        if self._closed.is_set() or not self.client.is_available():
            return ()
        generation = self.client.book_connection_id
        if not generation:
            self.client.set_order_book_sink(self._sink)
            generation = self.client.book_connection_id
            if not generation:
                return ()
        desired = set(stock_codes[:self._max])
        if self._generation is not None and generation != self._generation:
            self.manager.invalidate_orderbook_cache(list(self._verified | set(self._owned) | desired))
            self._owned.clear()
            self._verified.clear()
        self._generation = generation
        current = self.manager.orderbook_subscribed_stocks
        self._borrowed.update(desired & current - set(self._owned))
        now = self._clock()
        for code, since in tuple(self._owned.items()):
            if self._closed.is_set():
                return ()
            if code in desired or now - since < 65:
                continue
            if code in current:
                self.manager.unsubscribe_multi_types([code], [SubType.ORDER_BOOK])
            if code not in self.manager.orderbook_subscribed_stocks:
                self._owned.pop(code, None)
        for code in stock_codes[:self._max]:
            if self._closed.is_set():
                return ()
            if code in self.manager.orderbook_subscribed_stocks:
                continue
            if code not in self._borrowed and len(self._owned) >= self._max:
                continue
            self.manager.subscribe_multi_types([code], [SubType.ORDER_BOOK])
            if code in self.manager.orderbook_subscribed_stocks and code not in self._borrowed:
                self._owned[code] = self._clock()
        if self.client.book_connection_id != generation or not self.client.is_available():
            return ()
        self._verified = desired & self.manager.orderbook_subscribed_stocks
        return tuple(code for code in stock_codes if code in self._verified)

    def close(self) -> None:
        self._closed.set()
        self._sink = None
        self.client.set_order_book_sink(None)
