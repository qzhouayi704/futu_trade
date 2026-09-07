"""Typed contracts shared by strategy evaluation and lifecycle projections."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from ...domain.enums import StrategyStatus, StringEnum
from ...domain.serialization import (
    JsonValue,
    freeze_json,
    require_aware,
    require_stock_code,
)


class SignalPermission(StringEnum):
    NONE = "NONE"
    TRACKING = "TRACKING"
    RESEARCH = "RESEARCH"
    FORMAL_ELIGIBLE = "FORMAL_ELIGIBLE"
    DELIVERED = "DELIVERED"


def signal_permission(
    status: str | StrategyStatus,
    *,
    alert_eligible: bool,
    delivered: bool = False,
) -> SignalPermission:
    if delivered:
        return SignalPermission.DELIVERED
    value = status.value if isinstance(status, StrategyStatus) else str(status).upper()
    if value in {StrategyStatus.IDLE.value, StrategyStatus.INVALIDATED.value}:
        return SignalPermission.NONE
    if value == StrategyStatus.CONFIRMED.value:
        return (
            SignalPermission.FORMAL_ELIGIBLE
            if alert_eligible
            else SignalPermission.RESEARCH
        )
    if value in {StrategyStatus.SETUP.value, StrategyStatus.WATCHING.value}:
        return SignalPermission.TRACKING
    return SignalPermission.NONE


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyAssessment:
    stock_code: str
    strategy_id: str
    as_of: datetime
    stage: StrategyStatus
    score: float
    reference_price: float
    permission: SignalPermission
    reason_codes: tuple[str, ...]
    evidence: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.as_of, "as_of")
        if not self.strategy_id.strip():
            raise ValueError("strategy_id 不能为空")
        if not 0 <= self.score <= 100:
            raise ValueError("策略评分必须在 0 到 100 之间")
        if self.reference_price <= 0:
            raise ValueError("策略参考价必须大于 0")
        if not self.reason_codes:
            raise ValueError("策略评估必须包含原因")
        object.__setattr__(self, "evidence", freeze_json(self.evidence))


@dataclass(frozen=True, slots=True, kw_only=True)
class SetupLifecycle:
    setup_id: str
    stock_code: str
    strategy_version: str
    opened_at: datetime
    updated_at: datetime
    first_stage: StrategyStatus
    max_stage: StrategyStatus
    current_status: StrategyStatus
    current_reason_code: str
    permission: SignalPermission

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.opened_at, "opened_at")
        require_aware(self.updated_at, "updated_at")
        if not self.setup_id.strip() or not self.strategy_version.strip():
            raise ValueError("机会标识和策略版本不能为空")
        if self.updated_at < self.opened_at:
            raise ValueError("机会更新时间不能早于首次发现时间")
        if not self.current_reason_code.strip():
            raise ValueError("当前状态必须包含原因")


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPlan:
    setup_id: str
    stock_code: str
    strategy_id: str
    as_of: datetime
    reference_price: float
    entry_price_min: float
    entry_price_max: float
    max_chase_price: float
    invalidation_price: float
    initial_position_ratio: float
    holding_minutes: int | None = None
    holding_sessions: int | None = None
    add_conditions: tuple[str, ...] = ()
    exit_conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.as_of, "as_of")
        if not self.setup_id.strip() or not self.strategy_id.strip():
            raise ValueError("入场计划必须包含机会和策略标识")
        if min(
            self.reference_price,
            self.entry_price_min,
            self.entry_price_max,
            self.max_chase_price,
            self.invalidation_price,
        ) <= 0:
            raise ValueError("入场计划价格必须大于 0")
        if not (
            self.invalidation_price < self.entry_price_min
            <= self.entry_price_max <= self.max_chase_price
        ):
            raise ValueError("入场、追价和失效价格顺序无效")
        if not 0 < self.initial_position_ratio <= 1:
            raise ValueError("初始仓位比例必须在 0 到 1 之间")
        if self.holding_minutes is None and self.holding_sessions is None:
            raise ValueError("入场计划必须包含持有期限")
        if self.holding_minutes is not None and self.holding_minutes <= 0:
            raise ValueError("持有分钟数必须大于 0")
        if self.holding_sessions is not None and self.holding_sessions <= 0:
            raise ValueError("持有交易日数必须大于 0")
