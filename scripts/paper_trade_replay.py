#!/usr/bin/env python3
"""Replay explicit plans and best-book observations into an isolated paper ledger."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Match the standalone test runner: do not import the FastAPI app or broker services.
for name, path in (("simple_trade", ROOT / "simple_trade"),
                   ("simple_trade.utils", ROOT / "simple_trade" / "utils")):
    if name not in sys.modules:
        package = ModuleType(name)
        package.__path__ = [str(path)]
        package.__package__ = name
        sys.modules[name] = package

from simple_trade.v2.application.planning.paper_service import PaperTradingService
from simple_trade.v2.domain.planning.codec import (
    book_from_payload, encode, policy_from_payload, setup_from_payload,
)
from simple_trade.v2.infrastructure.paper.sqlite_account_store import SqlitePaperAccountStore


def replay(source: Path, ledger: Path) -> dict:
    if source.resolve() == ledger.resolve():
        raise ValueError("input and paper ledger must be different files")
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported replay schema")
    store = SqlitePaperAccountStore(
        ledger, payload["account_id"], policy_from_payload(payload["policy"]),
    )
    service = PaperTradingService(store)
    results = []
    for command in payload["events"]:
        kind = command["kind"]
        if kind == "plan":
            result = service.submit(command["event_id"], setup_from_payload(command["setup"]),
                                    datetime.fromisoformat(command["when"]))
        elif kind == "book":
            result = service.on_book(book_from_payload(command["book"]))
        elif kind == "clock":
            result = service.advance(command["event_id"], datetime.fromisoformat(command["when"]))
        elif kind == "cancel_entry":
            result = service.cancel_entry(command["event_id"], command["plan_id"],
                                          datetime.fromisoformat(command["when"]))
        else:
            raise ValueError(f"unsupported paper command: {kind}")
        results.append(json.loads(result))
    account = service.snapshot()
    return {
        "mode": "OFFLINE_PAPER_ONLY",
        "data_origin": payload.get("data_origin", "USER_SUPPLIED_UNVERIFIED"),
        "execution_model": "causal_best_book_with_participation_cap_not_exchange_matching",
        "account_id": account.account_id, "as_of": account.as_of,
        "initial_cash": account.policy.initial_cash, "cash": account.cash,
        "reserved_cash": account.reserved_cash, "equity": account.equity,
        "net_pnl": account.equity - account.policy.initial_cash,
        "fees": sum((fill.fee for fill in account.fills), start=account.cash * 0),
        "plan_count": len(account.orders), "fill_count": len(account.fills),
        "open_positions": sum(order.held > 0 for order in account.orders),
        "orders": [{"plan": order.plan, "status": order.status, "held": order.held,
                    "entry_remaining": order.entry_remaining,
                    "entry_end_reason": order.entry_end_reason, "exit_reason": order.exit_reason}
                   for order in account.orders],
        "fills": account.fills, "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    print(encode(replay(args.input, args.ledger)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
