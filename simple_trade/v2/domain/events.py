"""V2 领域事件信封。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping
from uuid import uuid4

from .enums import DataQuality, EventType
from .market import OrderBookSnapshot, QuoteSnapshot, TickTrade
from .features import FeatureSnapshot
from .positions import PositionReconciliation
from .orders import RiskDecision, TradeIntent
from .serialization import JsonValue, freeze_json, require_aware, require_stock_code


def _new_id() -> str:
    return uuid4().hex


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    event_type: EventType
    stock_code: str
    exchange_time: datetime
    received_time: datetime
    source: str
    schema_version: int = 1
    strategy_version: str = "v2-infrastructure"
    sequence: int | None = None
    event_id: str = field(default_factory=_new_id)
    correlation_id: str = field(default_factory=_new_id)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.exchange_time, "exchange_time")
        require_aware(self.received_time, "received_time")
        if self.schema_version < 1:
            raise ValueError("schema_version 必须大于 0")
        if self.sequence is not None and self.sequence < 0:
            raise ValueError("sequence 不能小于 0")
        if not self.source.strip():
            raise ValueError("source 不能为空")
        if not self.strategy_version.strip():
            raise ValueError("strategy_version 不能为空")


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketEvent(DomainEvent):
    payload: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        object.__setattr__(self, "payload", freeze_json(self.payload))


@dataclass(frozen=True, slots=True, kw_only=True)
class QuoteEvent(DomainEvent):
    quote: QuoteSnapshot

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.event_type is not EventType.QUOTE_UPDATED:
            raise ValueError("QuoteEvent 类型必须是 QUOTE_UPDATED")
        if self.quote.stock_code != self.stock_code:
            raise ValueError("quote 与事件 stock_code 不一致")
        if self.quote.exchange_time != self.exchange_time:
            raise ValueError("quote 与事件 exchange_time 不一致")


@dataclass(frozen=True, slots=True, kw_only=True)
class TickEvent(DomainEvent):
    tick: TickTrade

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.event_type is not EventType.TICK_RECEIVED:
            raise ValueError("TickEvent 类型必须是 TICK_RECEIVED")
        if self.tick.stock_code != self.stock_code:
            raise ValueError("tick 与事件 stock_code 不一致")
        if self.tick.exchange_time != self.exchange_time:
            raise ValueError("tick 与事件 exchange_time 不一致")
        if self.tick.sequence != self.sequence:
            raise ValueError("tick 与事件 sequence 不一致")


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderBookEvent(DomainEvent):
    order_book: OrderBookSnapshot

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.event_type is not EventType.ORDER_BOOK_UPDATED:
            raise ValueError("OrderBookEvent 类型必须是 ORDER_BOOK_UPDATED")
        if self.order_book.stock_code != self.stock_code:
            raise ValueError("order_book 与事件 stock_code 不一致")
        if self.order_book.exchange_time != self.exchange_time:
            raise ValueError("order_book 与事件 exchange_time 不一致")


@dataclass(frozen=True, slots=True, kw_only=True)
class DataQualityEvent(DomainEvent):
    quality: DataQuality
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.event_type is not EventType.DATA_QUALITY_CHANGED:
            raise ValueError("DataQualityEvent 类型必须是 DATA_QUALITY_CHANGED")
        if self.quality is DataQuality.GOOD:
            raise ValueError("GOOD 质量不需要产生变化事件")
        if not self.reason_codes:
            raise ValueError("数据质量事件必须包含 reason_codes")


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureSnapshotEvent(DomainEvent):
    snapshot: FeatureSnapshot

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.event_type is not EventType.FEATURE_SNAPSHOT_READY:
            raise ValueError("FeatureSnapshotEvent 类型必须是 FEATURE_SNAPSHOT_READY")
        if self.snapshot.stock_code != self.stock_code:
            raise ValueError("snapshot 与事件 stock_code 不一致")
        if self.snapshot.computed_at != self.exchange_time:
            raise ValueError("snapshot 与事件 exchange_time 不一致")


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionReconciledEvent(DomainEvent):
    reconciliation: PositionReconciliation

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.event_type is not EventType.POSITION_RECONCILED:
            raise ValueError("PositionReconciledEvent 类型必须是 POSITION_RECONCILED")
        if self.reconciliation.as_of != self.exchange_time:
            raise ValueError("reconciliation 与事件 exchange_time 不一致")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskAssessedEvent(DomainEvent):
    source_decision_event_id: str
    intent: TradeIntent
    risk: RiskDecision

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.event_type not in {EventType.RISK_APPROVED, EventType.RISK_REJECTED}:
            raise ValueError("RiskAssessedEvent 类型必须是 RISK_APPROVED/RISK_REJECTED")
        if not self.source_decision_event_id.strip():
            raise ValueError("source_decision_event_id 不能为空")
        if self.intent.intent_id != self.risk.intent_id:
            raise ValueError("intent 与 risk 的 intent_id 不一致")
        if self.intent.source_event_id != self.source_decision_event_id:
            raise ValueError("intent 与 source decision event 不一致")
