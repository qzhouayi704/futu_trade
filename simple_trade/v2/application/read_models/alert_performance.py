"""Delivered-alert performance across later trading sessions."""

import asyncio
from collections import defaultdict
from datetime import date

from .alert_performance_metrics import (
    evaluate_alert,
    performance_summary,
)
from .alert_performance_records import (
    collapse_candidates,
    collapse_delivered,
    eligible_delivered,
)

VALID_SCOPES = {"candidates", "watching", "confirmed", "alerts"}


class AlertPerformanceReader:
    def __init__(self, db) -> None:
        self._db = db

    async def history(
        self,
        *,
        trade_date: str | None = None,
        scope: str = "candidates",
    ) -> dict:
        selected_date = self._validated_date(trade_date)
        if scope not in VALID_SCOPES:
            raise ValueError(
                "复盘范围必须是 candidates、watching、confirmed 或 alerts"
            )
        exclusions = {"total": 0, "by_reason": {}}
        if scope == "alerts":
            alerts, exclusions = await self._delivered_alerts(selected_date)
        else:
            alerts = await self._candidate_alerts(selected_date, scope=scope)
        if not alerts:
            return self._empty(selected_date, scope, exclusions=exclusions)

        codes = sorted({item["stock_code"] for item in alerts})
        names, klines, intraday, intraday_closes = await asyncio.gather(
            self._names(codes),
            self._klines(codes, selected_date),
            self._intraday(codes, selected_date),
            self._intraday_closes(codes, selected_date),
        )
        items = [
            evaluate_alert(item, names, klines, intraday, intraday_closes)
            for item in alerts
        ]
        summary_by_version = {
            version: performance_summary([
                item for item in items if item["strategy_version"] == version
            ])
            for version in sorted({item["strategy_version"] for item in items})
        }
        return {
            "trade_date": selected_date,
            "scope": scope,
            "items": items,
            "count": len(items),
            "available_kline_through": max(
                (day for stock_days in klines.values() for day in stock_days),
                default=None,
            ),
            "intraday_coverage_count": sum(
                bool(item["same_day"]["intraday_covered"]) for item in items
            ),
            "excluded": exclusions,
            "summary": performance_summary(items),
            "summary_by_strategy_version": summary_by_version,
        }

    async def _delivered_alerts(self, selected_date: str) -> tuple[list[dict], dict]:
        rows = await self._query(
            "SELECT e.event_id, e.event_type, e.stock_code, e.exchange_time, "
            "e.reason_code, e.strategy_version, i.intent_type, i.risk_result, "
            "i.buy_leg_json, i.sell_leg_json, n.delivered_at, "
            "o.mfe_pct, o.mae_pct, o.close_return_pct "
            "FROM v2_notification_log n "
            "JOIN v2_decision_events e ON e.event_id=n.decision_event_id "
            "JOIN v2_trade_intents i ON i.source_event_id=e.event_id "
            "LEFT JOIN v2_outcomes o ON o.decision_event_id=e.event_id "
            "WHERE n.channel='WECHAT' AND n.status='DELIVERED' "
            "AND substr(e.exchange_time,1,10)=? "
            "ORDER BY e.exchange_time, e.id",
            (selected_date,),
        )
        eligible, exclusions = eligible_delivered(rows)
        return collapse_delivered(eligible), exclusions

    async def _candidate_alerts(self, selected_date: str, *, scope: str) -> list[dict]:
        if scope == "confirmed":
            states = ("CONFIRMED",)
        elif scope == "watching":
            states = ("WATCHING", "CONFIRMED")
        else:
            states = ("SETUP", "WATCHING", "CONFIRMED")
        placeholders = ",".join("?" for _ in states)
        rows = await self._query(
            "SELECT e.event_id, e.event_type, e.stock_code, e.exchange_time, "
            "e.reason_code, e.strategy_version, e.new_state, e.payload_json, "
            "o.mfe_pct, o.mae_pct, o.close_return_pct "
            "FROM v2_decision_events e LEFT JOIN v2_outcomes o "
            "ON o.decision_event_id=e.event_id "
            "WHERE e.event_type IN "
            "('CANDIDATE_ENTERED','CANDIDATE_UPDATED','BUY_CONFIRMED') "
            f"AND e.new_state IN ({placeholders}) "
            "AND substr(e.exchange_time,1,10)=? "
            "ORDER BY e.exchange_time, e.id",
            (*states, selected_date),
        )
        return collapse_candidates(rows)

    async def _names(self, codes: list[str]) -> dict[str, str]:
        placeholders = ",".join("?" for _ in codes)
        rows = await self._query(
            f"SELECT code, COALESCE(name, '') FROM stocks WHERE code IN ({placeholders})",
            tuple(codes),
        )
        return {str(row[0]): str(row[1] or "") for row in rows}

    async def _klines(self, codes: list[str], start_date: str) -> dict[str, dict[str, tuple]]:
        placeholders = ",".join("?" for _ in codes)
        rows = await self._query(
            "SELECT stock_code, substr(time_key,1,10), close_price, high_price, low_price "
            f"FROM kline_data WHERE stock_code IN ({placeholders}) "
            "AND substr(time_key,1,10)>=? ORDER BY stock_code, time_key LIMIT 20000",
            (*codes, start_date),
        )
        result: dict[str, dict[str, tuple]] = defaultdict(dict)
        for row in rows:
            if row[2] is None:
                continue
            result[str(row[0])][str(row[1])] = (
                float(row[2]),
                float(row[3]) if row[3] is not None else float(row[2]),
                float(row[4]) if row[4] is not None else float(row[2]),
            )
        return dict(result)

    async def _intraday(self, codes: list[str], trade_date: str) -> dict[str, list[tuple]]:
        placeholders = ",".join("?" for _ in codes)
        rows = await self._query(
            "SELECT stock_code, minute, price, high, low FROM ticker_minute "
            f"WHERE stock_code IN ({placeholders}) AND trade_date=? "
            "ORDER BY stock_code, minute",
            (*codes, trade_date),
        )
        result: dict[str, list[tuple]] = defaultdict(list)
        for row in rows:
            if row[2] is None:
                continue
            price = float(row[2])
            result[str(row[0])].append((
                str(row[1]),
                price,
                float(row[3]) if row[3] is not None else price,
                float(row[4]) if row[4] is not None else price,
            ))
        return dict(result)

    async def _intraday_closes(self, codes: list[str], trade_date: str) -> dict[str, float]:
        placeholders = ",".join("?" for _ in codes)
        rows = await self._query(
            "SELECT t.stock_code, t.price FROM ticker_data t JOIN ("
            "SELECT stock_code, MAX(id) AS last_id FROM ticker_data "
            f"WHERE stock_code IN ({placeholders}) AND trade_date=? "
            "GROUP BY stock_code) latest ON latest.last_id=t.id",
            (*codes, trade_date),
        )
        return {
            str(row[0]): float(row[1])
            for row in rows
            if row[1] is not None
        }

    async def _query(self, sql: str, params: tuple = ()) -> list:
        return await asyncio.to_thread(self._db.execute_query, sql, params)

    @staticmethod
    def _validated_date(value: str | None) -> str:
        if value is None:
            return date.today().isoformat()
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as error:
            raise ValueError("交易日期必须是 YYYY-MM-DD") from error

    @staticmethod
    def _empty(trade_date: str, scope: str, *, exclusions: dict) -> dict:
        return {
            "trade_date": trade_date,
            "scope": scope,
            "items": [],
            "count": 0,
            "available_kline_through": None,
            "intraday_coverage_count": 0,
            "excluded": exclusions,
            "summary": performance_summary([]),
            "summary_by_strategy_version": {},
        }
