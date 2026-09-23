"""Bounded, decimal-string read contracts with no execution authority."""

from dataclasses import dataclass
from datetime import datetime

from ..paper_session import PaperSessionStats


@dataclass(frozen=True, slots=True)
class LedgerOrder:
    plan_id: str
    stock_code: str
    approved_at: datetime
    status: str
    quantity: int
    bought: int
    sold: int
    held: int
    entry_remaining: int
    entry_min: str
    entry_limit: str
    stop_price: str
    valid_until: datetime
    exit_at: datetime
    entry_end_reason: str | None
    exit_reason: str | None
    closed_net_pnl: str | None


@dataclass(frozen=True, slots=True)
class LedgerFill:
    fill_id: str
    stock_code: str
    side: str
    quantity: int
    price: str
    fee: str
    exchange_time: datetime


@dataclass(frozen=True, slots=True)
class LedgerSignal:
    event_id: str
    stock_code: str
    processed_at: str
    reason: str


@dataclass(frozen=True, slots=True)
class PaperLedgerSnapshot:
    reported_at: datetime
    as_of: datetime | None
    account_id: str
    experiment_id: str
    strategy_id: str
    strategy_version: str
    stock_codes: tuple[str, ...]
    run_record_status: str
    run_error_code: str | None
    cash: str
    reserved_cash: str
    marked_equity: str
    closed_order_net_pnl: str
    closed_order_count: int
    fees: str
    stale_position_codes: tuple[str, ...]
    order_count: int
    orders: tuple[LedgerOrder, ...]
    fill_count: int
    recent_fills: tuple[LedgerFill, ...]
    recent_signals: tuple[LedgerSignal, ...]


@dataclass(frozen=True, slots=True)
class PaperLedgerView:
    status: str
    execution_enabled: bool
    runtime: PaperSessionStats | None
    ledger: PaperLedgerSnapshot | None
