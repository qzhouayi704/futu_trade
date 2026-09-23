"""Futu push normalization without inventing timestamps or executable quotes."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from ....utils.converters import parse_positive_int
from ...domain.capture import CapturedBook


HK = timezone(timedelta(hours=8))


def _server_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip() or value.strip() == "0":
        return None
    try:
        result = datetime.fromisoformat(value.strip())
        return result.replace(tzinfo=HK) if result.tzinfo is None else result
    except ValueError:
        return None


def _best(raw: object) -> tuple[Decimal | None, int]:
    if not isinstance(raw, (tuple, list)) or not raw:
        return None, 0
    level = raw[0]
    if not isinstance(level, (tuple, list)) or len(level) < 2:
        return None, 0
    try:
        price = Decimal(str(level[0]))
        size = parse_positive_int(level[1])
        if not price.is_finite() or price <= 0 or size is None:
            return None, 0
        return price, size
    except (InvalidOperation, ValueError):
        return None, 0


def normalize_book(raw: Mapping[str, object], *, session_id: str, sequence: int,
                   connection_id: str, received_at: datetime, loss_count: int) -> CapturedBook:
    bid_time = _server_time(raw.get("svr_recv_time_bid"))
    ask_time = _server_time(raw.get("svr_recv_time_ask"))
    bid, bid_size = _best(raw.get("Bid"))
    ask, ask_size = _best(raw.get("Ask"))
    reasons: list[str] = []
    if bid_time is None or ask_time is None:
        reasons.append("SERVER_TIME_MISSING")
    elif any(not 0 <= (received_at - value).total_seconds() <= 3 for value in (bid_time, ask_time)):
        reasons.append("SERVER_TIME_FUTURE_OR_STALE")
    if bid is None or ask is None:
        reasons.append("BOOK_EMPTY_OR_INVALID")
    elif bid >= ask:
        reasons.append("BOOK_LOCKED_OR_CROSSED")
    if str(raw.get("order_book_type", "NORMAL")) != "NORMAL":
        reasons.append("BOOK_TYPE_NOT_NORMAL")
    if loss_count:
        reasons.append("CAPTURE_HAS_GAPS")
    return CapturedBook(session_id=session_id, sequence=sequence, connection_id=connection_id,
                        stock_code=str(raw.get("code", "")), received_at=received_at,
                        bid_time=bid_time, ask_time=ask_time, bid=bid, ask=ask,
                        bid_size=bid_size, ask_size=ask_size, reasons=tuple(reasons), loss_count=loss_count)
