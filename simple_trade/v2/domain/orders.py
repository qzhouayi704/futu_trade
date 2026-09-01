"""订单意图、风控与执行 DTO。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping
from uuid import uuid4

from .enums import (
    ExecutionStatus,
    IntentType,
    OrderSide,
    OrderType,
    RiskResult,
    RuntimeMode,
)
from .serialization import JsonValue, freeze_json, require_aware, require_stock_code


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderLeg:
    stock_code: str
    side: OrderSide
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    reference_price: float | None = None
    lot_size: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        if self.quantity <= 0:
            raise ValueError("quantity 必须大于 0")
        if self.order_type is OrderType.LIMIT and (
            self.limit_price is None or self.limit_price <= 0
        ):
            raise ValueError("限价单必须包含有效 limit_price")
        if self.reference_price is not None and self.reference_price <= 0:
            raise ValueError("reference_price 必须大于 0")
        if self.lot_size is not None:
            if self.lot_size <= 0:
                raise ValueError("lot_size 必须大于 0")
            if self.side is OrderSide.BUY and self.quantity % self.lot_size:
                raise ValueError("买入数量必须是 lot_size 的整数倍")


@dataclass(frozen=True, slots=True, kw_only=True)
class TradeIntent:
    source_event_id: str
    intent_type: IntentType
    created_at: datetime
    mode: RuntimeMode
    sell_leg: OrderLeg | None = None
    buy_leg: OrderLeg | None = None
    intent_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        require_aware(self.created_at, "created_at")
        if not self.source_event_id.strip():
            raise ValueError("source_event_id 不能为空")
        if self.intent_type is IntentType.ROTATE:
            if self.sell_leg is None or self.buy_leg is None:
                raise ValueError("换票意图必须同时包含卖出腿和买入腿")
            if self.sell_leg.side is not OrderSide.SELL or self.buy_leg.side is not OrderSide.BUY:
                raise ValueError("换票意图的订单方向不正确")
        elif self.intent_type is IntentType.BUY:
            if self.buy_leg is None or self.sell_leg is not None:
                raise ValueError("买入意图只能包含买入腿")
        elif self.intent_type is IntentType.SELL:
            if self.sell_leg is None or self.buy_leg is not None:
                raise ValueError("卖出意图只能包含卖出腿")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskDecision:
    intent_id: str
    result: RiskResult
    checked_at: datetime
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        require_aware(self.checked_at, "checked_at")
        if not self.intent_id.strip() or not self.reason_codes:
            raise ValueError("风控结果必须包含 intent_id 和 reason_codes")


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCommand:
    intent_id: str
    leg: OrderLeg
    submitted_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        require_aware(self.submitted_at, "submitted_at")
        if not self.intent_id.strip() or not self.idempotency_key.strip():
            raise ValueError("intent_id 和 idempotency_key 不能为空")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionReport:
    intent_id: str
    stock_code: str
    status: ExecutionStatus
    reported_at: datetime
    broker_order_id: str | None = None
    filled_quantity: int = 0
    average_price: float | None = None
    details: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.reported_at, "reported_at")
        if not self.intent_id.strip():
            raise ValueError("intent_id 不能为空")
        if self.filled_quantity < 0:
            raise ValueError("filled_quantity 不能小于 0")
        if self.average_price is not None and self.average_price <= 0:
            raise ValueError("average_price 必须大于 0")
        object.__setattr__(self, "details", freeze_json(self.details))
