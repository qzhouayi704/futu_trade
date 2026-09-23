"""Explicit conversion of sampled server-time books into approximate paper inputs."""

from ...domain.capture import CapturedBook
from ...domain.planning.models import PaperBook


def to_paper_book(book: CapturedBook, *, allow_sampled_server_time: bool = False,
                  market_open: bool) -> PaperBook:
    if not allow_sampled_server_time:
        raise ValueError("sampled server-time approximation requires explicit opt-in")
    if (book.reasons or book.loss_count or book.bid_time is None or book.ask_time is None
            or book.bid is None or book.ask is None or book.bid >= book.ask
            or book.bid_size <= 0 or book.ask_size <= 0):
        raise ValueError("incomplete or gapped capture cannot supply a paper fill")
    for value in (book.bid_time, book.ask_time):
        if not 0 <= (book.received_at - value).total_seconds() <= 3:
            raise ValueError("book is stale or not yet known")
    # Requiring both sides to advance is conservative: repeated snapshots cannot
    # reuse the same displayed liquidity merely because local receipt is newer.
    return PaperBook(event_id=book.event_id, stock_code=book.stock_code,
                     exchange_time=min(book.bid_time, book.ask_time), received_at=book.received_at,
                     bid=book.bid, ask=book.ask, bid_size=book.bid_size, ask_size=book.ask_size,
                     market_open=market_open)
