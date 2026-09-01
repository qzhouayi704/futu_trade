"""Typed account and risk context snapshots."""

from dataclasses import dataclass
from datetime import datetime

from .enums import DataQuality
from .positions import ActiveOrderSnapshot, PositionSnapshot
from .serialization import require_aware


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountSnapshot:
    as_of: datetime
    available_funds: float
    total_assets: float
    currency: str = "HKD"
    quality: DataQuality = DataQuality.GOOD
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_aware(self.as_of, "as_of")
        if self.available_funds < 0 or self.total_assets < 0:
            raise ValueError("account amounts cannot be negative")
        if not self.currency.strip():
            raise ValueError("currency cannot be empty")
        if self.quality is DataQuality.INVALID and not self.reason_codes:
            raise ValueError("invalid account snapshot requires reason_codes")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskContext:
    checked_at: datetime
    market_trading: bool
    positions: tuple[PositionSnapshot, ...]
    active_orders: tuple[ActiveOrderSnapshot, ...]
    account: AccountSnapshot

    def __post_init__(self) -> None:
        require_aware(self.checked_at, "checked_at")


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_positions: int = 5
    max_single_position_ratio: float = 0.30
    min_cash_reserve_ratio: float = 0.30

    def __post_init__(self) -> None:
        if self.max_positions <= 0:
            raise ValueError("max_positions must be positive")
        if not 0 < self.max_single_position_ratio <= 1:
            raise ValueError("max_single_position_ratio must be in (0, 1]")
        if not 0 <= self.min_cash_reserve_ratio < 1:
            raise ValueError("min_cash_reserve_ratio must be in [0, 1)")
