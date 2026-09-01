#!/usr/bin/env python3
"""Read-only intraday audit for V2 candidate coverage and missed entries."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


HK = timezone(timedelta(hours=8))
TABLES = (
    "stocks",
    "ticker_data",
    "ticker_minute",
    "capital_flow_minute",
    "tick_capital_flow",
    "market_baselines",
    "daily_active_stocks",
    "kline_data",
    "signal_pipeline",
    "v2_decision_events",
    "v2_strategy_states",
)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]


def coverage(conn: sqlite3.Connection, table: str, trade_date: str) -> dict:
    names = columns(conn, table)
    date_column = next(
        (name for name in ("trade_date", "check_date") if name in names), None
    )
    time_column = next(
        (
            name
            for name in ("exchange_time", "timestamp", "time", "time_key", "minute")
            if name in names
        ),
        None,
    )
    result = {"columns": names}
    if date_column is not None:
        row = conn.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT stock_code) FROM {table} "
            f"WHERE {date_column}=?",
            (trade_date,),
        ).fetchone()
        result.update({"today_rows": int(row[0]), "today_stocks": int(row[1])})
        latest = conn.execute(f"SELECT MAX({date_column}) FROM {table}").fetchone()[0]
        result["latest_date"] = latest
    elif time_column is not None:
        row = conn.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT stock_code) FROM {table} "
            f"WHERE substr({time_column},1,10)=?",
            (trade_date,),
        ).fetchone()
        result.update({"today_rows": int(row[0]), "today_stocks": int(row[1])})
        latest = conn.execute(f"SELECT MAX({time_column}) FROM {table}").fetchone()[0]
        result["latest_time"] = latest
    else:
        result["rows"] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return result


def load_candidate_states(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        "SELECT s.stock_code, s.status, s.updated_at, e.reason_code "
        "FROM v2_strategy_states s LEFT JOIN v2_decision_events e "
        "ON e.event_id=s.last_event_id"
    )
    return {
        str(row[0]): {
            "status": row[1],
            "updated_at": row[2],
            "reason_code": row[3],
        }
        for row in rows
    }


def load_candidate_timelines(
    conn: sqlite3.Connection, trade_date: str
) -> dict[str, list[dict[str, Any]]]:
    timelines: dict[str, list[dict[str, Any]]] = {}
    rows = conn.execute(
        "SELECT stock_code, event_type, exchange_time, reason_code FROM v2_decision_events "
        "WHERE substr(exchange_time,1,10)=? AND event_type IN "
        "('CANDIDATE_ENTERED','CANDIDATE_UPDATED','BUY_CONFIRMED',"
        "'CANDIDATE_INVALIDATED','BUY_INVALIDATED') ORDER BY exchange_time",
        (trade_date,),
    )
    for code, event_type, exchange_time, reason_code in rows:
        timelines.setdefault(str(code), []).append(
            {
                "event_type": event_type,
                "time": exchange_time,
                "reason_code": reason_code,
            }
        )
    return timelines


def outcome_after(
    conn: sqlite3.Connection,
    trade_date: str,
    stock_code: str,
    event_ts: float,
    entry_price: float,
) -> dict[str, Any]:
    if entry_price <= 0:
        return {}
    start_ms = int(event_ts * 1000)
    row = conn.execute(
        "SELECT MAX(price), MIN(price), MAX(timestamp) FROM ticker_data "
        "WHERE trade_date=? AND stock_code=? AND timestamp>=? AND price>0",
        (trade_date, stock_code, start_ms),
    ).fetchone()
    if row is None or row[0] is None:
        return {}
    last_row = conn.execute(
        "SELECT price, timestamp FROM ticker_data WHERE trade_date=? AND stock_code=? "
        "AND timestamp>=? AND price>0 ORDER BY timestamp DESC, id DESC LIMIT 1",
        (trade_date, stock_code, start_ms),
    ).fetchone()
    target_row = conn.execute(
        "SELECT timestamp FROM ticker_data WHERE trade_date=? AND stock_code=? "
        "AND timestamp>=? AND price>=? ORDER BY timestamp LIMIT 1",
        (trade_date, stock_code, start_ms, entry_price * 1.015),
    ).fetchone()
    max_price, min_price = float(row[0]), float(row[1])
    last_price = float(last_row[0]) if last_row else None
    return {
        "mfe_pct": round((max_price / entry_price - 1.0) * 100.0, 3),
        "mae_pct": round((min_price / entry_price - 1.0) * 100.0, 3),
        "last_return_pct": (
            round((last_price / entry_price - 1.0) * 100.0, 3)
            if last_price is not None
            else None
        ),
        "max_price": max_price,
        "last_price": last_price,
        "reached_1_5": target_row is not None,
        "time_to_1_5_minutes": (
            round((float(target_row[0]) / 1000.0 - event_ts) / 60.0, 1)
            if target_row is not None
            else None
        ),
    }


def load_flow_events(
    conn: sqlite3.Connection,
    trade_date: str,
    v2_started_ts: float | None,
    states: dict[str, dict[str, Any]],
    timelines: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT timestamp, stock_code, stock_name, raw_detail FROM signal_pipeline "
        "WHERE trade_date=? AND source='capital_trend' ORDER BY timestamp",
        (trade_date,),
    )
    tracked_stages = {
        "FIRST",
        "SECOND_WATCH",
        "CONFIRMED",
        "STRENGTHENED",
        "REJECTED",
        "INVALIDATED",
        "EXPIRED",
        "WATCH_TRAIL_EXIT",
        "TRAIL_EXIT",
    }
    for timestamp, code, name, raw_text in rows:
        try:
            raw = json.loads(raw_text or "{}")
        except json.JSONDecodeError:
            continue
        stage = str(raw.get("inflow_stage") or "")
        if not raw.get("is_large_inflow") and stage not in tracked_stages:
            continue
        event_ts = float(raw.get("timestamp") or 0.0)
        entry_price = float(raw.get("last_price") or 0.0)
        outcome = outcome_after(conn, trade_date, str(code), event_ts, entry_price)
        state = states.get(str(code))
        if v2_started_ts is not None and event_ts < v2_started_ts:
            v2_reason = "V2_NOT_RUNNING"
        elif state is not None:
            v2_reason = str(state.get("reason_code") or state.get("status") or "IN_CANDIDATES")
        else:
            v2_reason = str(raw.get("inflow_gate_reason") or "NOT_IN_V2_UNIVERSE")
        events.append(
            {
                "time": timestamp,
                "event_ts": event_ts,
                "code": code,
                "name": name,
                "stage": stage,
                "entry_price": entry_price,
                "risk_mode": raw.get("inflow_risk_mode"),
                "sequence_no": raw.get("inflow_sequence_no"),
                "window_net": raw.get("window_main_net"),
                "window_buy_ratio": raw.get("window_buy_ratio"),
                "market_breadth": raw.get("market_breadth"),
                "turnover_rank": raw.get("turnover_rank_percentile"),
                "plate_name": raw.get("plate_name"),
                "plate_breadth": raw.get("plate_breadth"),
                "relative_strength": raw.get("relative_strength_pct"),
                "gate_reason": raw.get("inflow_gate_reason"),
                "is_hot_candidate": raw.get("is_hot_candidate"),
                "v2_state": state,
                "v2_timeline": timelines.get(str(code), []),
                "v2_reason": v2_reason,
                **outcome,
            }
        )
    return events


def top_movers(conn: sqlite3.Connection, trade_date: str, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "WITH latest_tick AS ("
        "SELECT stock_code, price, timestamp, ROW_NUMBER() OVER "
        "(PARTITION BY stock_code ORDER BY timestamp DESC, id DESC) rn "
        "FROM ticker_data WHERE trade_date=? AND price>0), "
        "day_stats AS (SELECT stock_code, MIN(price) low, MAX(price) high, "
        "SUM(turnover) turnover FROM ticker_data WHERE trade_date=? AND price>0 "
        "GROUP BY stock_code), prev AS ("
        "SELECT stock_code, close_price, ROW_NUMBER() OVER "
        "(PARTITION BY stock_code ORDER BY time_key DESC) rn FROM kline_data "
        "WHERE substr(time_key,1,10)<?) "
        "SELECT l.stock_code, COALESCE(s.name,''), l.price, p.close_price, "
        "d.low, d.high, d.turnover FROM latest_tick l JOIN day_stats d "
        "ON d.stock_code=l.stock_code LEFT JOIN prev p ON p.stock_code=l.stock_code "
        "AND p.rn=1 LEFT JOIN stocks s ON s.code=l.stock_code "
        "WHERE l.rn=1 AND p.close_price>0 ORDER BY l.price/p.close_price DESC LIMIT ?",
        (trade_date, trade_date, trade_date, limit),
    )
    return [
        {
            "code": row[0],
            "name": row[1],
            "last_price": float(row[2]),
            "prev_close": float(row[3]),
            "change_pct": round((float(row[2]) / float(row[3]) - 1.0) * 100.0, 3),
            "low": float(row[4]),
            "high": float(row[5]),
            "intraday_range_pct": round((float(row[5]) / float(row[4]) - 1.0) * 100.0, 3),
            "ticker_turnover": round(float(row[6]), 2),
        }
        for row in rows
    ]


def universe_references(
    conn: sqlite3.Connection, trade_date: str, codes: set[str]
) -> dict[str, dict[str, Any]]:
    references: dict[str, dict[str, Any]] = {}
    for code in sorted(codes):
        active = conn.execute(
            "SELECT is_active, activity_score, turnover_rate, turnover_amount, created_at "
            "FROM daily_active_stocks WHERE check_date=? AND stock_code=?",
            (trade_date, code),
        ).fetchone()
        bars = conn.execute(
            "SELECT COUNT(*), MIN(time_key), MAX(time_key) FROM kline_data WHERE stock_code=?",
            (code,),
        ).fetchone()
        stock = conn.execute(
            "SELECT is_manual, stock_priority, heat_score, activity_score, "
            "liquidity_score, liquidity_level FROM stocks WHERE code=?",
            (code,),
        ).fetchone()
        references[code] = {
            "daily_active": (
                {
                    "is_active": bool(active[0]),
                    "activity_score": active[1],
                    "turnover_rate": active[2],
                    "turnover_amount": active[3],
                    "created_at": active[4],
                }
                if active
                else None
            ),
            "daily_bars": {
                "count": bars[0], "first": bars[1], "last": bars[2]
            },
            "stock_profile": (
                {
                    "is_manual": bool(stock[0]),
                    "priority": stock[1],
                    "heat_score": stock[2],
                    "activity_score": stock[3],
                    "liquidity_score": stock[4],
                    "liquidity_level": stock[5],
                }
                if stock
                else None
            ),
        }
    return references


def signal_source_summary(conn: sqlite3.Connection, trade_date: str) -> dict[str, Any]:
    grouped = conn.execute(
        "SELECT source, direction, final_action, guard_result, COUNT(*) "
        "FROM signal_pipeline WHERE trade_date=? "
        "GROUP BY source, direction, final_action, guard_result "
        "ORDER BY source, direction, final_action, guard_result",
        (trade_date,),
    ).fetchall()
    rows = conn.execute(
        "SELECT timestamp, stock_code, stock_name, source, direction, strength, "
        "resonance_result, guard_result, final_action, final_reason, raw_detail "
        "FROM signal_pipeline WHERE trade_date=? ORDER BY timestamp",
        (trade_date,),
    ).fetchall()
    interesting: list[dict[str, Any]] = []
    for row in rows:
        direction = str(row[4] or "").upper()
        action = str(row[8] or "").upper()
        if not any(token in direction or token in action for token in ("BUY", "INFLOW", "LONG")):
            continue
        try:
            raw = json.loads(row[10] or "{}")
        except json.JSONDecodeError:
            raw = {}
        interesting.append(
            {
                "time": row[0], "code": row[1], "name": row[2], "source": row[3],
                "direction": row[4], "strength": row[5], "resonance": row[6],
                "guard": row[7], "action": row[8], "reason": row[9],
                "raw_keys": sorted(raw)[:80],
                "raw": raw,
            }
        )
    return {
        "grouped": [
            {
                "source": row[0], "direction": row[1], "action": row[2],
                "guard": row[3], "count": row[4],
            }
            for row in grouped
        ],
        "interesting": interesting,
    }


def audit(conn: sqlite3.Connection, trade_date: str) -> dict[str, Any]:
    states = load_candidate_states(conn)
    timelines = load_candidate_timelines(conn, trade_date)
    first_v2 = conn.execute(
        "SELECT MIN(received_time) FROM v2_decision_events "
        "WHERE substr(received_time,1,10)=?",
        (trade_date,),
    ).fetchone()[0]
    v2_started_ts = datetime.fromisoformat(first_v2).timestamp() if first_v2 else None
    events = load_flow_events(
        conn, trade_date, v2_started_ts, states, timelines
    )
    entries = [row for row in events if row["stage"] in {"FIRST", "CONFIRMED", "STRENGTHENED"}]
    opportunities = [row for row in entries if row.get("reached_1_5")]
    movers = top_movers(conn, trade_date)
    relevant_codes = {row["code"] for row in entries} | {
        row["code"] for row in movers[:10]
    }
    return {
        "trade_date": trade_date,
        "generated_at": datetime.now(HK).isoformat(),
        "v2_started_at": first_v2,
        "coverage": {
            table: coverage(conn, table, trade_date)
            for table in ("ticker_data", "tick_capital_flow", "signal_pipeline", "v2_decision_events")
        },
        "candidate_states": states,
        "candidate_timelines": timelines,
        "entry_event_count": len(entries),
        "opportunity_count": len(opportunities),
        "opportunities": opportunities,
        "all_entries": entries,
        "top_movers": movers,
        "universe_references": universe_references(conn, trade_date, relevant_codes),
    }


def compact_audit(result: dict[str, Any], limit: int) -> dict[str, Any]:
    entries = result["all_entries"]
    opportunities = result["opportunities"]
    v2_started_at = result.get("v2_started_at")

    v2_started_ts = datetime.fromisoformat(v2_started_at).timestamp() if v2_started_at else None

    def after_v2(row: dict[str, Any]) -> bool:
        return bool(v2_started_ts and float(row.get("event_ts") or 0.0) >= v2_started_ts)

    def unique_codes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected: dict[str, dict[str, Any]] = {}
        for row in sorted(rows, key=lambda item: item.get("event_ts", 0.0)):
            selected.setdefault(row["code"], row)
        return sorted(
            selected.values(),
            key=lambda item: (item.get("mfe_pct") or -999),
            reverse=True,
        )[:limit]

    def slim(row: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "code", "name", "time", "stage", "entry_price", "mfe_pct",
            "mae_pct", "last_return_pct", "time_to_1_5_minutes", "v2_state",
            "v2_reason", "gate_reason", "market_breadth", "plate_name",
            "plate_breadth", "relative_strength", "turnover_rank", "sequence_no",
            "window_net", "window_buy_ratio", "risk_mode",
        )
        return {field: row.get(field) for field in fields}

    mover_rows = []
    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in entries:
        by_code.setdefault(row["code"], []).append(row)
    for mover in result["top_movers"]:
        flow_rows = sorted(by_code.get(mover["code"], []), key=lambda row: row["event_ts"])
        state = result["candidate_states"].get(mover["code"], {})
        mover_rows.append(
            {
                **mover,
                "flow_stages": [row["stage"] for row in flow_rows],
                "first_flow_time": flow_rows[0]["time"] if flow_rows else None,
                "flow_mfe_pct": max((row.get("mfe_pct") or -999 for row in flow_rows), default=None),
                "candidate_state": state.get("status"),
                "candidate_reason": state.get("reason_code"),
            }
        )

    confirmed = [row for row in entries if row["stage"] in {"CONFIRMED", "STRENGTHENED"}]
    confirmed_opportunities = [row for row in confirmed if row.get("reached_1_5")]
    first_only_opportunities = [row for row in opportunities if row["stage"] == "FIRST"]
    post_v2 = [row for row in entries if after_v2(row)]
    post_v2_opportunities = [row for row in opportunities if after_v2(row)]
    return {
        "trade_date": result["trade_date"],
        "generated_at": result["generated_at"],
        "v2_started_at": v2_started_at,
        "coverage": result["coverage"],
        "entry_event_count": len(entries),
        "entry_stage_counts": dict(Counter(row["stage"] for row in entries)),
        "opportunity_event_count": len(opportunities),
        "opportunity_code_count": len({row["code"] for row in opportunities}),
        "post_v2_entry_stage_counts": dict(Counter(row["stage"] for row in post_v2)),
        "post_v2_opportunity_code_count": len({row["code"] for row in post_v2_opportunities}),
        "all_entries": [slim(row) for row in sorted(entries, key=lambda item: item["event_ts"])],
        "confirmed_entries": [slim(row) for row in unique_codes(confirmed)],
        "confirmed_opportunities": [slim(row) for row in unique_codes(confirmed_opportunities)],
        "first_opportunities": [slim(row) for row in unique_codes(first_only_opportunities)],
        "post_v2_opportunities": [slim(row) for row in unique_codes(post_v2_opportunities)],
        "candidate_states": result["candidate_states"],
        "candidate_timelines": result["candidate_timelines"],
        "universe_references": result["universe_references"],
        "top_movers": mover_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--date", default=datetime.now(HK).date().isoformat())
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--signal-summary", action="store_true")
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, uri=True, timeout=10)
    conn.execute("PRAGMA query_only=ON")
    if args.signal_summary:
        print(json.dumps(signal_source_summary(conn, args.date), ensure_ascii=False, indent=2, default=str))
        return
    if args.inspect:
        output = {
            table: coverage(conn, table, args.date)
            for table in TABLES
            if table_exists(conn, table)
        }
        if table_exists(conn, "ticker_data"):
            output["ticker_samples"] = [
                dict(zip(("code", "price", "turnover", "direction", "timestamp", "sequence"), row))
                for row in conn.execute(
                    "SELECT stock_code, price, turnover, direction, timestamp, sequence "
                    "FROM ticker_data WHERE trade_date=? ORDER BY id DESC LIMIT 8",
                    (args.date,),
                )
            ]
        if table_exists(conn, "v2_decision_events"):
            output["v2_event_summary"] = [
                {"event_type": row[0], "reason_code": row[1], "count": row[2]}
                for row in conn.execute(
                    "SELECT event_type, reason_code, COUNT(*) FROM v2_decision_events "
                    "WHERE substr(exchange_time,1,10)=? GROUP BY event_type, reason_code "
                    "ORDER BY event_type, reason_code",
                    (args.date,),
                )
            ]
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        return
    result = audit(conn, args.date)
    if args.compact:
        result = compact_audit(result, args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
