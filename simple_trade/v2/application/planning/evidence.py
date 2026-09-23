"""Audit available execution facts; this does not authorize orders or alerts."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

from ...domain.enums import DataQuality
from ...domain.features import FeatureSnapshot
from ...domain.serialization import require_aware


@dataclass(frozen=True, slots=True)
class ExecutionEvidence:
    schema_version: int
    as_of: datetime
    market_data_ready: bool
    execution_allowed: bool
    entry_plan_status: str
    blockers: tuple[str, ...]
    max_market_age_seconds: float
    max_lot_age_seconds: float


def execution_evidence(snapshot: FeatureSnapshot, *, as_of: datetime) -> ExecutionEvidence:
    require_aware(as_of, "as_of")
    market_age = 3.0
    lot_age = 21600.0
    blockers: list[str] = []
    quote = snapshot.quote
    if snapshot.computed_at > as_of:
        blockers.append("FEATURE_NOT_YET_KNOWN")
    if snapshot.quality is not DataQuality.GOOD or quote.quality is not DataQuality.GOOD:
        blockers.append("MARKET_DATA_QUALITY_INCOMPLETE")
    if not math.isfinite(quote.last_price) or quote.last_price <= 0:
        blockers.append("QUOTE_PRICE_INVALID")
    if not 0 <= (as_of - quote.exchange_time).total_seconds() <= market_age:
        blockers.append("QUOTE_TIME_INVALID_OR_STALE")

    fact = quote.lot_size_observation
    if fact is None:
        blockers.append("LOT_SIZE_PROVENANCE_MISSING")
    else:
        zone = timezone(timedelta(hours=8)) if quote.stock_code.startswith("HK.") else as_of.tzinfo
        if (not 0 <= (as_of - fact.observed_at).total_seconds() <= lot_age
                or fact.quote_exchange_time > quote.exchange_time
                or fact.quote_exchange_time.astimezone(zone).date() != as_of.astimezone(zone).date()):
            blockers.append("LOT_SIZE_TIME_INVALID_OR_STALE")

    book, received = snapshot.order_book, snapshot.order_book_received_at
    if book is None:
        blockers.append("ORDER_BOOK_MISSING")
    else:
        if received is None:
            blockers.append("ORDER_BOOK_RECEIPT_MISSING")
        elif (not 0 <= (as_of - received).total_seconds() <= market_age
              or book.exchange_time > received):
            blockers.append("ORDER_BOOK_RECEIPT_INVALID_OR_STALE")
        if book.timestamp_basis != "EXCHANGE":
            blockers.append("ORDER_BOOK_EXCHANGE_TIME_UNVERIFIED")
        if not 0 <= (as_of - book.exchange_time).total_seconds() <= market_age:
            blockers.append("ORDER_BOOK_TIME_INVALID_OR_STALE")
        if book.quality is not DataQuality.GOOD:
            blockers.append("ORDER_BOOK_QUALITY_INCOMPLETE")
        if (not book.bid_levels or not book.ask_levels
                or any(not math.isfinite(level.price) or level.price <= 0 or level.volume <= 0
                       for level in (*book.bid_levels, *book.ask_levels))
                or (book.best_bid is not None and book.best_ask is not None
                    and book.best_bid >= book.best_ask)):
            blockers.append("ORDER_BOOK_NOT_EXECUTABLE")

    market_ready = not blockers
    # Current live strategies produce signals, not executable EntryPlans.
    blockers.append("ENTRY_PLAN_NOT_GENERATED")
    return ExecutionEvidence(1, as_of, market_ready, False, "NOT_GENERATED",
                             tuple(blockers), market_age, lot_age)
