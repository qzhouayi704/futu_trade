"""Read-only bounded inspection; stale marks are never labelled final returns."""

from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import time

from ...domain.planning.codec import decode_account
from ...domain.planning.ledger import LedgerFill, LedgerOrder, LedgerSignal, PaperLedgerSnapshot
from ...domain.planning.models import PaperExitPolicy
from .sqlite_account_store import SqlitePaperAccountStore


def read_session_report(path: Path, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
        deadline = time.monotonic() + 5
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        if conn.execute("PRAGMA application_id").fetchone()[0] != SqlitePaperAccountStore.APPLICATION_ID:
            raise ValueError("not a paper ledger")
        run = conn.execute("SELECT CASE WHEN length(configuration)<=262144 THEN configuration END, "
                           "run_id, started_at, ended_at, error FROM paper_session_run").fetchone()
        row = conn.execute("SELECT CASE WHEN length(state_json)<=4194304 THEN state_json END "
                           "FROM paper_account").fetchone()
        if run is None or row is None:
            raise ValueError("paper session not initialized")
        if run[0] is None or row[0] is None:
            raise ValueError("paper report JSON exceeds read budget")
        account = decode_account(row[0])
        columns = "event_id, CASE WHEN length(result_json)<=262144 THEN result_json END"
        recent = conn.execute(f"SELECT {columns} FROM paper_commands ORDER BY rowid DESC LIMIT 50").fetchall()
        # The primary-key range excludes high-frequency book commands before sorting.
        signals = conn.execute(f"SELECT {columns} FROM paper_commands WHERE event_id>=? AND event_id<? "
                               "ORDER BY rowid DESC LIMIT 50", ("paper-signal:", "paper-signal;")).fetchall()
        if any(raw is None for _, raw in (*recent, *signals)):
            raise ValueError("paper command JSON exceeds read budget")
    stale = tuple(order.plan.setup.stock_code for order in account.orders if order.held and (
        order.plan.setup.stock_code not in account.book_times
        or not 0 <= (now - account.book_times[order.plan.setup.stock_code]).total_seconds()
        <= account.policy.max_book_age_seconds
    ))
    realized = sum((order.sell_notional - order.buy_notional - order.buy_fee - order.sell_fee
                    for order in account.orders if order.bought and not order.held), Decimal("0"))
    configuration = json.loads(run[0])
    stale_analysis = tuple(order.plan.setup.stock_code for order in account.orders
                           if order.held and not order.exit_reason
                           and order.plan.setup.exit_policy is PaperExitPolicy.PRODUCTION_RULES
                           and (order.position_state is None or not 0 <= (
                               now - order.position_state.updated_at).total_seconds()
                               <= configuration["experiment"]["maximum_signal_age_seconds"]))
    return {
        "mode": "LOCAL_PAPER_EXPERIMENT_ONLY", "execution_model": "sampled_server_time_approximation",
        "reported_at": now, "account_id": account.account_id, "as_of": account.as_of,
        "run_id": run[1], "started_at": run[2], "ended_at": run[3], "error": run[4],
        "run_record_status": "CLOSED" if run[3] else "OPEN_OR_UNCLEAN",
        "configuration": configuration, "cash": account.cash, "reserved_cash": account.reserved_cash,
        "marked_equity": account.equity, "stale_position_codes": stale,
        "stale_analysis_codes": stale_analysis,
        "closed_order_net_pnl": realized,
        "fees": sum((fill.fee for fill in account.fills), Decimal("0")),
        "orders": [{"plan": order.plan, "status": order.status, "held": order.held,
                    "entry_remaining": order.entry_remaining, "bought": order.bought, "sold": order.sold,
                    "entry_end_reason": order.entry_end_reason, "exit_reason": order.exit_reason,
                    "average_buy_price": order.buy_notional / order.bought if order.bought else None,
                    "position_reason": order.position_state.metadata.get("last_reason") if order.position_state else None,
                    "position_evaluated_at": order.position_state.updated_at if order.position_state else None,
                    "exit_triggered_at": order.exit_triggered_at,
                    "closed_net_pnl": (order.sell_notional - order.buy_notional - order.buy_fee - order.sell_fee
                                       if order.bought and not order.held else None)}
                   for order in account.orders],
        "fill_count": len(account.fills), "recent_fills": account.fills[-50:],
        "recent_results": [{"event_id": key, **json.loads(result)} for key, result in recent],
        "recent_signals": [{"event_id": key, **json.loads(result)} for key, result in signals],
    }


def read_ledger_snapshot(path: Path, *, now: datetime | None = None) -> PaperLedgerSnapshot:
    report = read_session_report(path, now=now)
    experiment = report["configuration"]["experiment"]
    codes = {item["plan"].plan_id: item["plan"].setup.stock_code for item in report["orders"]}
    orders = []
    visible = sorted(report["orders"], key=lambda item: (
        bool(item["held"] or item["entry_remaining"]), item["plan"].approved_at,
    ), reverse=True)[:100]
    for item in visible:
        plan, setup = item["plan"], item["plan"].setup
        orders.append(LedgerOrder(
            plan.plan_id, setup.stock_code, plan.approved_at, item["status"], plan.quantity,
            item["bought"], item["sold"], item["held"], item["entry_remaining"],
            str(setup.entry_min), str(setup.entry_limit), str(setup.stop_price), setup.valid_until,
            setup.exit_at, item["entry_end_reason"], item["exit_reason"],
            str(item["closed_net_pnl"]) if item["closed_net_pnl"] is not None else None,
            average_buy_price=str(item["average_buy_price"]) if item["average_buy_price"] is not None else None,
            position_reason=item["position_reason"], position_evaluated_at=item["position_evaluated_at"],
            exit_triggered_at=item["exit_triggered_at"],
        ))
    return PaperLedgerSnapshot(
        reported_at=report["reported_at"], as_of=report["as_of"], account_id=report["account_id"],
        experiment_id=experiment["experiment_id"], strategy_id=experiment["strategy_id"],
        strategy_version=experiment["strategy_version"], stock_codes=tuple(experiment["stock_codes"]),
        run_record_status=report["run_record_status"],
        run_error_code=report["error"].split(":", 1)[0] if report["error"] else None,
        cash=str(report["cash"]), reserved_cash=str(report["reserved_cash"]),
        marked_equity=str(report["marked_equity"]), closed_order_net_pnl=str(report["closed_order_net_pnl"]),
        closed_order_count=sum(item["closed_net_pnl"] is not None for item in report["orders"]),
        fees=str(report["fees"]), stale_position_codes=report["stale_position_codes"],
        order_count=len(report["orders"]), orders=tuple(orders), fill_count=report["fill_count"],
        recent_fills=tuple(LedgerFill(
            fill.fill_id, codes[fill.plan_id], fill.side, fill.quantity, str(fill.price), str(fill.fee),
            fill.exchange_time,
        ) for fill in reversed(report["recent_fills"])),
        recent_signals=tuple(LedgerSignal(
            item["event_id"], item["input"]["stock_code"], item["processed_at"], item["result"]["reason"],
        ) for item in report["recent_signals"]),
        exit_policy=experiment.get("exit_policy", "RESEARCH_ATR"),
        stale_analysis_codes=report["stale_analysis_codes"],
    )
