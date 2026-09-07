"""候选标的 DTO。"""

from dataclasses import dataclass
from datetime import date, datetime

from .enums import CandidateStatus, DataQuality, StringEnum
from .serialization import require_aware, require_stock_code


OVERNIGHT_HARD_INVALIDATIONS = frozenset({
    "PRICE_ACCEPTANCE_BROKEN", "LARGE_OUTFLOW_OFFSETS_INFLOW", "CAPITAL_MEMORY_TURNED_DISTRIBUTING",
})


@dataclass(frozen=True, slots=True, kw_only=True)
class TradeCandidate:
    stock_code: str
    as_of: datetime
    status: CandidateStatus
    score: float
    quality: DataQuality
    reason_codes: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    confirmation_price: float | None = None
    strategy_sources: tuple[str, ...] = ()
    consensus_count: int = 0
    alert_eligible: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.as_of, "as_of")
        if not 0 <= self.score <= 100:
            raise ValueError("score 必须在 0 到 100 之间")
        if self.confirmation_price is not None and self.confirmation_price <= 0:
            raise ValueError("confirmation_price 必须大于 0")
        if self.consensus_count != len(self.strategy_sources):
            raise ValueError("consensus_count 必须与 strategy_sources 数量一致")
        if not isinstance(self.alert_eligible, bool):
            raise ValueError("alert_eligible 必须是布尔值")
        if not self.reason_codes:
            raise ValueError("候选必须包含 reason_codes")


@dataclass(frozen=True, slots=True, kw_only=True)
class OvernightPriority:
    """历史独立合格条件形成、需在有效交易日重新确认的观察线索。"""

    stock_code: str
    source_date: str
    source_time: datetime
    score: float
    reference_price: float
    daily_percentile: float
    atr_percent: float
    capital_memory_score: float
    day_main_net: float
    independent_buy_events: int
    source_reason: str
    setup_id: str = ""
    eligible_date: str | None = None
    expires_date: str | None = None
    age_sessions: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.source_time, "source_time")
        date.fromisoformat(self.source_date)
        if not 0 <= self.score <= 100:
            raise ValueError("score 必须在 0 到 100 之间")
        if self.reference_price <= 0:
            raise ValueError("reference_price 必须大于 0")
        if not 0 <= self.daily_percentile <= 1:
            raise ValueError("daily_percentile 必须在 0 到 1 之间")
        if self.atr_percent < 0:
            raise ValueError("atr_percent 不能小于 0")
        if not 0 <= self.capital_memory_score <= 100:
            raise ValueError("capital_memory_score 必须在 0 到 100 之间")
        if self.day_main_net <= 0:
            raise ValueError("day_main_net 必须大于 0")
        if self.independent_buy_events < 1:
            raise ValueError("independent_buy_events 必须大于 0")
        if not self.source_reason.strip():
            raise ValueError("source_reason 不能为空")
        if self.age_sessions < 1:
            raise ValueError("age_sessions 必须大于 0")
        if self.eligible_date is not None:
            date.fromisoformat(self.eligible_date)
        if self.expires_date is not None:
            date.fromisoformat(self.expires_date)
            if self.expires_date <= self.source_date:
                raise ValueError("到期日必须晚于来源日")

    def is_valid_on(self, session_date: str) -> bool:
        return bool(
            self.eligible_date == session_date
            and self.expires_date is not None
            and self.source_date < session_date <= self.expires_date
            and self.age_sessions <= 3
        )


class OvernightStatus(StringEnum):
    WATCHING = "WATCHING"
    SUSPENDED = "SUSPENDED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True, kw_only=True)
class OvernightObservation:
    priority: OvernightPriority
    status: OvernightStatus
    reason_code: str
    last_event_time: datetime

    @property
    def retained(self) -> bool:
        return self.status in {OvernightStatus.WATCHING, OvernightStatus.SUSPENDED}
