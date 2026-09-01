"""Audit same-day multi-source buy confirmations that V2 did not retain."""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Any


HK = timezone(timedelta(hours=8))
CONFIRM_WINDOW_SECONDS = 15 * 60
COOLDOWN_SECONDS = 30 * 60
OUTCOME_WINDOW_SECONDS = 60 * 60


@dataclass(frozen=True, slots=True)
class SignalEvent:
    time: str
    epoch: float
    code: str
    name: str
    source: str
    strength: float
    action: str
    reason: str


def parse_local(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=HK) if parsed.tzinfo is None else parsed


def load_events(conn: sqlite3.Connection, trade_date: str) -> list[SignalEvent]:
    rows = conn.execute(
        "SELECT timestamp, stock_code, stock_name, source, direction, strength, "
        "final_action, final_reason, raw_detail FROM signal_pipeline "
        "WHERE trade_date=? ORDER BY timestamp",
        (trade_date,),
    )
    events: list[SignalEvent] = []
    for timestamp, code, name, source, direction, strength, action, reason, raw_text in rows:
        try:
            raw = json.loads(raw_text or "{}")
        except json.JSONDecodeError:
            raw = {}
        normalized_source = str(source or "")
        normalized_direction = str(direction or "").upper()
        if normalized_source == "capital_trend":
            if str(raw.get("inflow_stage") or "") not in {"FIRST", "CONFIRMED", "STRENGTHENED"}:
                continue
            source_class = "capital"
        elif normalized_source == "absorption_scanner" and normalized_direction == "BUY":
            source_class = "absorption"
        elif normalized_source in {"sniper", "anomaly"} and normalized_direction == "BUY":
            source_class = normalized_source
        else:
            continue
        moment = parse_local(timestamp)
        events.append(
            SignalEvent(
                time=str(timestamp),
                epoch=moment.timestamp(),
                code=str(code),
                name=str(name or ""),
                source=source_class,
                strength=float(strength or 0.0),
                action=str(action or ""),
                reason=str(reason or raw.get("reason") or ""),
            )
        )
    return events


def load_tape(
    conn: sqlite3.Connection, trade_date: str
) -> tuple[dict[str, tuple[list[float], list[float]]], dict[str, float]]:
    tapes: dict[str, tuple[list[float], list[float]]] = {}
    timestamps: dict[str, list[float]] = defaultdict(list)
    prices: dict[str, list[float]] = defaultdict(list)
    turnover: dict[str, float] = defaultdict(float)
    for code, timestamp, price, amount in conn.execute(
        "SELECT stock_code, timestamp, price, turnover FROM ticker_data "
        "WHERE trade_date=? AND price>0 ORDER BY stock_code, timestamp, id",
        (trade_date,),
    ):
        timestamps[str(code)].append(float(timestamp) / 1000.0)
        prices[str(code)].append(float(price))
        turnover[str(code)] += float(amount or 0.0)
    for code in timestamps:
        tapes[code] = (timestamps[code], prices[code])
    return tapes, dict(turnover)


def tape_outcome(
    tape: tuple[list[float], list[float]], event_epoch: float
) -> dict[str, float | bool | None]:
    timestamps, prices = tape
    start = bisect_left(timestamps, event_epoch)
    end = bisect_right(timestamps, event_epoch + OUTCOME_WINDOW_SECONDS)
    if start >= len(timestamps) or start >= end:
        return {}
    entry = prices[start]
    future = prices[start:end]
    target = entry * 1.015
    target_offset = next((index for index, price in enumerate(future) if price >= target), None)
    target_index = start + target_offset if target_offset is not None else None
    pre_target_end = target_index + 1 if target_index is not None else end
    pre_target_low = min(prices[start:pre_target_end])
    return {
        "entry_price": entry,
        "mfe_60m_pct": round((max(future) / entry - 1.0) * 100.0, 3),
        "target_1_5": target_index is not None,
        "time_to_1_5_min": (
            round((timestamps[target_index] - timestamps[start]) / 60.0, 1)
            if target_index is not None
            else None
        ),
        "pre_target_mae_pct": round((pre_target_low / entry - 1.0) * 100.0, 3),
        "last_return_pct": round((prices[-1] / entry - 1.0) * 100.0, 3),
    }


