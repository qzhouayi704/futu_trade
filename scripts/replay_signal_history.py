#!/usr/bin/env python3
"""Audit real signal history; minute stress simulation requires explicit assumptions."""

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path

# Reuse the isolated package bootstrap; never start FastAPI or load broker credentials.
from paper_trade_replay import ROOT
from simple_trade.v2.domain.planning.codec import encode
from simple_trade.v2.domain.planning.models import PaperPolicy
from paper_history.data import readiness, select, validate
from paper_history.coverage import coverage
from paper_history.stress import StressAssumptions, study


LIMITATIONS = [
    "Recorded BUY_CONFIRMED events, not a rerun of the new strategy rules; no selection by future gain.",
    "Minutes are recorded-trade averages/ranges, not closing prices or historical quotes.",
    "Strict execution replay requires point-in-time lots, executable plans and order-book evidence.",
    "Stress scenarios use assumed fixed board lots and exits, not historical system trade plans.",
    "Synthetic stress ask=minute high plus slippage, bid=minute low minus slippage; not executable quotes.",
    "Only full minutes after an action can be consumed; stop/target/deadline fills wait for a later full minute.",
    "Bar availability at end+1s, continuous sessions 09:30-12:00/13:00-16:00 and exit at 15:50 are assumptions.",
    "Minute volume participation cannot establish queue liquidity; no guaranteed conservative bound on profit.",
    "Fee rate and minimum per side are scenarios, not actual broker/account tariffs; tick-size rounding omitted.",
    "Missing minutes are not filled forward; pending exits and stale open marks remain visible.",
    "Each cohort is a separate account; eligible overlaps delivered and must not be added to it.",
    "Same-stock same-day confirmations keep only the first per cohort; no claim of independent samples or optimal parameters.",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-minute-stress", action="store_true")
    parser.add_argument("--cohort", choices=("delivered", "eligible", "shadow", "all"), default="all")
    parser.add_argument("--assumed-lot-size", type=int)
    parser.add_argument("--initial-cash", type=Decimal)
    parser.add_argument("--fee-rate", type=Decimal)
    parser.add_argument("--minimum-fee", type=Decimal)
    parser.add_argument("--slippage-bps", type=Decimal)
    args = parser.parse_args()
    if args.output and args.input.resolve() == args.output.resolve():
        parser.error("report must not overwrite the source export")
    required = (args.assumed_lot_size, args.initial_cash, args.fee_rate, args.minimum_fee, args.slippage_bps)
    if not args.allow_minute_stress and any(value is not None for value in required):
        parser.error("simulation assumptions require --allow-minute-stress")
    raw = args.input.read_bytes()
    payload = json.loads(raw.decode("utf-8-sig"))
    decisions, minutes = validate(payload)
    cohorts = ("delivered", "eligible", "shadow") if args.cohort == "all" else (args.cohort,)
    result = {
        "mode": "HISTORY_READINESS_ONLY", "report_version": "history-research-v2",
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "data_origin": payload["data_origin"], "exported_at": payload["exported_at"],
        "start": payload["start"], "end_exclusive": payload["end_exclusive"],
        "archives": payload["archives"], "raw_decisions": len(decisions), "minute_rows": len(minutes),
        "limitations": LIMITATIONS, "cohorts": {},
    }
    if args.allow_minute_stress:
        if any(value is None for value in required):
            parser.error("stress mode requires explicit lot size, cash, fee rate, minimum fee and slippage bps")
        policy = PaperPolicy(initial_cash=args.initial_cash, fee_rate=args.fee_rate, minimum_fee=args.minimum_fee,
                             max_book_age_seconds=120)
        assumptions = StressAssumptions(assumed_lot_size=args.assumed_lot_size,
                                        slippage_fraction=args.slippage_bps / 10000)
        result["mode"] = "MINUTE_RANGE_STRESS_NOT_EXECUTION_BACKTEST"
        for cohort in cohorts:
            result["cohorts"][cohort] = study(payload, cohort, policy, assumptions)
    else:
        for cohort in cohorts:
            selected, excluded = select(decisions, cohort)
            result["cohorts"][cohort] = {"exclusions": excluded, **readiness(selected, minutes),
                                         "post_signal_archive_coverage": coverage(selected, minutes)}
    report = encode(result)
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(report + "\n")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
