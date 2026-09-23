from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from scripts.paper_history.data import moment, readiness, select, validate
from scripts.paper_history.export import export_history
from scripts.paper_history.coverage import coverage
from scripts.paper_history.stress import StressAssumptions, study
from simple_trade.v2.domain.planning.models import PaperPolicy


ROOT = Path(__file__).resolve().parents[2]
D = Decimal
POLICY = PaperPolicy(initial_cash=D("100000"), fee_rate=D("0.001"), minimum_fee=D("3"),
                     max_book_age_seconds=120)
ASSUMPTIONS = StressAssumptions(assumed_lot_size=100, slippage_fraction=D("0"))


def decision(event="event-1", code="HK.00100", when="10:00:30", **updates):
    timestamp = f"2026-09-21T{when}+08:00"
    return {
        "event_id": event, "stock_code": code, "name": "TEST STOCK",
        "exchange_time": timestamp, "received_time": timestamp,
        "strategy_version": "historical-v1", "reason": "TEST_ONLY",
        "alert_eligible": True, "delivered": True, "risk_result": "APPROVED",
        "quote": {"last_price": 10, "lot_size": None}, "entry_plan": None, **updates,
    }


def minute(clock, mean=10, high=10, low=10, volume=100000, code="HK.00100", day="2026-09-21"):
    return [code, day, clock, mean, high, low, volume]


def payload(decisions=None, minutes=None):
    return {
        "schema_version": 1, "data_origin": "SYNTHETIC_TEST_NOT_MARKET_DATA",
        "exported_at": "2026-09-21T18:00:00+08:00", "archives": [["2026-09-21", "test"]],
        "start": "2026-09-21", "end_exclusive": "2026-09-22",
        "minute_price_semantics": "ARITHMETIC_MEAN_OF_RECORDED_TRADES_NOT_CLOSE_OR_QUOTE",
        "historical_order_books_in_export": False,
        "decisions": decisions if decisions is not None else [decision()],
        "minutes": minutes if minutes is not None else [minute("10:01"), minute("15:51")],
    }