def load_candidate_context(
    conn: sqlite3.Connection, trade_date: str
) -> tuple[float | None, dict[str, list[dict[str, Any]]]]:
    first_received = conn.execute(
        "SELECT MIN(received_time) FROM v2_decision_events WHERE substr(received_time,1,10)=?",
        (trade_date,),
    ).fetchone()[0]
    start_epoch = datetime.fromisoformat(first_received).timestamp() if first_received else None
    timelines: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for code, event_type, exchange_time, reason in conn.execute(
        "SELECT stock_code,event_type,exchange_time,reason_code FROM v2_decision_events "
        "WHERE substr(exchange_time,1,10)=? AND event_type LIKE 'CANDIDATE_%' "
        "ORDER BY exchange_time,id",
        (trade_date,),
    ):
        timelines[str(code)].append(
            {
                "event_type": event_type,
                "time": exchange_time,
                "epoch": datetime.fromisoformat(str(exchange_time)).timestamp(),
                "reason": reason,
            }
        )
    return start_epoch, dict(timelines)


def candidate_status_at(
    code: str,
    epoch: float,
    v2_start: float | None,
    timelines: dict[str, list[dict[str, Any]]],
) -> tuple[str, str | None]:
    if v2_start is None or epoch < v2_start:
        return "V2_NOT_RUNNING", None
    latest = None
    for item in timelines.get(code, []):
        if item["epoch"] <= epoch:
            latest = item
    if latest is None:
        return "NOT_ENTERED", None
    if latest["event_type"] == "CANDIDATE_ENTERED":
        return "IN_POOL", latest["reason"]
    return "INVALIDATED", latest["reason"]


def active_codes(conn: sqlite3.Connection, trade_date: str) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT stock_code FROM daily_active_stocks WHERE check_date=? AND is_active=1",
            (trade_date,),
        )
    }


def build_clusters(events: list[SignalEvent]) -> list[dict[str, Any]]:
    by_code: dict[str, list[SignalEvent]] = defaultdict(list)
    for event in events:
        by_code[event.code].append(event)
    clusters: list[dict[str, Any]] = []
    for code, code_events in by_code.items():
        recent: deque[SignalEvent] = deque()
        last_emitted = 0.0
        for event in code_events:
            while recent and event.epoch - recent[0].epoch > CONFIRM_WINDOW_SECONDS:
                recent.popleft()
            previous_sources = {item.source for item in recent}
            recent.append(event)
            sources = {item.source for item in recent}
            if len(sources) < 2 or len(previous_sources) >= 2:
                continue
            if event.epoch - last_emitted < COOLDOWN_SECONDS:
                continue
            last_emitted = event.epoch
            clusters.append(
                {
                    "code": code,
                    "name": event.name,
                    "confirmation_time": event.time,
                    "confirmation_epoch": event.epoch,
                    "sources": sorted(sources),
                    "signals": [
                        {
                            "time": item.time,
                            "source": item.source,
                            "strength": item.strength,
                            "action": item.action,
                            "reason": item.reason,
                        }
                        for item in recent
                    ],
                }
            )
    return clusters


def build_absorption_anchors(events: list[SignalEvent]) -> list[SignalEvent]:
    anchors: list[SignalEvent] = []
    last_by_code: dict[str, float] = {}
    for event in events:
        if event.source != "absorption":
            continue
        if event.epoch - last_by_code.get(event.code, 0.0) < COOLDOWN_SECONDS:
            continue
        anchors.append(event)
        last_by_code[event.code] = event.epoch
    return anchors


