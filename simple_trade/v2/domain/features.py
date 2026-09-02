"""统一特征快照及其可解释的组成部分。"""

from dataclasses import dataclass
from datetime import datetime

from .enums import DataQuality, MarketRegime
from .market import CapitalMemory, QuoteSnapshot, TickAggregate
from .serialization import require_aware, require_stock_code


def _validate_score(value: float, field_name: str = "score") -> None:
    if not 0 <= value <= 100:
        raise ValueError(f"{field_name} 必须在 0 到 100 之间")


@dataclass(frozen=True, slots=True, kw_only=True)
class DailyBar:
    stock_code: str
    as_of: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int = 0
    turnover: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.as_of, "as_of")
        prices = (self.open_price, self.high_price, self.low_price, self.close_price)
        if any(value <= 0 for value in prices):
            raise ValueError("日线价格必须大于 0")
        if self.high_price < self.low_price:
            raise ValueError("日线最高价不能低于最低价")
        if self.volume < 0 or self.turnover < 0:
            raise ValueError("日线成交量和成交额不能小于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class BreadthMember:
    stock_code: str
    change_pct: float
    turnover: float
    sector_code: str | None = None
    eligible: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        if self.turnover < 0:
            raise ValueError("成交额不能小于 0")
        if self.sector_code is not None:
            sector = self.sector_code.strip()
            object.__setattr__(self, "sector_code", sector or None)


@dataclass(frozen=True, slots=True, kw_only=True)
class CapitalBaseline:
    stock_code: str
    large_order_threshold: float
    flow_scale: float
    quality: DataQuality

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        if self.large_order_threshold <= 0 or self.flow_scale <= 0:
            raise ValueError("资金门槛和力度基准必须大于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivityMetrics:
    as_of: datetime
    score: float
    legacy_compatible_score: float
    turnover_rate: float | None
    turnover_amount: float
    volume: int
    is_active: bool
    quality: DataQuality
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_aware(self.as_of, "as_of")
        _validate_score(self.score)
        _validate_score(self.legacy_compatible_score, "legacy_compatible_score")
        if self.turnover_rate is not None and self.turnover_rate < 0:
            raise ValueError("turnover_rate 不能小于 0")
        if self.turnover_amount < 0 or self.volume < 0:
            raise ValueError("成交额和成交量不能小于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class LiquidityMetrics:
    as_of: datetime
    score: float
    level: str
    spread_pct: float | None
    lot_size: int | None
    lot_value: float | None
    turnover_amount: float
    quality: DataQuality
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_aware(self.as_of, "as_of")
        _validate_score(self.score)
        if self.level not in {"A", "B", "C", "D"}:
            raise ValueError("流动性等级必须是 A/B/C/D")
        if self.spread_pct is not None and self.spread_pct < 0:
            raise ValueError("spread_pct 不能小于 0")
        if self.lot_size is not None and self.lot_size <= 0:
            raise ValueError("lot_size 必须大于 0")
        if self.lot_value is not None and self.lot_value <= 0:
            raise ValueError("lot_value 必须大于 0")
        if self.turnover_amount < 0:
            raise ValueError("turnover_amount 不能小于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceAcceptance:
    as_of: datetime
    score: float
    confirmation_price: float | None
    current_price: float
    vwap: float | None
    return_from_confirmation_pct: float | None
    distance_to_vwap_pct: float | None
    drawdown_from_peak_pct: float | None
    accepted: bool
    quality: DataQuality
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_aware(self.as_of, "as_of")
        _validate_score(self.score)
        if self.current_price < 0:
            raise ValueError("current_price 不能小于 0")
        if self.confirmation_price is not None and self.confirmation_price <= 0:
            raise ValueError("confirmation_price 必须大于 0")
        if self.vwap is not None and self.vwap <= 0:
            raise ValueError("vwap 必须大于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketContext:
    as_of: datetime
    market_breadth: float
    market_sample_size: int
    sector_code: str | None
    sector_breadth: float | None
    sector_sample_size: int
    relative_strength: float | None
    quality: DataQuality
    turnover_rank_percentile: float | None = None
    market_regime: MarketRegime = MarketRegime.EXTREME

    def __post_init__(self) -> None:
        require_aware(self.as_of, "as_of")
        if not 0 <= self.market_breadth <= 1:
            raise ValueError("market_breadth 必须在 0 到 1 之间")
        if self.sector_breadth is not None and not 0 <= self.sector_breadth <= 1:
            raise ValueError("sector_breadth 必须在 0 到 1 之间")
        if self.market_sample_size < 0 or self.sector_sample_size < 0:
            raise ValueError("样本数不能小于 0")
        if (
            self.turnover_rank_percentile is not None
            and not 0 <= self.turnover_rank_percentile <= 1
        ):
            raise ValueError("turnover_rank_percentile 必须在 0 到 1 之间")


@dataclass(frozen=True, slots=True, kw_only=True)
class PricePosition:
    as_of: datetime
    daily_percentile: float
    atr_percent: float
    drawdown_from_high: float
    distance_to_ma20: float
    structure: str
    quality: DataQuality

    def __post_init__(self) -> None:
        require_aware(self.as_of, "as_of")
        if not 0 <= self.daily_percentile <= 1:
            raise ValueError("daily_percentile 必须在 0 到 1 之间")
        if self.atr_percent < 0:
            raise ValueError("atr_percent 不能小于 0")
        if not self.structure.strip():
            raise ValueError("structure 不能为空")


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureSnapshot:
    stock_code: str
    computed_at: datetime
    quote: QuoteSnapshot
    tick_windows: tuple[TickAggregate, ...]
    market_context: MarketContext
    price_position: PricePosition
    activity_score: float
    liquidity_score: float
    price_acceptance_score: float
    quality: DataQuality
    activity: ActivityMetrics | None = None
    liquidity: LiquidityMetrics | None = None
    price_acceptance: PriceAcceptance | None = None
    capital_memory: CapitalMemory | None = None
    missing_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        code = require_stock_code(self.stock_code)
        object.__setattr__(self, "stock_code", code)
        require_aware(self.computed_at, "computed_at")
        if self.quote.stock_code != code:
            raise ValueError("quote 与 FeatureSnapshot 的 stock_code 不一致")
        if any(window.stock_code != code for window in self.tick_windows):
            raise ValueError("tick_windows 与 FeatureSnapshot 的 stock_code 不一致")
        if self.capital_memory is not None and self.capital_memory.stock_code != code:
            raise ValueError("capital_memory 与 FeatureSnapshot 的 stock_code 不一致")
        for value in (
            self.activity_score,
            self.liquidity_score,
            self.price_acceptance_score,
        ):
            if not 0 <= value <= 100:
                raise ValueError("特征分数必须在 0 到 100 之间")
        if self.activity is not None and self.activity.score != self.activity_score:
            raise ValueError("activity_score 与 activity 明细不一致")
        if self.liquidity is not None and self.liquidity.score != self.liquidity_score:
            raise ValueError("liquidity_score 与 liquidity 明细不一致")
        if (
            self.price_acceptance is not None
            and self.price_acceptance.score != self.price_acceptance_score
        ):
            raise ValueError("price_acceptance_score 与 price_acceptance 明细不一致")
        if self.quality is DataQuality.GOOD and self.missing_fields:
            raise ValueError("GOOD 快照不能包含 missing_fields")