class HistoryValidationTests(unittest.TestCase):
    def test_selection_is_received_time_ordered_first_stock_day_not_later_best_price(self):
        first = decision("first", when="10:00:30")
        later = decision("later", when="10:10:00", quote={"last_price": 1})
        rows, excluded = select([later, first], "delivered")
        self.assertEqual([row["event_id"] for row in rows], ["first"])
        self.assertEqual(excluded["SAME_STOCK_DAY_REPEAT"], 1)

    def test_delivery_requires_eligible_and_risk_approved(self):
        rows = [decision("shadow", alert_eligible=False), decision("risk", risk_result="REJECTED"),
                decision("eligible", delivered=False)]
        self.assertEqual(select(rows, "delivered")[0], [])
        self.assertEqual(select(rows, "shadow")[0][0]["event_id"], "shadow")
        self.assertEqual(len(select(rows, "eligible")[0]), 1)

    def test_no_future_returns_used_to_filter_equities(self):
        rows = [decision("ordinary"), decision("etf", "HK.07226", name="TEST ETF"),
                decision("lunch", "HK.00002", when="12:30:00")]
        selected, counts = select(rows, "eligible")
        self.assertEqual(len(selected), 1)
        self.assertEqual(counts["OUTSIDE_CONTINUOUS_SESSION"], 1)
        self.assertEqual(counts["NON_ORDINARY_EQUITY_HEURISTIC"], 1)

    def test_readiness_never_promotes_minute_archive_to_executable_book(self):
        decisions, minutes = validate(payload())
        result = readiness(decisions, minutes)
        self.assertEqual(result["strictly_replayable"], 0)
        self.assertEqual(result["blocker_counts"]["POINT_IN_TIME_LOT_SIZE_MISSING"], 1)
        self.assertNotIn("NO_FULL_LATER_REGULAR_MINUTE", result["blocker_counts"])

    def test_globalx_short_name_without_etf_is_not_a_stock(self):
        rows = [decision("fund", "HK.02837", name="GlobalX Hang Seng TECH"),
                decision("stock", "HK.03200", name="TEST STOCK")]
        selected, excluded = select(rows, "delivered")
        self.assertEqual([row["stock_code"] for row in selected], ["HK.03200"])
        self.assertEqual(excluded["NON_ORDINARY_EQUITY_HEURISTIC"], 1)

    def test_coverage_counts_only_complete_regular_minutes_and_does_not_filter(self):
        source = payload([decision(when="11:59:30")], [minute("11:59"), minute("12:00"), minute("13:00"), minute("15:59")])
        decisions, bars = validate(source)
        result = coverage(decisions, bars)
        self.assertEqual(result["cases"][0]["expected_regular_minutes"], 180)
        self.assertEqual(result["cases"][0]["observed_regular_minutes"], 2)
        self.assertEqual(result["cases"][0]["longest_missing_trading_minutes"], 178)
        self.assertEqual(result["cases"][0]["minutes_in_assumed_exit_window"], 1)
        self.assertEqual(len(select(decisions, "delivered")[0]), 1)

    def test_naive_future_and_duplicate_data_rejected(self):
        changes = [
            {"decisions": [decision(), decision()]},
            {"minutes": [minute("10:01"), minute("10:01")]},
            {"minutes": [minute("10:01", low=11)]},
            {"minutes": [minute("10:01", volume=1.5)]},
            {"minutes": [minute("10:01", mean=float("nan"))]},
            {"decisions": [decision(received_time="2026-09-21T09:59:00+08:00")]},
            {"decisions": [decision(exchange_time="2026-09-21T10:00:30")]},
            {"decisions": [decision(delivered="true")]},
            {"minute_price_semantics": "close"},
            {"exported_at": "2026-09-21T10:00:35+08:00"},
            {"exported_at": "2026-09-21T10:00:29+08:00"},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate({**payload(), **change})

    def test_sqlite_average_roundoff_does_not_change_execution_range(self):
        _, bars = validate(payload(minutes=[minute("10:01", mean=10.100000000000001, high=10.1, low=10.1)]))
        self.assertEqual(bars[0].high, D("10.1"))
        self.assertEqual(bars[0].low, D("10.1"))


class MinuteStressTests(unittest.TestCase):
    def run_study(self, source=None, policy=POLICY, assumptions=ASSUMPTIONS):
        return study(source or payload(), "delivered", policy, assumptions)

    def test_signal_minute_cannot_fill_even_if_its_high_looks_profitable(self):
        result = self.run_study(payload(minutes=[minute("10:00", mean=11, high=12),
                                                minute("10:01"), minute("15:51")]))
        self.assertEqual(result["fills"][0].exchange_time, moment("2026-09-21T10:02:00+08:00"))
        self.assertEqual(result["fills"][0].price, D("10"))

    def test_end_of_day_exit_uses_later_complete_minute_and_accounts_for_fees(self):
        result = self.run_study(payload(minutes=[minute("10:01"), minute("15:49", 11, 11, 11),
                                                minute("15:50", 10.5, 10.5, 10.5)]))
        fills = result["fills"]
        self.assertEqual([fill.side for fill in fills], ["BUY", "SELL"])
        self.assertEqual(fills[-1].price, D("10.5"))
        self.assertEqual(fills[-1].exchange_time.hour, 15)
        self.assertEqual(fills[-1].exchange_time.minute, 51)
        self.assertTrue(result["all_positions_closed"])
        self.assertEqual(result["closed_trades"], 1)
        self.assertEqual(result["marked_net_pnl_not_fully_realized"],
                         sum((f.quantity * f.price * (1 if f.side == "SELL" else -1) - f.fee for f in fills)))

    def test_stop_and_high_in_same_minute_never_sells_at_peak_or_ideal_stop(self):
        result = self.run_study(payload(minutes=[minute("10:01"),
            minute("10:02", 10, 12, 9.5), minute("10:03", 9.4, 9.4, 9.4),
            minute("10:04", 9, 9, 9)]))
        self.assertEqual(result["trades"][0]["exit_reason"], "STOP_BROKEN")
        self.assertEqual(result["fills"][-1].price, D("9"))
        self.assertLess(result["portfolio_return_pct"], 0)

    def test_missing_end_quotes_leave_pending_exit_and_suppress_stale_return(self):
        result = self.run_study(payload(minutes=[minute("10:01")]))
        self.assertFalse(result["all_positions_closed"])
        self.assertIsNone(result["portfolio_return_pct"])
        self.assertEqual(result["closed_trades"], 0)
        self.assertEqual(result["trades"][0]["status"], "EXIT_PENDING")
        self.assertEqual(len(result["stale_open_marks"]), 1)

    def test_limit_above_entry_range_is_unfilled_not_reference_price_buy(self):
        result = self.run_study(payload(minutes=[minute("10:01", 11, 11, 11)]))
        self.assertEqual(result["fills"], [])
        self.assertEqual(result["unfilled_plans"][0]["status"], "ENTRY_EXPIRED")

    def test_volume_capacity_partial_entry_and_pending_exit(self):
        result = self.run_study(payload(minutes=[minute("10:01", volume=1000), minute("15:50", volume=0)]))
        self.assertEqual(result["trades"][0]["bought"], 100)
        self.assertEqual(result["trades"][0]["sold"], 0)

    def test_assumed_lot_and_budget_can_prevent_allocation(self):
        result = self.run_study(assumptions=replace(ASSUMPTIONS, assumed_lot_size=100000))
        self.assertEqual(result["assessment_counts"], {"BELOW_ONE_LOT_BUDGET": 1})

    def test_new_candidate_does_not_free_unexited_position_budget(self):
        rows = [decision(), decision("second", "HK.00002", when="10:02:30")]
        result = self.run_study(payload(rows, [minute("10:01"), minute("10:03", code="HK.00002")]),
                                policy=replace(POLICY, max_positions=1))
        self.assertEqual(result["assessment_counts"]["MAX_POSITIONS_REACHED"], 1)

    def test_stale_holding_that_blocks_later_signal_is_identified(self):
        source = payload([decision(), decision("second", "HK.00002", when="10:05:30")],
                         [minute("10:01"), minute("10:06", code="HK.00002")])
        result = self.run_study(source)
        blocked = [row for row in result["assessments"] if row["reason"] == "ACCOUNT_MARK_STALE"]
        self.assertEqual(blocked[0]["stale_holdings"][0]["stock_code"], "HK.00100")
        self.assertTrue(result["allocation_affected_by_stale_marks"])
        self.assertTrue(result["daily"][0]["stale_open_marks"])

    def test_repeat_run_is_deterministic_and_does_not_mutate_source(self):
        source = payload()
        original = deepcopy(source)
        self.assertEqual(self.run_study(source), self.run_study(source))
        self.assertEqual(source, original)

    def test_invalid_assumptions_are_rejected(self):
        for updates in ({"assumed_lot_size": 0}, {"slippage_fraction": D("NaN")},
                        {"stop_fraction": D("0.001")}, {"entry_valid_minutes": 0}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                replace(ASSUMPTIONS, **updates)


class HistoryExportTests(unittest.TestCase):
    def test_export_is_read_only_and_includes_only_signalled_stock_minutes(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript("""
            CREATE TABLE v2_decision_events(id INTEGER PRIMARY KEY,event_id TEXT,stock_code TEXT,
                exchange_time TEXT,received_time TEXT,strategy_version TEXT,reason_code TEXT,payload_json TEXT,event_type TEXT);
            CREATE TABLE v2_trade_intents(source_event_id TEXT,intent_type TEXT,risk_result TEXT);
            CREATE TABLE v2_notification_log(decision_event_id TEXT,channel TEXT,status TEXT);
            CREATE TABLE stocks(code TEXT,name TEXT,market TEXT);
            CREATE TABLE ticker_minute(stock_code TEXT,trade_date TEXT,minute TEXT,price REAL,high REAL,low REAL,volume INTEGER);
            CREATE TABLE ticker_minute_archive_meta(trade_date TEXT,updated_at TEXT);
        """)
        row = decision()
        conn.execute("INSERT INTO v2_decision_events VALUES(1,?,?,?,?,?,?,?,'BUY_CONFIRMED')", (
            row["event_id"], row["stock_code"], row["exchange_time"], row["received_time"],
            row["strategy_version"], row["reason"], json.dumps({"alert_eligible": True,
                "feature_snapshot": {"quote": row["quote"]}})))
        conn.execute("INSERT INTO stocks VALUES('HK.00100','TEST','HK')")
        for code in ("HK.00100", "HK.09999"):
            conn.execute("INSERT INTO ticker_minute VALUES(?,?,?,?,?,?,?)", minute("10:01", code=code))
        conn.commit()
        result = export_history(conn, "2026-09-21", "2026-09-22")
        self.assertEqual(len(result["minutes"]), 1)
        self.assertEqual(len(result["decisions"]), 1)
        self.assertFalse(conn.in_transaction)
        self.assertEqual(conn.execute("PRAGMA query_only").fetchone()[0], 1)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM stocks")
        with self.assertRaises(ValueError):
            export_history(conn, "2026-01-01", "2026-09-22")


class HistoryCliTests(unittest.TestCase):
    def test_readiness_default_and_explicit_stress_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "input.json"
            source.write_text(json.dumps(payload()), encoding="utf-8")
            base = [sys.executable, str(ROOT / "scripts/replay_signal_history.py"), "--input", str(source)]
            audit = subprocess.run(base, capture_output=True, text=True, check=True, timeout=30)
            result = json.loads(audit.stdout)
            self.assertEqual(result["mode"], "HISTORY_READINESS_ONLY")
            self.assertEqual(result["cohorts"]["delivered"]["strictly_replayable"], 0)
            missing = subprocess.run(base + ["--allow-minute-stress"], capture_output=True, text=True, timeout=30)
            self.assertNotEqual(missing.returncode, 0)
            unacknowledged = subprocess.run(base + ["--fee-rate", "0.001"], capture_output=True, text=True, timeout=30)
            self.assertNotEqual(unacknowledged.returncode, 0)
            full = subprocess.run(base + ["--allow-minute-stress", "--assumed-lot-size", "100",
                "--initial-cash", "100000", "--fee-rate", "0.001", "--minimum-fee", "3", "--slippage-bps", "5"],
                capture_output=True, text=True, check=True, timeout=30)
            self.assertEqual(json.loads(full.stdout)["mode"], "MINUTE_RANGE_STRESS_NOT_EXECUTION_BACKTEST")
            self.assertEqual(audit.stderr + full.stderr, "")

    def test_cli_never_overwrites_input_or_existing_report(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "input.json"
            raw = json.dumps(payload())
            source.write_text(raw, encoding="utf-8")
            command = [sys.executable, str(ROOT / "scripts/replay_signal_history.py"), "--input", str(source),
                       "--output", str(source)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(source.read_text(encoding="utf-8"), raw)
