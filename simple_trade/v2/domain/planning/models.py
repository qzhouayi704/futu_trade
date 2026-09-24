"""Decimal-valued contracts; these plans have no authority to trade live."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_UP
import hashlib
import math
import re

from ..serialization import require_aware, require_stock_code
from ..positions import PositionState
from ..enums import StringEnum


ZERO = Decimal("0")


class PaperExitPolicy(StringEnum):
    RESEARCH_ATR = "RESEARCH_ATR"
    PRODUCTION_RULES = "PRODUCTION_RULES"


def hk_stock_code(value: str) -> str:
    code = require_stock_code(value)
    if re.fullmatch(r"HK\.[0-9]{5}", code) is None:
        raise ValueError("the paper ledger currently supports HK securities only")
    return code


def positive(value: Decimal, name: str, *, allow_zero: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    if value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{name} is outside its allowed range")


def integer(value: int, name: str, *, minimum: int = 1) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


@dataclass(frozen=True, slots=True, kw_only=True)
class PaperPolicy:
    initial_cash: Decimal
    fee_rate: Decimal
    minimum_fee: Decimal
    currency: str = "HKD"
    risk_fraction: Decimal = Decimal("0.0025")
    portfolio_risk_fraction: Decimal = Decimal("0.0075")
    position_fraction: Decimal = Decimal("0.10")
    cash_reserve_fraction: Decimal = Decimal("0.30")
    participation_fraction: Decimal = Decimal("0.10")
    max_positions: int = 3
    latency_seconds: int = 1
    max_book_age_seconds: int = 3

    def __post_init__(self) -> None:
        if self.currency != "HKD":
            raise ValueError("the paper ledger currently supports HKD only")
        positive(self.initial_cash, "initial_cash")
        for name in ("fee_rate", "minimum_fee"):
            positive(getattr(self, name), name, allow_zero=True)
        if self.fee_rate > 1:
            raise ValueError("fee_rate must not exceed one")
        for name in ("risk_fraction", "portfolio_risk_fraction", "position_fraction",
                     "cash_reserve_fraction", "participation_fraction"):
            value = getattr(self, name)
            positive(value, name, allow_zero=name == "cash_reserve_fraction")
            if value > 1 or (name == "cash_reserve_fraction" and value == 1):
                raise ValueError(f"{name} is outside [0, 1]")
        if self.risk_fraction > self.portfolio_risk_fraction:
            raise ValueError("per-plan risk exceeds portfolio risk")
        for name in ("max_positions", "latency_seconds", "max_book_age_seconds"):
            integer(getattr(self, name), name)

    def fee(self, notional: Decimal) -> Decimal:
        return max(self.minimum_fee, notional * self.fee_rate).quantize(
            Decimal("0.01"), rounding=ROUND_UP
        ) if notional > 0 else ZERO


@dataclass(frozen=True, slots=True, kw_only=True)
class EntrySetup:
    setup_id: str
    source_event_id: str
    strategy_id: str
    strategy_version: str
    stock_code: str
    created_at: datetime
    valid_until: datetime
    exit_at: datetime
    entry_min: Decimal
    entry_limit: Decimal
    stop_price: Decimal
    lot_size: int
    take_profit: Decimal | None = None
    position_fraction: Decimal | None = None
    exit_policy: PaperExitPolicy = PaperExitPolicy.RESEARCH_ATR

    def __post_init__(self) -> None:
        object.__setattr__(self, "exit_policy", PaperExitPolicy(self.exit_policy))
        for name in ("setup_id", "source_event_id", "strategy_id", "strategy_version"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        object.__setattr__(self, "stock_code", hk_stock_code(self.stock_code))
        for name in ("created_at", "valid_until", "exit_at"):
            require_aware(getattr(self, name), name)
        if not self.created_at < self.valid_until <= self.exit_at:
            raise ValueError("entry validity must precede the exit deadline")
        for name in ("entry_min", "entry_limit", "stop_price"):
            positive(getattr(self, name), name)
        if not self.stop_price < self.entry_min <= self.entry_limit:
            raise ValueError("invalid long-entry price structure")
        integer(self.lot_size, "lot_size")
        if self.position_fraction is not None:
            positive(self.position_fraction, "position_fraction")
            if self.position_fraction > 1:
                raise ValueError("position_fraction must not exceed one")
        if self.take_profit is not None:
            positive(self.take_profit, "take_profit")
            if self.take_profit <= self.entry_limit:
                raise ValueError("take profit must exceed the maximum entry price")

    def plan_id(self, account_id: str) -> str:
        # Length-prefixed components prevent ambiguous concatenated identifiers.
        parts = (account_id, self.strategy_id, self.strategy_version, self.setup_id)
        key = "".join(f"{len(part)}:{part}" for part in parts)
        return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class TradePlan:
    plan_id: str
    setup: EntrySetup
    quantity: int
    approved_at: datetime
    initial_risk: Decimal

    def __post_init__(self) -> None:
        integer(self.quantity, "quantity")
        if not self.plan_id or self.quantity % self.setup.lot_size:
            raise ValueError("plan must have an id and board-lot quantity")
        require_aware(self.approved_at, "approved_at")
        if not self.setup.created_at <= self.approved_at < self.setup.valid_until:
            raise ValueError("approval outside entry validity")
        positive(self.initial_risk, "initial_risk")


@dataclass(frozen=True, slots=True, kw_only=True)
class PaperBook:
    event_id: str
    stock_code: str
    exchange_time: datetime
    received_at: datetime
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int
    market_open: bool
    quality_good: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", hk_stock_code(self.stock_code))
        if not self.event_id:
            raise ValueError("book event id is required")
        for name in ("exchange_time", "received_at"):
            require_aware(getattr(self, name), name)
        for name in ("bid", "ask"):
            positive(getattr(self, name), name)
        for name in ("bid_size", "ask_size"):
            integer(getattr(self, name), name, minimum=0)
        if self.bid > self.ask:
            raise ValueError("crossed book is not executable")
        if type(self.market_open) is not bool or type(self.quality_good) is not bool:
            raise ValueError("book quality and session flags must be boolean")


@dataclass(frozen=True, slots=True, kw_only=True)
class PaperFill:
    fill_id: str
    plan_id: str
    book_event_id: str
    side: str
    quantity: int
    price: Decimal
    fee: Decimal
    exchange_time: datetime

    def __post_init__(self) -> None:
        if not self.fill_id or not self.plan_id or not self.book_event_id:
            raise ValueError("fill identity is required")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("unsupported paper fill side")
        integer(self.quantity, "quantity")
        positive(self.price, "price")
        positive(self.fee, "fee", allow_zero=True)
        require_aware(self.exchange_time, "exchange_time")


@dataclass(slots=True, kw_only=True)
class PaperOrder:
    plan: TradePlan
    entry_remaining: int
    bought: int = 0
    sold: int = 0
    buy_notional: Decimal = ZERO
    sell_notional: Decimal = ZERO
    buy_fee: Decimal = ZERO
    sell_fee: Decimal = ZERO
    entry_end_reason: str | None = None
    exit_reason: str | None = None
    exit_triggered_at: datetime | None = None
    position_state: PositionState | None = None
    price_history: tuple[tuple[datetime, float], ...] = ()

    def __post_init__(self) -> None:
        for name in ("entry_remaining", "bought", "sold"):
            integer(getattr(self, name), name, minimum=0)
        for name in ("buy_notional", "sell_notional", "buy_fee", "sell_fee"):
            positive(getattr(self, name), name, allow_zero=True)
        if bool(self.exit_reason) != (self.exit_triggered_at is not None):
            raise ValueError("exit reason and trigger time must be recorded together")
        if self.exit_triggered_at is not None:
            require_aware(self.exit_triggered_at, "exit_triggered_at")
        if self.position_state is not None:
            if (self.plan.setup.exit_policy is not PaperExitPolicy.PRODUCTION_RULES
                    or self.position_state.stock_code != self.plan.setup.stock_code
                    or self.position_state.strategy_version != self.plan.setup.strategy_version
                    or not self.bought):
                raise ValueError("paper position analysis does not match its filled plan")
        if len(self.price_history) > 2048:
            raise ValueError("paper position price history exceeds budget")
        for stamp, price in self.price_history:
            require_aware(stamp, "paper price time")
            if not math.isfinite(price) or price <= 0:
                raise ValueError("invalid paper price history")
        if any(a[0] >= b[0] for a, b in zip(self.price_history, self.price_history[1:])):
            raise ValueError("paper price history must be chronological")

    @property
    def held(self) -> int:
        return self.bought - self.sold

    @property
    def active(self) -> bool:
        return bool(self.entry_remaining or self.held)

    @property
    def status(self) -> str:
        if self.exit_reason and self.held:
            return "EXIT_PENDING"
        if self.entry_remaining:
            return "PARTIALLY_FILLED" if self.bought else "WORKING"
        if self.held:
            return "HOLDING"
        if self.bought:
            return "CLOSED"
        return self.entry_end_reason or "CANCELLED"

    def reserved_cash(self, policy: PaperPolicy) -> Decimal:
        if not self.entry_remaining:
            return ZERO
        remaining = self.entry_remaining * self.plan.setup.entry_limit
        return remaining + policy.fee(self.buy_notional + remaining) - self.buy_fee

    def risk(self, policy: PaperPolicy) -> Decimal:
        quantity = self.held + self.entry_remaining
        if not quantity:
            return ZERO
        setup = self.plan.setup
        return (quantity * (setup.entry_limit - setup.stop_price)
                + policy.fee(quantity * setup.entry_limit)
                + policy.fee(quantity * setup.stop_price))


@dataclass(slots=True, kw_only=True)
class PaperAccount:
    account_id: str
    policy: PaperPolicy
    cash: Decimal
    as_of: datetime | None = None
    orders: list[PaperOrder] = field(default_factory=list)
    fills: list[PaperFill] = field(default_factory=list)
    marks: dict[str, Decimal] = field(default_factory=dict)
    book_times: dict[str, datetime] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.account_id.startswith("paper:") or not self.account_id[6:].strip():
            raise ValueError("only explicitly named paper accounts are supported")
        positive(self.cash, "cash", allow_zero=True)
        if self.as_of is not None:
            require_aware(self.as_of, "as_of")
        for code, value in self.marks.items():
            positive(value, f"mark:{code}")
        for code, when in self.book_times.items():
            require_aware(when, f"book_time:{code}")

    @property
    def equity(self) -> Decimal:
        return self.cash + sum((order.held * self.marks.get(
            order.plan.setup.stock_code,
            order.buy_notional / order.bought if order.bought else ZERO,
        ) for order in self.orders), ZERO)

    @property
    def reserved_cash(self) -> Decimal:
        return sum((order.reserved_cash(self.policy) for order in self.orders), ZERO)


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanAssessment:
    plan_id: str
    reason: str
    plan: TradePlan | None = None
