"""市场事实 DTO。"""

from dataclasses import dataclass
from datetime import datetime

from .enums import CapitalMemoryState, DataQuality, TickDirection
from .serialization import require_aware, require_stock_code


@dataclass(frozen=True, slots=True, kw_only=True)
class QuoteSnapshot:
    stock_code: str
    exchange_time: datetime
    last_price: float
    prev_close: float
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    volume: int = 0
    turnover: float = 0.0
    turnover_rate: float | None = None
    amplitude: float | None = None
    lot_size: int | None = None
    sector_code: str | None = None
    quality: DataQuality = DataQuality.GOOD

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.exchange_time, "exchange_time")
        if self.last_price < 0 or self.prev_close < 0:
            raise ValueError("价格不能小于 0")
        if self.volume < 0 or self.turnover < 0:
            raise ValueError("成交量和成交额不能小于 0")
        if self.turnover_rate is not None and self.turnover_rate < 0:
            raise ValueError("换手率不能小于 0")
        if self.amplitude is not None and self.amplitude < 0:
            raise ValueError("振幅不能小于 0")
        if self.lot_size is not None and self.lot_size <= 0:
            raise ValueError("每手股数必须大于 0")
        if self.sector_code is not None:
            sector = self.sector_code.strip()
            object.__setattr__(self, "sector_code", sector or None)


@dataclass(frozen=True, slots=True, kw_only=True)
class TickTrade:
    stock_code: str
    exchange_time: datetime
    price: float
    volume: int
    turnover: float
    direction: TickDirection
    sequence: int | None
    quality: DataQuality = DataQuality.GOOD

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.exchange_time, "exchange_time")
        if self.price <= 0 or self.volume <= 0 or self.turnover < 0:
            raise ValueError("逐笔价格和数量必须大于 0，成交额不能小于 0")
        if self.sequence is not None and self.sequence < 0:
            raise ValueError("sequence 不能小于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderBookLevel:
    price: float
    volume: int
    order_count: int = 0

    def __post_init__(self) -> None:
        if self.price <= 0 or self.volume < 0 or self.order_count < 0:
            raise ValueError("盘口价格必须大于 0，数量和订单数不能小于 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderBookSnapshot:
    stock_code: str
    exchange_time: datetime
    bid_levels: tuple[OrderBookLevel, ...]
    ask_levels: tuple[OrderBookLevel, ...]
    quality: DataQuality

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.exchange_time, "exchange_time")
        if len(self.bid_levels) > 10 or len(self.ask_levels) > 10:
            raise ValueError("盘口最多保留十档")

    @property
    def best_bid(self) -> float | None:
        return self.bid_levels[0].price if self.bid_levels else None

    @property
    def best_ask(self) -> float | None:
        return self.ask_levels[0].price if self.ask_levels else None


@dataclass(frozen=True, slots=True, kw_only=True)
class TickAggregate:
    stock_code: str
    as_of: datetime
    window_seconds: int
    buy_amount: float
    sell_amount: float
    main_net: float
    big_buy_count: int
    big_sell_count: int
    independent_buy_events: int
    independent_sell_events: int
    buy_sell_ratio: float | None
    cumulative_main_net: float
    cumulative_peak: float
    cumulative_trough: float
    last_sequence: int | None
    sample_count: int
    quality: DataQuality
    large_order_threshold: float | None = None
    flow_scale: float | None = None
    first_independent_buy_at: datetime | None = None
    last_independent_buy_at: datetime | None = None
    first_independent_sell_at: datetime | None = None
    last_independent_sell_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.as_of, "as_of")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds 必须大于 0")
        counts = (
            self.big_buy_count,
            self.big_sell_count,
            self.independent_buy_events,
            self.independent_sell_events,
            self.sample_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("逐笔计数不能小于 0")
        if self.last_sequence is not None and self.last_sequence < 0:
            raise ValueError("last_sequence 不能小于 0")
        if self.buy_sell_ratio is not None and not 0 <= self.buy_sell_ratio <= 1:
            raise ValueError("buy_sell_ratio 必须在 0 到 1 之间")
        if self.large_order_threshold is not None and self.large_order_threshold <= 0:
            raise ValueError("large_order_threshold 必须大于 0")
        if self.flow_scale is not None and self.flow_scale <= 0:
            raise ValueError("flow_scale 必须大于 0")
        for field_name in (
            "first_independent_buy_at",
            "last_independent_buy_at",
            "first_independent_sell_at",
            "last_independent_sell_at",
        ):
            value = getattr(self, field_name)
            if value is not None:
                require_aware(value, field_name)

    @property
    def independent_buy_span_seconds(self) -> float:
        if self.first_independent_buy_at is None or self.last_independent_buy_at is None:
            return 0.0
        return max(
            0.0,
            (self.last_independent_buy_at - self.first_independent_buy_at).total_seconds(),
        )

    @property
    def net_direction(self) -> TickDirection:
        if self.main_net > 0:
            return TickDirection.BUY
        if self.main_net < 0:
            return TickDirection.SELL
        return TickDirection.NEUTRAL


@dataclass(frozen=True, slots=True, kw_only=True)
class CapitalMemory:
    stock_code: str
    as_of: datetime
    state: CapitalMemoryState
    score: float
    day_main_net: float
    day_peak: float
    day_trough: float
    day_recovery_ratio: float
    decayed_buy_amount: float
    decayed_sell_amount: float
    decayed_main_net: float
    decayed_buy_events: float
    decayed_sell_events: float
    recent_15m_main_net: float
    recent_15m_buy_events: int
    recent_15m_sell_events: int
    half_life_minutes: int
    quality: DataQuality
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", require_stock_code(self.stock_code))
        require_aware(self.as_of, "as_of")
        if not 0 <= self.score <= 100:
            raise ValueError("score 必须在 0 到 100 之间")
        if not 0 <= self.day_recovery_ratio <= 1:
            raise ValueError("day_recovery_ratio 必须在 0 到 1 之间")
        if self.decayed_buy_amount < 0 or self.decayed_sell_amount < 0:
            raise ValueError("衰减资金金额不能小于 0")
        if self.decayed_buy_events < 0 or self.decayed_sell_events < 0:
            raise ValueError("衰减事件数不能小于 0")
        if self.recent_15m_buy_events < 0 or self.recent_15m_sell_events < 0:
            raise ValueError("近期事件数不能小于 0")
        if self.half_life_minutes <= 0:
            raise ValueError("half_life_minutes 必须大于 0")
