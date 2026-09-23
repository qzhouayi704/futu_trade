from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from simple_trade.v2.application.planning.builder import PlanBuilder
from simple_trade.v2.application.planning.paper_engine import PaperEngine
from simple_trade.v2.application.planning.paper_service import PaperTradingService
from simple_trade.v2.domain.planning.codec import encode_account, decode_account
from simple_trade.v2.domain.planning.models import EntrySetup, PaperAccount, PaperBook, PaperPolicy
from simple_trade.v2.infrastructure.paper.sqlite_account_store import SqlitePaperAccountStore
from simple_trade.v2.application.strategy.assessments import EntryPlan


D = Decimal
NOW = datetime(2026, 9, 21, 10, tzinfo=timezone(timedelta(hours=8)))
POLICY = PaperPolicy(initial_cash=D("100000"), fee_rate=D("0.001"), minimum_fee=D("3"),
                     risk_fraction=D("0.01"), portfolio_risk_fraction=D("0.03"))


def setup(**changes) -> EntrySetup:
    return replace(EntrySetup(
        setup_id="test-setup", source_event_id="decision-1", strategy_id="test-only",
        strategy_version="test-v1", stock_code="HK.00100", created_at=NOW,
        valid_until=NOW + timedelta(minutes=5), exit_at=NOW + timedelta(hours=1),
        entry_min=D("9.8"), entry_limit=D("10"), stop_price=D("9.5"),
        take_profit=D("11"), lot_size=100,
    ), **changes)


def book(seconds: int, **changes) -> PaperBook:
    when = NOW + timedelta(seconds=seconds)
    return replace(PaperBook(
        event_id=f"book-{seconds}", stock_code="HK.00100", exchange_time=when,
        received_at=when, bid=D("9.99"), ask=D("10"), bid_size=2000,
        ask_size=2000, market_open=True,
    ), **changes)


