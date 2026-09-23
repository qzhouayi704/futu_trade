"""Validation, cohort selection and execution readiness for archived decisions."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import re

from simple_trade.v2.domain.planning.models import hk_stock_code, integer, positive
from simple_trade.v2.domain.serialization import require_aware


HK = timezone(timedelta(hours=8))
SEMANTICS = "ARITHMETIC_MEAN_OF_RECORDED_TRADES_NOT_CLOSE_OR_QUOTE"


def moment(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    require_aware(result, "history timestamp")
    return result.astimezone(HK)


def regular(when: datetime) -> bool:
    clock = when.astimezone(HK).strftime("%H:%M:%S")
    return "09:30:00" <= clock < "12:00:00" or "13:00:00" <= clock < "16:00:00"


def ordinary_equity(code: str, name: str) -> bool:
    # A documented name/code heuristic, not an authoritative point-in-time security master.
    return int(code[3:]) < 10000 and not re.search(
        r"ETF|GLOBAL\s*X|\u4e24\u500d|\u4e09\u500d|\u53cd\u5411|\u76c8\u5bcc\u57fa\u91d1|\u5b89\u7855|\u5357\u65b9\u6052|\u6052\u751f\u6307\u6570|\u534e\u590f\u6052\u751f",
        name, re.I,
    )


@dataclass(frozen=True)
class Minute:
    stock_code: str
    start: datetime
    mean: Decimal
    high: Decimal
    low: Decimal
    volume: int

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=1)


def validate(payload: dict) -> tuple[list[dict], list[Minute]]:
    if payload.get("schema_version") != 1 or payload.get("minute_price_semantics") != SEMANTICS:
        raise ValueError("unsupported history schema or ambiguous minute price semantics")
    if payload.get("historical_order_books_in_export") is not False:
        raise ValueError("this archive adapter supports minute data only, not historical books")
    first, end = date.fromisoformat(payload["start"]), date.fromisoformat(payload["end_exclusive"])
    if not 0 < (end - first).days <= 31:
        raise ValueError("history requires a bounded date range of 1..31 days")
    exported = moment(payload["exported_at"])
    ids: set[str] = set()
    for decision in payload["decisions"]:
        event_id = decision["event_id"]
        if not event_id or event_id in ids:
            raise ValueError("duplicate or empty decision identity")
        ids.add(event_id)
        hk_stock_code(decision["stock_code"])
        exchange, received = moment(decision["exchange_time"]), moment(decision["received_time"])
        if received < exchange:
            raise ValueError("decision received before its exchange timestamp")
        if received > exported:
            raise ValueError("decision is later than the export snapshot")
        if not payload["start"] <= exchange.date().isoformat() < payload["end_exclusive"]:
            raise ValueError("decision outside exported date range")
        for flag in ("alert_eligible", "delivered"):
            if type(decision[flag]) is not bool:
                raise ValueError("history flags must be boolean")
    seen = set()
    minutes = []
    for code, day, clock, mean, high, low, volume in payload["minutes"]:
        hk_stock_code(code)
        start = datetime.fromisoformat(f"{day}T{clock}:00+08:00")
        if start + timedelta(minutes=1) > exported:
            raise ValueError("minute was incomplete at the export snapshot")
        if not payload["start"] <= day < payload["end_exclusive"]:
            raise ValueError("minute outside exported date range")
        key = (code, start)
        if key in seen:
            raise ValueError("duplicate minute would double-count execution capacity")
        seen.add(key)
        prices = [Decimal(str(value)) for value in (mean, high, low)]
        for price in prices:
            positive(price, "minute price")
        # SQLite AVG of repeated REAL values may drift just beyond a constant range.
        tolerance = max(prices[1], Decimal(1)) * Decimal("1e-12")
        if prices[2] > prices[1] or not prices[2] - tolerance <= prices[0] <= prices[1] + tolerance:
            raise ValueError("invalid minute price range")
        amount = Decimal(str(volume))
        positive(amount, "volume", allow_zero=True)
        if amount != int(amount):
            raise ValueError("minute volume must be an integer share count")
        minutes.append(Minute(code, start, *prices, int(amount)))
    return payload["decisions"], sorted(minutes, key=lambda row: (row.end, row.stock_code))


def select(decisions: list[dict], cohort: str) -> tuple[list[dict], dict]:
    if cohort not in {"delivered", "eligible", "shadow"}:
        raise ValueError("unsupported research cohort")
    selected, seen, exclusions = [], set(), Counter()
    for row in sorted(decisions, key=lambda item: (moment(item["received_time"]), item["event_id"])):
        eligible = row["alert_eligible"]
        matched = (row["delivered"] and eligible and row["risk_result"] == "APPROVED"
                   if cohort == "delivered" else eligible if cohort == "eligible" else not eligible)
        if not matched:
            continue
        when = moment(row["received_time"])
        if not ordinary_equity(row["stock_code"], row["name"]):
            exclusions["NON_ORDINARY_EQUITY_HEURISTIC"] += 1
        elif not regular(when):
            exclusions["OUTSIDE_CONTINUOUS_SESSION"] += 1
        elif (when.date(), row["stock_code"]) in seen:
            exclusions["SAME_STOCK_DAY_REPEAT"] += 1
        else:
            selected.append(row)
            seen.add((when.date(), row["stock_code"]))
    return selected, dict(exclusions)


def readiness(decisions: list[dict], minutes: list[Minute]) -> dict:
    counts = Counter()
    cases = []
    by_code: dict[str, list[Minute]] = {}
    for row in minutes:
        by_code.setdefault(row.stock_code, []).append(row)
    for row in decisions:
        # An archive with no order books cannot establish an executable fill.
        reasons = ["HISTORICAL_ORDER_BOOK_MISSING", "RECEIPT_TIME_FOR_MINUTE_ARCHIVE_UNKNOWN"]
        if not row.get("entry_plan"):
            reasons.append("EXECUTABLE_ENTRY_PLAN_MISSING")
        lot = row["quote"].get("lot_size")
        try:
            integer(lot, "lot_size")
        except ValueError:
            reasons.append("POINT_IN_TIME_LOT_SIZE_MISSING")
        when = moment(row["received_time"])
        if not any(bar.start >= when and bar.start.date() == when.date() and regular(bar.start)
                   for bar in by_code.get(row["stock_code"], [])):
            reasons.append("NO_FULL_LATER_REGULAR_MINUTE")
        counts.update(reasons)
        cases.append({"event_id": row["event_id"], "stock_code": row["stock_code"],
                      "when": when.isoformat(), "blocking_reasons": reasons})
    return {"decisions": len(decisions), "strictly_replayable": 0,
            "blocker_counts": dict(counts), "cases": cases}
