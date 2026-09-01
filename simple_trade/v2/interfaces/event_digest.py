"""Stable semantic hashes shared by live ingestion and replay."""

import hashlib

from ..domain.events import (
    DataQualityEvent,
    DomainEvent,
    FeatureSnapshotEvent,
    OrderBookEvent,
    QuoteEvent,
    TickEvent,
)
from ..domain.serialization import canonical_json, to_primitive


def event_semantic_record(event: DomainEvent) -> dict[str, object]:
    record: dict[str, object] = {
        "event_type": event.event_type.value,
        "stock_code": event.stock_code,
        "exchange_time": event.exchange_time.isoformat(),
        "sequence": event.sequence,
        "schema_version": event.schema_version,
    }
    if isinstance(event, QuoteEvent):
        record["data"] = to_primitive(event.quote)
    elif isinstance(event, FeatureSnapshotEvent):
        record["data"] = to_primitive(event.snapshot)
    elif isinstance(event, TickEvent):
        record["data"] = to_primitive(event.tick)
    elif isinstance(event, OrderBookEvent):
        record["data"] = to_primitive(event.order_book)
    elif isinstance(event, DataQualityEvent):
        record["data"] = {
            "quality": event.quality.value,
            "reason_codes": list(event.reason_codes),
        }
    else:
        record["data"] = None
    return record


def event_stream_digest(events: tuple[DomainEvent, ...]) -> str:
    payload = [event_semantic_record(event) for event in events]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
