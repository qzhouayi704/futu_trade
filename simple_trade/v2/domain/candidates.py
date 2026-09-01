"""候选标的 DTO。"""

from dataclasses import dataclass
from datetime import datetime

from .enums import CandidateStatus, DataQuality
from .serialization import require_aware, require_stock_code


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.as_of, "as_of")
        if not 0 <= self.score <= 100:
            raise ValueError("score 必须在 0 到 100 之间")
        if self.confirmation_price is not None and self.confirmation_price <= 0:
            raise ValueError("confirmation_price 必须大于 0")
        if not self.reason_codes:
            raise ValueError("候选必须包含 reason_codes")
