"""Causal best-book paper fills; explicit approximation, never a live executor."""

from datetime import datetime
from decimal import Decimal
import hashlib

from ...domain.planning.models import (
    EntrySetup, PaperAccount, PaperBook, PaperExitPolicy, PaperFill, PaperOrder, PlanAssessment,
)
from ...domain.serialization import require_aware
from .builder import PlanBuilder


class PaperEngine:
    @staticmethod
    def advance(account: PaperAccount, when: datetime) -> None:
        require_aware(when, "when")
        if account.as_of is not None and when < account.as_of:
            raise ValueError("account clock cannot move backwards")
        account.as_of = when
        for order in account.orders:
            if order.entry_remaining and when >= order.plan.setup.valid_until:
                order.entry_remaining = 0
                order.entry_end_reason = "ENTRY_EXPIRED"
            if order.held and when >= order.plan.setup.exit_at:
                PaperEngine._trigger_exit(order, "HOLDING_DEADLINE", when)

    @classmethod
    def submit(cls, account: PaperAccount, setup: EntrySetup, when: datetime) -> PlanAssessment:
        cls.advance(account, when)
        assessment = PlanBuilder.assess(account, setup, when)
        if assessment.plan is not None and assessment.reason == "PAPER_PLAN_APPROVED":
            account.orders.append(PaperOrder(plan=assessment.plan,
                                             entry_remaining=assessment.plan.quantity))
        return assessment

    @classmethod
    def cancel_entry(cls, account: PaperAccount, plan_id: str, when: datetime) -> None:
        cls.advance(account, when)
        order = next((item for item in account.orders if item.plan.plan_id == plan_id), None)
        if order is None:
            raise ValueError("unknown paper plan")
        order.entry_remaining = 0
        order.entry_end_reason = "ENTRY_CANCELLED"

    @classmethod
    def request_exit(cls, account: PaperAccount, order: PaperOrder, reason: str, when: datetime) -> None:
        cls.advance(account, when)
        if not any(item is order for item in account.orders) or not order.held or not reason:
            raise ValueError("an exit requires an owned, filled paper position and a reason")
        cls._trigger_exit(order, reason, when)

    @classmethod
    def on_book(cls, account: PaperAccount, book: PaperBook) -> str:
        cls.advance(account, book.received_at)
        age = (book.received_at - book.exchange_time).total_seconds()
        if not book.quality_good or not 0 <= age <= account.policy.max_book_age_seconds:
            return "BOOK_UNUSABLE"
        previous = account.book_times.get(book.stock_code)
        if previous is not None and book.exchange_time <= previous:
            return "BOOK_NOT_NEWER"
        if not book.market_open:
            return "MARKET_CLOSED"
        account.book_times[book.stock_code] = book.exchange_time
        account.marks[book.stock_code] = book.bid
        for order in account.orders:
            if order.active and order.plan.setup.stock_code == book.stock_code:
                cls._match(account, order, book)
        return "BOOK_PROCESSED"

    @classmethod
    def _match(cls, account: PaperAccount, order: PaperOrder, book: PaperBook) -> None:
        setup = order.plan.setup
        if order.exit_reason is not None:
            elapsed = (book.exchange_time - order.exit_triggered_at).total_seconds()
            if order.held and elapsed >= account.policy.latency_seconds:
                quantity = cls._capacity(account, book.bid_size, setup.lot_size, order.held)
                if quantity:
                    cls._fill(account, order, book, "SELL", quantity, book.bid)
            return
        research_exit = setup.exit_policy is PaperExitPolicy.RESEARCH_ATR
        if book.bid <= setup.stop_price and (research_exit or not order.held):
            order.entry_remaining = 0
            order.entry_end_reason = "ENTRY_STRUCTURE_BROKEN"
            if order.held:
                cls._trigger_exit(order, "STOP_BROKEN", book.received_at)
            return
        if research_exit and order.held and setup.take_profit is not None and book.bid >= setup.take_profit:
            cls._trigger_exit(order, "TAKE_PROFIT", book.received_at)
            return
        elapsed = (book.exchange_time - order.plan.approved_at).total_seconds()
        if (order.entry_remaining and elapsed >= account.policy.latency_seconds
                and setup.entry_min <= book.ask <= setup.entry_limit):
            quantity = cls._capacity(account, book.ask_size, setup.lot_size, order.entry_remaining)
            if quantity:
                cls._fill(account, order, book, "BUY", quantity, book.ask)

    @staticmethod
    def _capacity(account: PaperAccount, size: int, lot: int, remaining: int) -> int:
        return min(remaining, int(size * account.policy.participation_fraction) // lot * lot)

    @staticmethod
    def _trigger_exit(order: PaperOrder, reason: str, when: datetime) -> None:
        order.entry_remaining = 0
        if order.exit_reason is None:
            order.exit_reason = reason
            order.exit_triggered_at = when

    @staticmethod
    def _fill(account: PaperAccount, order: PaperOrder, book: PaperBook,
              side: str, quantity: int, price: Decimal) -> None:
        notional = price * quantity
        if side == "BUY":
            fee = account.policy.fee(order.buy_notional + notional) - order.buy_fee
            account.cash -= notional + fee
            order.entry_remaining -= quantity
            order.bought += quantity
            order.buy_notional += notional
            order.buy_fee += fee
            cumulative = order.bought
        else:
            fee = account.policy.fee(order.sell_notional + notional) - order.sell_fee
            account.cash += notional - fee
            order.sold += quantity
            order.sell_notional += notional
            order.sell_fee += fee
            cumulative = order.sold
        key = f"{order.plan.plan_id}:{side}:{cumulative}:{book.event_id}"
        account.fills.append(PaperFill(
            fill_id=hashlib.sha256(key.encode("utf-8")).hexdigest(),
            plan_id=order.plan.plan_id, book_event_id=book.event_id,
            side=side, quantity=quantity, price=price, fee=fee,
            exchange_time=book.exchange_time,
        ))

    @staticmethod
    def assert_invariants(account: PaperAccount) -> None:
        if account.cash < 0 or account.reserved_cash > account.cash:
            raise ValueError("paper account cash/reservation invariant failed")
        active_codes: set[str] = set()
        fill_ids = {fill.fill_id for fill in account.fills}
        if len(fill_ids) != len(account.fills):
            raise ValueError("duplicate paper fill")
        expected_cash = account.policy.initial_cash + sum((
            (fill.quantity * fill.price if fill.side == "SELL" else -fill.quantity * fill.price)
            - fill.fee for fill in account.fills
        ), Decimal("0"))
        if expected_cash != account.cash:
            raise ValueError("paper cash does not reconcile to fills")
        plan_ids = {order.plan.plan_id for order in account.orders}
        if len(plan_ids) != len(account.orders) or any(fill.plan_id not in plan_ids for fill in account.fills):
            raise ValueError("duplicate plan or orphan paper fill")
        for order in account.orders:
            if order.plan.plan_id != order.plan.setup.plan_id(account.account_id):
                raise ValueError("plan belongs to a different account/setup")
            fills = [fill for fill in account.fills if fill.plan_id == order.plan.plan_id]
            for side, quantity, notional, fee in (
                ("BUY", order.bought, order.buy_notional, order.buy_fee),
                ("SELL", order.sold, order.sell_notional, order.sell_fee),
            ):
                matched = [fill for fill in fills if fill.side == side]
                if (sum(fill.quantity for fill in matched) != quantity
                        or sum((fill.quantity * fill.price for fill in matched), Decimal("0")) != notional
                        or sum((fill.fee for fill in matched), Decimal("0")) != fee):
                    raise ValueError("paper order does not reconcile to fills")
            if not (0 <= order.sold <= order.bought <= order.plan.quantity):
                raise ValueError("paper filled quantity invariant failed")
            if not 0 <= order.entry_remaining <= order.plan.quantity - order.bought:
                raise ValueError("paper remaining quantity invariant failed")
            if order.exit_reason and order.entry_remaining:
                raise ValueError("cannot add to a position with a pending exit")
            if order.active:
                code = order.plan.setup.stock_code
                if code in active_codes:
                    raise ValueError("multiple active allocations for one stock")
                active_codes.add(code)
