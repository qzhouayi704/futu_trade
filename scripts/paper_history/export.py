"""Bounded read-only export. Can run over SSH stdin without importing the app."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import time


def export_history(conn: sqlite3.Connection, start: str, end: str) -> dict:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if not 0 < (last - first).days <= 31:
        raise ValueError("export requires an exclusive end and a range of 1..31 days")
    conn.execute("PRAGMA query_only=ON")
    if conn.in_transaction:
        raise ValueError("export requires its own read transaction")
    began = time.monotonic()
    conn.set_progress_handler(lambda: time.monotonic() - began > 60, 10000)
    conn.execute("BEGIN")
    try:
        rows = conn.execute(
            "SELECT e.event_id,e.stock_code,e.exchange_time,e.received_time,"
            "e.strategy_version,e.reason_code,e.payload_json,i.risk_result,"
            "EXISTS(SELECT 1 FROM v2_notification_log n WHERE n.decision_event_id=e.event_id "
            "AND n.channel='WECHAT' AND n.status='DELIVERED') "
            "FROM v2_decision_events e LEFT JOIN v2_trade_intents i "
            "ON i.source_event_id=e.event_id AND i.intent_type='BUY' "
            "WHERE e.event_type='BUY_CONFIRMED' AND e.exchange_time>=? "
            "AND e.exchange_time<? ORDER BY e.exchange_time,e.id LIMIT 4001",
            (start, end),
        ).fetchall()
        if len(rows) > 4000:
            raise ValueError("too many decisions; narrow the date range")
        names = dict(conn.execute("SELECT code,name FROM stocks WHERE market='HK'"))
        decisions = []
        for event_id, code, exchange, received, version, reason, raw, risk, sent in rows:
            payload = json.loads(raw)
            feature = payload.get("feature_snapshot") or {}
            quote = feature.get("quote") or {}
            decisions.append({
                "event_id": event_id, "stock_code": code, "name": names.get(code) or "",
                "exchange_time": exchange, "received_time": received,
                "strategy_version": version, "reason": reason,
                "alert_eligible": payload.get("alert_eligible") is True,
                "risk_result": risk, "delivered": bool(sent),
                "quote": quote, "liquidity": feature.get("liquidity") or {},
                "strategy_sources": (payload.get("strategy_portfolio") or {}).get("strategy_sources", []),
                "entry_plan": payload.get("entry_plan"),
            })
        # Export only signalled securities, but retain every day in the window for exits.
        minutes = []
        for code in sorted({row["stock_code"] for row in decisions}):
            minutes.extend([code, *row] for row in conn.execute(
                "SELECT trade_date,minute,price,high,low,volume FROM ticker_minute "
                "WHERE stock_code=? AND trade_date>=? AND trade_date<? "
                "ORDER BY trade_date,minute", (code, start, end),
            ))
            if len(minutes) > 500000:
                raise ValueError("too many minute rows; narrow the export window")
        archives = [list(row) for row in conn.execute(
            "SELECT trade_date,updated_at FROM ticker_minute_archive_meta "
            "WHERE trade_date>=? AND trade_date<? ORDER BY trade_date", (start, end),
        )]
        return {
            "schema_version": 1, "data_origin": "PRODUCTION_DB_READ_ONLY_EXPORT",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "start": start, "end_exclusive": end,
            "minute_price_semantics": "ARITHMETIC_MEAN_OF_RECORDED_TRADES_NOT_CLOSE_OR_QUOTE",
            "minute_columns": ["stock_code", "trade_date", "minute", "mean", "high", "low", "volume"],
            "historical_order_books_in_export": False,
            "archives": archives, "decisions": decisions, "minutes": minutes,
        }
    finally:
        conn.rollback()
        conn.set_progress_handler(None, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True, help="exclusive date")
    args = parser.parse_args()
    uri = Path(args.db).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        print(json.dumps(export_history(conn, args.start, args.end), ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
