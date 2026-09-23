"""Minute-range stress scenarios, explicitly NOT historical order-book replay."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import statistics

from simple_trade.v2.application.planning.paper_engine import PaperEngine
from simple_trade.v2.domain.planning.codec import encode
from simple_trade.v2.domain.planning.models import EntrySetup, PaperAccount, PaperBook, PaperPolicy, integer, positive
from .data import Minute, moment, readiness, regular, select, validate
from .coverage import coverage


@dataclass(frozen=True, kw_only=True)
class StressAssumptions:
    assumed_lot_size: int
    slippage_fraction: Decimal
    stop_fraction: Decimal = Decimal("0.03")
    entry_band_fraction: Decimal = Decimal("0.01")
    take_profit_fraction: Decimal | None = Decimal("0.05")
    entry_valid_minutes: int = 10

    def __post_init__(self) -> None:
        integer(self.assumed_lot_size, "assumed_lot_size")
        integer(self.entry_valid_minutes, "entry_valid_minutes")
        for key in ("slippage_fraction", "stop_fraction", "entry_band_fraction"):
            value = getattr(self, key)
            positive(value, key, allow_zero=key == "slippage_fraction")
            if value >= 1:
                raise ValueError(f"{key} must be less than one")
        if self.stop_fraction <= self.entry_band_fraction:
            raise ValueError("stop must be below the assumed entry range")
        if self.take_profit_fraction is not None:
            positive(self.take_profit_fraction, "take_profit_fraction")
            if self.take_profit_fraction <= self.entry_band_fraction:
                raise ValueError("take profit must exceed the assumed entry range")


def make_setup(row: dict, assumptions: StressAssumptions, version: str) -> EntrySetup | None:
    when = moment(row["received_time"])
    deadline = when.replace(hour=15, minute=50, second=0, microsecond=0)
    if when + timedelta(minutes=2) >= deadline:
        return None
    price = Decimal(str(row["quote"].get("last_price") or 0))
    positive(price, "signal reference price")
    return EntrySetup(
        setup_id=row["event_id"], source_event_id=row["event_id"],
        strategy_id="archived_signal_assumed_intraday_exit", strategy_version=version,
        stock_code=row["stock_code"], created_at=when,
        valid_until=min(when + timedelta(minutes=assumptions.entry_valid_minutes), deadline),
        exit_at=deadline, entry_min=price * (1 - assumptions.entry_band_fraction),
        entry_limit=price * (1 + assumptions.entry_band_fraction),
        stop_price=price * (1 - assumptions.stop_fraction),
        lot_size=assumptions.assumed_lot_size,
        take_profit=(price * (1 + assumptions.take_profit_fraction)
                     if assumptions.take_profit_fraction is not None else None),
    )


def on_minute(account: PaperAccount, bar: Minute, assumptions: StressAssumptions) -> str:
    """Pessimistic range prices are synthetic stress inputs, never historical quotes."""
    arrival = bar.end + timedelta(seconds=1)
    PaperEngine.advance(account, arrival)
    bid = bar.low * (1 - assumptions.slippage_fraction)
    ask = bar.high * (1 + assumptions.slippage_fraction)
    # The entire consumed minute must follow the relevant decision/exit trigger.
    for order in account.orders:
        if order.active and order.plan.setup.stock_code == bar.stock_code:
            action_at = order.exit_triggered_at or order.plan.approved_at
            if action_at > bar.start:
                account.marks[bar.stock_code] = bid
                account.book_times[bar.stock_code] = bar.end
                return "MINUTE_CONTAINS_OR_PRECEDES_ACTION"
    return PaperEngine.on_book(account, PaperBook(
        event_id=f"minute-stress:{bar.stock_code}:{bar.start.isoformat()}",
        stock_code=bar.stock_code, exchange_time=bar.end, received_at=arrival,
        bid=bid, ask=ask, bid_size=bar.volume, ask_size=bar.volume, market_open=True,
    ))


def stale_marks(account: PaperAccount) -> list[dict]:
    stale = []
    for order in account.orders:
        if order.held:
            code = order.plan.setup.stock_code
            marked = account.book_times.get(code)
            age = (account.as_of - marked).total_seconds() if marked is not None and account.as_of else None
            if age is None or age > account.policy.max_book_age_seconds:
                stale.append({"stock_code": code, "marked_at": marked, "age_seconds": age,
                              "held": order.held, "exit_reason": order.exit_reason})
    return stale


def performance(account: PaperAccount) -> dict:
    trades = []
    for order in account.orders:
        if not order.bought:
            continue
        closed = order.held == 0
        pnl = order.sell_notional - order.buy_notional - order.buy_fee - order.sell_fee if closed else None
        trades.append({
            "source_event_id": order.plan.setup.source_event_id,
            "stock_code": order.plan.setup.stock_code, "signal_at": order.plan.setup.created_at,
            "status": order.status, "bought": order.bought, "sold": order.sold,
            "held": order.held, "entry_price": order.buy_notional / order.bought,
            "exit_price": order.sell_notional / order.sold if order.sold else None,
            "exit_reason": order.exit_reason, "net_pnl_if_closed": pnl,
            "net_return_pct_if_closed": pnl / (order.buy_notional + order.buy_fee) * 100 if closed else None,
        })
    returns = [row["net_return_pct_if_closed"] for row in trades if row["net_return_pct_if_closed"] is not None]
    bins = Counter({key: 0 for key in ("below_-5", "-5_to_-2", "-2_to_0", "0_to_2", "2_to_5", "at_least_5")})
    for value in returns:
        key = ("below_-5" if value < -5 else "-5_to_-2" if value < -2 else "-2_to_0" if value < 0
               else "0_to_2" if value < 2 else "2_to_5" if value < 5 else "at_least_5")
        bins[key] += 1
    stale = stale_marks(account)
    pnl = account.equity - account.policy.initial_cash
    return {
        "initial_cash": account.policy.initial_cash, "cash": account.cash,
        "reserved_cash": account.reserved_cash, "marked_equity": account.equity,
        "marked_net_pnl_not_fully_realized": pnl,
        "portfolio_return_pct": pnl / account.policy.initial_cash * 100 if not stale else None,
        "all_positions_closed": not any(order.held for order in account.orders),
        "stale_open_marks": stale,
        "future_liquidation_cost_included": False,
        "fees": sum((fill.fee for fill in account.fills), Decimal(0)),
        "plans": len(account.orders), "trades_with_entry": len(trades),
        "closed_trades": len(returns), "profitable_closed_trades": sum(value > 0 for value in returns),
        "closed_win_rate_pct": Decimal(sum(value > 0 for value in returns)) / len(returns) * 100 if returns else None,
        "closed_return_median_pct": statistics.median(returns) if returns else None,
        "closed_return_distribution_pct": dict(bins), "trades": trades, "fills": account.fills,
        "unfilled_plans": [{"source_event_id": order.plan.setup.source_event_id,
                            "stock_code": order.plan.setup.stock_code, "status": order.status}
                           for order in account.orders if not order.bought],
    }


def study(payload: dict, cohort: str, policy: PaperPolicy, assumptions: StressAssumptions) -> dict:
    decisions, minutes = validate(payload)
    selected, exclusions = select(decisions, cohort)
    version = "minute-range-stress-v2:" + hashlib.sha256(encode({
        "policy": policy, "assumptions": assumptions,
    }).encode()).hexdigest()[:16]
    account = PaperAccount(account_id=f"paper:history:{cohort}:{version}", policy=policy, cash=policy.initial_cash)
    events = []
    skipped, outcomes = Counter(), []
    for row in selected:
        setup = make_setup(row, assumptions, version)
        if setup is None:
            skipped["TOO_LATE_FOR_ASSUMED_INTRADAY_EXIT"] += 1
        else:
            events.append((setup.created_at, 2, setup.source_event_id, "plan", setup))
            events.append((setup.exit_at, 0, setup.source_event_id, "clock", None))
    codes = {row["stock_code"] for row in selected}
    days = {moment(row["received_time"]).date().isoformat() for row in selected}
    for bar in minutes:
        if bar.stock_code in codes and regular(bar.start):
            events.append((bar.end + timedelta(seconds=1), 1, bar.stock_code, "minute", bar))
            days.add(bar.start.date().isoformat())
    for day in sorted(days):
        events.append((datetime.fromisoformat(day + "T16:01:01+08:00"), 3, day, "close", None))
    peak, drawdown, max_reserved = policy.initial_cash, Decimal(0), Decimal(0)
    max_exposure = Decimal(0)
    daily = []
    for when, _, _, kind, item in sorted(events, key=lambda event: event[:3]):
        if kind == "plan":
            result = PaperEngine.submit(account, item, when)
            outcomes.append({"source_event_id": item.source_event_id, "stock_code": item.stock_code,
                             "when": when, "reason": result.reason,
                             "quantity": result.plan.quantity if result.plan else 0,
                             "stale_holdings": stale_marks(account) if result.reason == "ACCOUNT_MARK_STALE" else []})
        elif kind == "minute":
            on_minute(account, item, assumptions)
        else:
            PaperEngine.advance(account, when)
            if kind == "close":
                daily.append({"day": when.date().isoformat(), "marked_equity": account.equity,
                              "cash": account.cash, "open_positions": sum(order.held > 0 for order in account.orders),
                              "stale_open_marks": stale_marks(account)})
        peak = max(peak, account.equity)
        drawdown = max(drawdown, (peak - account.equity) / peak * 100)
        max_reserved = max(max_reserved, account.reserved_cash)
        max_exposure = max(max_exposure, account.equity - account.cash)
    PaperEngine.assert_invariants(account)
    return {
        "mode": "MINUTE_RANGE_STRESS_NOT_EXECUTION_BACKTEST", "cohort": cohort,
        "scenario_version": version, "assumptions": asdict(assumptions), "policy": asdict(policy),
        "selected_stock_days": len(selected), "exclusions": exclusions, "skipped": dict(skipped),
        "strict_readiness": readiness(selected, minutes),
        "post_signal_archive_coverage": coverage(selected, minutes),
        "allocation_affected_by_stale_marks": any(row["stale_holdings"] for row in outcomes),
        "assessment_counts": dict(Counter(row["reason"] for row in outcomes)), "assessments": outcomes,
        "max_marked_drawdown_pct": drawdown, "max_reserved_cash": max_reserved,
        "max_marked_exposure": max_exposure, "daily": daily, **performance(account),
    }