class PaperContractTests(unittest.TestCase):
    def test_prices_must_be_finite_decimal_and_stop_below_entry(self):
        for changes in ({"entry_limit": D("NaN")}, {"stop_price": D("10")},
                        {"entry_min": 9.8}, {"lot_size": 1.5}, {"lot_size": True},
                        {"valid_until": NOW}, {"created_at": NOW.replace(tzinfo=None)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                setup(**changes)

    def test_policy_is_explicit_and_account_is_paper_only(self):
        with self.assertRaises(ValueError):
            PaperAccount(account_id="real", policy=POLICY, cash=POLICY.initial_cash)
        with self.assertRaises(ValueError):
            replace(POLICY, fee_rate=D("Infinity"))
        with self.assertRaises(ValueError):
            replace(POLICY, participation_fraction=D("1.1"))
        with self.assertRaises(ValueError):
            book(1, market_open="true")
        with self.assertRaises(ValueError):
            setup(stock_code="US.AAPL")
        with self.assertRaises(ValueError):
            replace(POLICY, currency="USD")

    def test_plan_id_is_stable_and_scoped_to_strategy_account_and_setup(self):
        item = setup()
        self.assertEqual(item.plan_id("paper:a"), item.plan_id("paper:a"))
        self.assertNotEqual(item.plan_id("paper:a"), item.plan_id("paper:b"))
        self.assertNotEqual(item.plan_id("paper:a"), replace(item, strategy_version="v2").plan_id("paper:a"))

    def test_existing_entry_plan_contract_preserves_position_cap(self):
        proposal = EntryPlan(setup_id="proposal", stock_code="HK.00100", strategy_id="test",
                             as_of=NOW, reference_price=10, entry_price_min=9.8,
                             entry_price_max=10, max_chase_price=10.1, invalidation_price=9.5,
                             initial_position_ratio=0.02, holding_minutes=60)
        item = PlanBuilder.from_entry_plan(
            proposal, source_event_id="event", strategy_version="v1", lot_size=100,
            valid_until=NOW + timedelta(minutes=5), exit_at=NOW + timedelta(hours=1),
        )
        account = PaperAccount(account_id="paper:bridge", policy=POLICY, cash=POLICY.initial_cash)
        result = PaperEngine.submit(account, item, NOW)
        self.assertEqual(result.plan.quantity, 200)
        self.assertEqual(item.entry_limit, D("10"))
        with self.assertRaises(ValueError):
            PlanBuilder.from_entry_plan(
                replace(proposal, exit_conditions=("unmodeled-condition",)),
                source_event_id="event", strategy_version="v1", lot_size=100,
                valid_until=item.valid_until, exit_at=item.exit_at,
            )


class PaperLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "paper.db"
        self.service = self.open_service()

    def open_service(self, policy=POLICY):
        return PaperTradingService(SqlitePaperAccountStore(self.path, "paper:test", policy))

    def submit(self, item=None, event="plan-1", when=NOW):
        return json.loads(self.service.submit(event, item or setup(), when))

    def test_approval_reserves_cash_without_inventing_a_fill(self):
        result = self.submit()
        self.assertEqual(result["reason"], "PAPER_PLAN_APPROVED")
        account = self.service.snapshot()
        self.assertEqual(account.orders[0].plan.quantity, 1000)
        self.assertEqual(account.reserved_cash, D("10010"))
        self.assertEqual(account.cash, POLICY.initial_cash)
        self.assertEqual(account.fills, [])

    def test_risk_distance_reduces_quantity_and_below_one_lot_is_skipped(self):
        self.submit(setup(stop_price=D("5")))
        self.assertEqual(self.service.snapshot().orders[0].plan.quantity, 100)
        other = PaperAccount(account_id="paper:small", policy=replace(POLICY, initial_cash=D("100")), cash=D("100"))
        result = PaperEngine.submit(other, setup(), NOW)
        self.assertEqual(result.reason, "BELOW_ONE_LOT_BUDGET")
        self.assertEqual(other.orders, [])

    def test_no_same_observation_fill_and_no_chasing(self):
        self.submit()
        self.service.on_book(book(0))
        self.service.on_book(book(1, ask=D("10.1")))
        self.service.on_book(book(2, bid=D("9.7"), ask=D("9.79")))
        self.assertEqual(self.service.snapshot().fills, [])
        self.service.on_book(book(3))
        self.assertEqual(self.service.snapshot().orders[0].held, 200)

    def test_partial_fills_charge_minimum_fee_once_per_order_side(self):
        self.submit()
        self.service.on_book(book(1))
        self.service.on_book(book(2))
        account = self.service.snapshot()
        self.assertEqual([fill.fee for fill in account.fills], [D("3"), D("1")])
        self.assertEqual(account.orders[0].status, "PARTIALLY_FILLED")
        self.assertEqual(account.reserved_cash, D("6006"))
        self.assertEqual(account.cash, D("95996"))

    def test_duplicate_events_and_same_timestamp_never_duplicate_fills(self):
        self.submit()
        original = self.service.on_book(book(1))
        self.assertEqual(self.service.on_book(book(1)), original)
        self.assertEqual(json.loads(self.service.on_book(book(1, event_id="duplicate-time"))), "BOOK_NOT_NEWER")
        self.assertEqual(len(self.service.snapshot().fills), 1)
        with self.assertRaises(ValueError):
            self.service.on_book(book(1, ask=D("10.1")))
        self.assertEqual(len(self.service.snapshot().fills), 1)

    def test_duplicate_setup_across_event_ids_does_not_allocate_twice(self):
        first = self.submit()
        second = self.submit(event="plan-2")
        self.assertEqual(first["plan"]["plan_id"], second["plan"]["plan_id"])
        self.assertEqual(second["reason"], "ALREADY_PLANNED")
        self.assertEqual(len(self.service.snapshot().orders), 1)
        with self.assertRaises(ValueError):
            self.submit(setup(stop_price=D("9.4")), event="plan-3")

    def test_restart_keeps_reservations_positions_and_deduplication(self):
        self.submit()
        self.service.on_book(book(1))
        before = encode_account(self.service.snapshot())
        self.service = self.open_service()
        self.submit()
        self.service.on_book(book(1))
        self.assertEqual(encode_account(self.service.snapshot()), before)
        self.service.on_book(book(2))
        self.assertEqual(self.service.snapshot().orders[0].held, 400)

    def test_expiry_releases_only_unfilled_cash_and_keeps_filled_position(self):
        self.submit()
        self.service.on_book(book(1))
        self.service.advance("expiry", NOW + timedelta(minutes=5))
        account = self.service.snapshot()
        self.assertEqual(account.reserved_cash, 0)
        self.assertEqual(account.orders[0].held, 200)
        self.assertEqual(account.orders[0].status, "HOLDING")
        self.service.on_book(book(301))
        self.assertEqual(self.service.snapshot().orders[0].held, 200)

    def test_unfilled_plan_expires_and_cannot_fill_after_recovery(self):
        self.submit()
        self.service.on_book(book(300))
        account = self.service.snapshot()
        self.assertEqual(account.orders[0].status, "ENTRY_EXPIRED")
        self.assertEqual(account.reserved_cash, 0)
        self.assertFalse(account.fills)

    def test_stop_exit_waits_for_next_book_and_uses_gap_price(self):
        self.submit()
        self.service.on_book(book(1))
        self.service.on_book(book(2))
        self.service.on_book(book(3, bid=D("9.4"), ask=D("9.5")))
        account = self.service.snapshot()
        self.assertEqual(len(account.fills), 2)
        self.assertEqual(account.orders[0].status, "EXIT_PENDING")
        self.assertEqual(account.reserved_cash, 0)
        self.service = self.open_service()
        self.service.on_book(book(4, bid=D("8.5"), ask=D("8.6")))
        self.service.on_book(book(5, bid=D("8.4"), ask=D("8.5")))
        account = self.service.snapshot()
        self.assertEqual(account.orders[0].status, "CLOSED")
        self.assertEqual(account.orders[0].held, 0)
        self.assertEqual(account.cash, D("99372.62"))
        self.assertEqual([f.price for f in account.fills[2:]], [D("8.5"), D("8.4")])

    def test_take_profit_does_not_fill_at_hindsight_high(self):
        self.submit()
        self.service.on_book(book(1))
        self.service.on_book(book(2, bid=D("11.1"), ask=D("11.2")))
        self.assertEqual(len(self.service.snapshot().fills), 1)
        self.service.on_book(book(3, bid=D("10.5"), ask=D("10.6")))
        account = self.service.snapshot()
        self.assertEqual(account.orders[0].exit_reason, "TAKE_PROFIT")
        self.assertEqual(account.fills[-1].price, D("10.5"))

    def test_deadline_retries_after_closed_market_instead_of_losing_exit(self):
        self.submit()
        self.service.on_book(book(1))
        self.service.advance("deadline", NOW + timedelta(hours=1))
        self.service.on_book(book(3601, market_open=False))
        self.assertEqual(self.service.snapshot().orders[0].status, "EXIT_PENDING")
        self.service = self.open_service()
        self.service.on_book(book(3602))
        self.assertEqual(self.service.snapshot().orders[0].status, "CLOSED")

    def test_invalid_stale_and_future_books_cannot_fill(self):
        self.submit()
        self.service.on_book(book(1, quality_good=False))
        self.service.on_book(book(2, received_at=NOW + timedelta(seconds=10)))
        self.service.on_book(book(20, received_at=NOW + timedelta(seconds=11)))
        self.assertFalse(self.service.snapshot().fills)

    def test_out_of_order_command_rolls_back_atomically(self):
        self.submit()
        self.service.on_book(book(5))
        before = encode_account(self.service.snapshot())
        with self.assertRaises(ValueError):
            self.service.on_book(book(4))
        self.assertEqual(encode_account(self.service.snapshot()), before)

    def test_cancel_entry_does_not_erase_partial_fills(self):
        result = self.submit()
        self.service.on_book(book(1))
        self.service.cancel_entry("cancel", result["plan_id"], NOW + timedelta(seconds=2))
        self.assertEqual(self.service.snapshot().orders[0].held, 200)
        self.assertEqual(self.service.snapshot().reserved_cash, 0)

    def test_existing_stock_and_stale_marks_block_new_allocations(self):
        self.submit()
        result = self.submit(setup(setup_id="second"), event="other")
        self.assertEqual(result["reason"], "STOCK_ALREADY_ALLOCATED")
        self.service.on_book(book(1))
        result = self.submit(setup(setup_id="new", stock_code="HK.03690", source_event_id="new"), event="new",
                             when=NOW + timedelta(seconds=10))
        self.assertEqual(result["reason"], "ACCOUNT_MARK_STALE")

    def test_concurrent_plans_see_reserved_budget_and_position_slots(self):
        def submit_one(index):
            service = self.open_service()
            item = setup(setup_id=f"setup-{index}", stock_code=f"HK.{index:05d}", source_event_id=f"source-{index}")
            return json.loads(service.submit(f"request-{index}", item, NOW))["reason"]
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(submit_one, range(1, 7)))
        self.assertEqual(results.count("PAPER_PLAN_APPROVED"), 3)
        self.assertEqual(results.count("MAX_POSITIONS_REACHED"), 3)
        account = self.service.snapshot()
        self.assertEqual(account.reserved_cash, D("30030"))
        self.assertLessEqual(account.reserved_cash, account.cash)

    def test_portfolio_risk_cap_includes_unfilled_orders(self):
        policy = replace(POLICY, portfolio_risk_fraction=D("0.01"))
        account = PaperAccount(account_id="paper:risk", policy=policy, cash=policy.initial_cash)
        first = PaperEngine.submit(account, setup(), NOW)
        second = PaperEngine.submit(account, setup(setup_id="second", stock_code="HK.03690", source_event_id="second"), NOW)
        self.assertLess(second.plan.quantity, first.plan.quantity)
        self.assertLessEqual(sum(order.risk(policy) for order in account.orders), D("1000"))

    def test_restart_refuses_policy_change_and_foreign_database(self):
        with self.assertRaises(ValueError):
            self.open_service(replace(POLICY, initial_cash=D("200000")))
        foreign = Path(self.temp.name) / "foreign.db"
        with closing(sqlite3.connect(foreign)) as connection, connection:
            connection.execute("CREATE TABLE production_data (value INTEGER)")
        with self.assertRaises(ValueError):
            SqlitePaperAccountStore(foreign, "paper:test", POLICY)
        with closing(sqlite3.connect(foreign)) as connection:
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        self.assertEqual(tables, [("production_data",)])

    def test_decimal_account_round_trip_is_lossless(self):
        self.submit()
        self.service.on_book(book(1))
        encoded = encode_account(self.service.snapshot())
        self.assertEqual(encode_account(decode_account(encoded)), encoded)

    def test_failed_write_operation_rolls_back_fills_and_command_id(self):
        self.submit()
        before = encode_account(self.service.snapshot())
        with patch.object(PaperEngine, "assert_invariants", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                self.service.on_book(book(1))
        self.assertEqual(encode_account(self.service.snapshot()), before)
        self.service.on_book(book(1))
        self.assertEqual(len(self.service.snapshot().fills), 1)

    def test_closed_source_event_cannot_open_a_new_setup(self):
        result = self.submit()
        self.service.cancel_entry("cancel", result["plan_id"], NOW)
        repeat = self.submit(setup(setup_id="renamed-setup"), event="new-command")
        self.assertEqual(repeat["reason"], "SOURCE_EVENT_ALREADY_PLANNED")

    def test_corrupted_cash_cannot_resume_as_a_healthy_account(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            raw = connection.execute("SELECT state_json FROM paper_account").fetchone()[0]
            payload = json.loads(raw)
            payload["account"]["cash"] = "999999"
            connection.execute("UPDATE paper_account SET state_json=?", (json.dumps(payload),))
        with self.assertRaisesRegex(ValueError, "reconcile"):
            self.open_service()


if __name__ == "__main__":
    unittest.main()