def audit(
    conn: sqlite3.Connection, trade_date: str, focus_code: str | None = None
) -> dict[str, Any]:
    events = load_events(conn, trade_date)
    if focus_code:
        events = [event for event in events if event.code == focus_code.strip().upper()]
    tapes, turnover = load_tape(conn, trade_date)
    active = active_codes(conn, trade_date)
    v2_start, timelines = load_candidate_context(conn, trade_date)
    rows: list[dict[str, Any]] = []
    for cluster in build_clusters(events):
        tape = tapes.get(cluster["code"])
        if tape is None:
            continue
        outcome = tape_outcome(tape, cluster["confirmation_epoch"])
        if not outcome:
            continue
        candidate_status, candidate_reason = candidate_status_at(
            cluster["code"], cluster["confirmation_epoch"], v2_start, timelines
        )
        amount = turnover.get(cluster["code"], 0.0)
        row = {
            **cluster,
            **outcome,
            "turnover": round(amount, 2),
            "daily_active": cluster["code"] in active,
            "candidate_status": candidate_status,
            "candidate_reason": candidate_reason,
            "candidate_timeline": timelines.get(cluster["code"], []),
        }
        row["qualified"] = bool(
            row["target_1_5"]
            and (row["time_to_1_5_min"] or 999.0) <= 60.0
            and (row["pre_target_mae_pct"] or -999.0) >= -1.5
            and (row["daily_active"] or amount >= 50_000_000.0)
        )
        rows.append(row)
    qualified = sorted(
        (row for row in rows if row["qualified"]),
        key=lambda row: (row["mfe_60m_pct"], -row["time_to_1_5_min"]),
        reverse=True,
    )
    single_source: list[dict[str, Any]] = []
    single_source_debug: list[dict[str, Any]] = []
    clustered_codes = {row["code"] for row in qualified}
    for event in build_absorption_anchors(events):
        if event.code in clustered_codes:
            continue
        tape = tapes.get(event.code)
        if tape is None:
            continue
        outcome = tape_outcome(tape, event.epoch)
        if not outcome:
            continue
        amount = turnover.get(event.code, 0.0)
        meets_single_rule = bool(
            outcome.get("target_1_5")
            and (outcome.get("time_to_1_5_min") or 999.0) <= 30.0
            and (outcome.get("mfe_60m_pct") or 0.0) >= 2.0
            and (outcome.get("pre_target_mae_pct") or -999.0) >= -1.0
            and (event.code in active or amount >= 50_000_000.0)
        )
        candidate_status, candidate_reason = candidate_status_at(
            event.code, event.epoch, v2_start, timelines
        )
        item = {
            **asdict(event),
            **outcome,
            "turnover": round(amount, 2),
            "daily_active": event.code in active,
            "candidate_status": candidate_status,
            "candidate_reason": candidate_reason,
            "candidate_timeline": timelines.get(event.code, []),
            "meets_single_rule": meets_single_rule,
        }
        if focus_code:
            single_source_debug.append(item)
        if meets_single_rule:
            single_source.append(item)
    single_source.sort(key=lambda row: row["mfe_60m_pct"], reverse=True)
    return {
        "trade_date": trade_date,
        "generated_at": datetime.now(HK).isoformat(),
        "v2_started_at": (
            datetime.fromtimestamp(v2_start, HK).isoformat() if v2_start is not None else None
        ),
        "source_event_count": len(events),
        "multi_source_cluster_count": len(rows),
        "qualified_count": len(qualified),
        "qualified": qualified,
        "single_source_watch_count": len(single_source),
        "single_source_watch": single_source,
        "single_source_debug": single_source_debug,
        "all_clusters": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--date", default=datetime.now(HK).date().isoformat())
    parser.add_argument("--code")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db, uri=True, timeout=10)
    conn.execute("PRAGMA query_only=ON")
    print(json.dumps(audit(conn, args.date, args.code), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
