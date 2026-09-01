"""策略状态、决策事件与通知 DTO。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from .enums import EventType, NotificationChannel, StrategyStatus
from .events import DomainEvent
from .serialization import JsonValue, freeze_json, require_aware, require_stock_code


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyTransition:
    stock_code: str
    strategy_version: str
    old_state: StrategyStatus
    new_state: StrategyStatus
    occurred_at: datetime
    reason_code: str
    evidence_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.occurred_at, "occurred_at")
        if self.old_state is self.new_state:
            raise ValueError("状态转换的新旧状态不能相同")
        if not self.strategy_version.strip() or not self.reason_code.strip():
            raise ValueError("strategy_version 和 reason_code 不能为空")


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyState:
    stock_code: str
    strategy_version: str
    status: StrategyStatus
    version: int
    last_event_id: str
    updated_at: datetime
    confirmed_price: float | None = None
    peak_price: float | None = None
    last_sequence: int | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.updated_at, "updated_at")
        if not self.strategy_version.strip() or not self.last_event_id.strip():
            raise ValueError("strategy_version 和 last_event_id 不能为空")
        if self.version < 1:
            raise ValueError("状态 version 必须从 1 开始")
        if self.confirmed_price is not None and self.confirmed_price <= 0:
            raise ValueError("confirmed_price 必须大于 0")
        if self.peak_price is not None and self.peak_price <= 0:
            raise ValueError("peak_price 必须大于 0")
        if self.last_sequence is not None and self.last_sequence < 0:
            raise ValueError("last_sequence 不能小于 0")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionEvent(DomainEvent):
    reason_code: str
    old_state: str | None = None
    new_state: str | None = None
    payload: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if not self.reason_code.strip():
            raise ValueError("reason_code 不能为空")
        object.__setattr__(self, "payload", freeze_json(self.payload))


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationEvent(DomainEvent):
    decision_event_id: str
    channel: NotificationChannel
    idempotency_key: str
    title: str
    message: str
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.event_type is not EventType.NOTIFICATION_REQUESTED:
            raise ValueError("NotificationEvent 的 event_type 必须是 NOTIFICATION_REQUESTED")
        if not self.decision_event_id.strip() or not self.idempotency_key.strip():
            raise ValueError("decision_event_id 和 idempotency_key 不能为空")
        if not self.title.strip() or not self.message.strip():
            raise ValueError("通知标题和内容不能为空")
        if self.expires_at is not None:
            require_aware(self.expires_at, "expires_at")
