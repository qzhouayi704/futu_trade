"""Market-data-only operations. No trading/account execution dependency."""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol
from ..domain.capture import CapturedBook, CaptureStats


BookSink = Callable[[Mapping[str, object], datetime, str], None]


class BookNormalizer(Protocol):
    def __call__(self, raw: Mapping[str, object], *, session_id: str, sequence: int,
                 connection_id: str, received_at: datetime, loss_count: int) -> CapturedBook: ...


class BookArchivePort(Protocol):
    def start(self, session_id: str, when: datetime) -> None: ...

    def write(self, books: tuple[CapturedBook, ...], stats: CaptureStats,
              *, ended_at: datetime | None = None) -> None: ...


class BookCapturePort(Protocol):
    def set_sink(self, sink: BookSink | None) -> None: ...

    def sync(self, stock_codes: tuple[str, ...]) -> tuple[str, ...]:
        """Return verified ORDER_BOOK subscriptions, respecting shared quotas."""
        ...

    def close(self) -> None:
        """Detach the sink. Do not revoke subscriptions belonging to others."""
        ...
