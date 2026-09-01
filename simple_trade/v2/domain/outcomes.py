"""V2 signal outcome models used only for post-trade evaluation."""

from dataclasses import dataclass, replace
from datetime import datetime

from .serialization import require_aware, require_stock_code


@dataclass(frozen=True, slots=True, kw_only=True)
class OutcomeRecord:
    decision_event_id: str
    stock_code: str
    strategy_version: str
    signal_time: datetime
    signal_price: float
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    close_return_pct: float | None = None
    next_day_return_pct: float | None = None
    time_to_1_5_seconds: int | None = None
    time_to_3_seconds: int | None = None
    time_to_5_seconds: int | None = None
    time_to_peak_seconds: int | None = None
    hold_control_return_pct: float | None = None
    rotation_return_pct: float | None = None
    evaluated_at: datetime | None = None
    control_stock_code: str | None = None
    control_signal_price: float | None = None
    last_price: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.signal_time, "signal_time")
        if self.evaluated_at is not None:
            require_aware(self.evaluated_at, "evaluated_at")
        if not self.decision_event_id.strip() or not self.strategy_version.strip():
            raise ValueError("outcome identifiers cannot be empty")
        if self.signal_price <= 0:
            raise ValueError("signal_price must be positive")
        if self.control_stock_code is not None:
            object.__setattr__(
                self, "control_stock_code", require_stock_code(self.control_stock_code)
            )
            if self.control_signal_price is None or self.control_signal_price <= 0:
                raise ValueError("rotation control requires a positive control price")

    @property
    def reached_1_5(self) -> bool:
        return self.time_to_1_5_seconds is not None

    @property
    def reached_3(self) -> bool:
        return self.time_to_3_seconds is not None

    @property
    def reached_5(self) -> bool:
        return self.time_to_5_seconds is not None

    def evolve(self, **changes) -> "OutcomeRecord":
        return replace(self, **changes)
