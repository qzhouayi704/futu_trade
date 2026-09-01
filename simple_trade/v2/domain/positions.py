"""持仓事实、效率、状态与换票建议 DTO。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from .enums import DataQuality, DecisionAction, PositionStatus
from .serialization import JsonValue, freeze_json, require_aware, require_stock_code


@dataclass(frozen=True, slots=True, kw_only=True)
class ActiveOrderSnapshot:
    order_id: str
    stock_code: str
    side: str
    status: str
    quantity: int
    dealt_quantity: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        if not self.order_id.strip() or not self.side.strip() or not self.status.strip():
            raise ValueError("活动订单关键字段不能为空")
        if self.quantity < 0 or self.dealt_quantity < 0:
            raise ValueError("订单数量不能小于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionSnapshot:
    stock_code: str
    as_of: datetime
    quantity: int
    sellable_quantity: int
    cost_price: float
    current_price: float
    peak_price: float
    lot_size: int | None
    active_order_ids: tuple[str, ...] = ()
    stock_name: str = ""
    quality: DataQuality = DataQuality.GOOD

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.as_of, "as_of")
        if self.quantity < 0 or self.sellable_quantity < 0:
            raise ValueError("持仓数量不能小于 0")
        if self.sellable_quantity > self.quantity:
            raise ValueError("可卖数量不能大于持仓数量")
        if any(value < 0 for value in (self.cost_price, self.current_price, self.peak_price)):
            raise ValueError("持仓价格不能小于 0")
        if self.lot_size is not None and self.lot_size <= 0:
            raise ValueError("lot_size 必须大于 0")

    @property
    def current_return_pct(self) -> float:
        if self.cost_price <= 0:
            return 0.0
        return (self.current_price / self.cost_price - 1.0) * 100.0


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionReconciliation:
    as_of: datetime
    positions: tuple[PositionSnapshot, ...]
    active_orders: tuple[ActiveOrderSnapshot, ...]
    authoritative: bool
    quality: DataQuality
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_aware(self.as_of, "as_of")
        codes = [position.stock_code for position in self.positions]
        if len(codes) != len(set(codes)):
            raise ValueError("持仓对账不能包含重复股票")
        if self.authoritative and self.quality is DataQuality.INVALID:
            raise ValueError("权威持仓对账不能是 INVALID")


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionEfficiency:
    stock_code: str
    as_of: datetime
    current_return_pct: float
    mfe_pct: float
    mae_pct: float
    drawdown_from_peak_pct: float
    flow_peak: float
    flow_current: float
    flow_drawdown_ratio: float
    slope_15m_pct: float | None
    slope_30m_pct: float | None
    slope_60m_pct: float | None
    range_15m_pct: float | None
    minutes_since_high: float
    score: float
    stalled: bool
    quality: DataQuality
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.as_of, "as_of")
        if not 0 <= self.score <= 100:
            raise ValueError("持仓效率分必须在 0 到 100 之间")
        if not 0 <= self.flow_drawdown_ratio <= 1:
            raise ValueError("flow_drawdown_ratio 必须在 0 到 1 之间")
        if self.minutes_since_high < 0:
            raise ValueError("minutes_since_high 不能小于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionState:
    stock_code: str
    strategy_version: str
    status: PositionStatus
    version: int
    last_event_id: str
    updated_at: datetime
    opened_at: datetime
    cost_price: float
    peak_price: float
    trough_price: float
    mfe_pct: float
    mae_pct: float
    last_high_at: datetime
    stalled_since: datetime | None = None
    profit_ready_since: datetime | None = None
    flow_peak: float = 0.0
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        for name in ("updated_at", "opened_at", "last_high_at"):
            require_aware(getattr(self, name), name)
        if self.stalled_since is not None:
            require_aware(self.stalled_since, "stalled_since")
        if self.profit_ready_since is not None:
            require_aware(self.profit_ready_since, "profit_ready_since")
        if self.version < 1 or not self.last_event_id.strip() or not self.strategy_version.strip():
            raise ValueError("持仓状态版本和标识无效")
        if min(self.cost_price, self.peak_price, self.trough_price) < 0:
            raise ValueError("持仓状态价格不能小于 0")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class RotationProposal:
    as_of: datetime
    sell_stock_code: str
    sellable_quantity: int
    buy_stock_code: str
    estimated_buy_quantity: int
    estimated_buy_price: float
    buy_lot_size: int
    held_efficiency_score: float
    candidate_score: float
    estimated_cost_pct: float
    safety_margin_score: float
    net_advantage_score: float
    evidence: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_aware(self.as_of, "as_of")
        object.__setattr__(self, "sell_stock_code", require_stock_code(self.sell_stock_code))
        object.__setattr__(self, "buy_stock_code", require_stock_code(self.buy_stock_code))
        if self.sellable_quantity <= 0 or self.estimated_buy_quantity <= 0:
            raise ValueError("换票建议数量必须大于 0")
        if self.estimated_buy_price <= 0 or self.buy_lot_size <= 0:
            raise ValueError("换票建议必须包含候选价格和每手股数")
        if self.estimated_buy_quantity % self.buy_lot_size:
            raise ValueError("换票买入数量必须是每手股数的整数倍")
        for score in (
            self.held_efficiency_score,
            self.candidate_score,
            self.safety_margin_score,
        ):
            if not 0 <= score <= 100:
                raise ValueError("换票分数必须在 0 到 100 之间")
        if self.estimated_cost_pct < 0:
            raise ValueError("换票成本不能小于 0")
        object.__setattr__(self, "evidence", freeze_json(self.evidence))


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionDecision:
    stock_code: str
    as_of: datetime
    status: PositionStatus
    action: DecisionAction
    reason_codes: tuple[str, ...]
    replacement_stock_code: str | None = None
    confidence: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.as_of, "as_of")
        if self.replacement_stock_code is not None:
            object.__setattr__(
                self,
                "replacement_stock_code",
                require_stock_code(self.replacement_stock_code),
            )
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence 必须在 0 到 1 之间")
        if not self.reason_codes:
            raise ValueError("持仓决策必须包含 reason_codes")
        if self.action is DecisionAction.ROTATE and self.replacement_stock_code is None:
            raise ValueError("换票决策必须包含 replacement_stock_code")
