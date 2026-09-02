"""Cross-version intraday candidate summaries and per-stock timelines."""

import asyncio
from datetime import datetime, timedelta
import json
from typing import Protocol
from zoneinfo import ZoneInfo


class CandidateHistoryDatabasePort(Protocol):
    def execute_query(self, query: str, params: tuple | None = None) -> list: ...


class CandidateHistoryReader:
    EVENT_TYPES = (
        "CANDIDATE_ENTERED",
        "CANDIDATE_UPDATED",
        "CANDIDATE_INVALIDATED",
        "CANDIDATE_REJECTED",
        "BUY_CONFIRMED",
        "BUY_INVALIDATED",
    )

    def __init__(self, db: CandidateHistoryDatabasePort) -> None:
        self._db = db

    async def history(
        self,
        *,
        trade_date: str | None = None,
        scope: str = "entered",
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        day = self._trade_date(trade_date)
        if scope not in {"entered", "all"}:
            raise ValueError("候选历史范围必须是 entered 或 all")
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("候选历史分页参数无效")
        start_at, end_at = self._trade_day_bounds(day)
        placeholders = ",".join("?" for _ in self.EVENT_TYPES)
        filters = ["r.row_number=1"]
        params: list[object] = [*self.EVENT_TYPES, start_at, end_at]
        if scope == "entered":
            filters.append("s.meaningful_events>0")
        if status:
            filters.append("COALESCE(r.new_state, 'IDLE')=?")
            params.append(status.strip().upper())
        if search:
            term = f"%{search.strip()}%"
            filters.append("(r.stock_code LIKE ? OR COALESCE(st.name, '') LIKE ?)")
            params.extend((term.upper(), term))
        rows = await self._query(
            f"{self._history_cte(placeholders)} "
            "SELECT r.stock_code, COALESCE(st.name, ''), s.first_seen_at, "
            "s.last_seen_at, s.event_count, s.max_stage_rank, "
            "s.strategy_version_count, r.event_type, COALESCE(r.new_state, 'IDLE'), "
            "r.reason_code, r.strategy_version, latest.payload_json, COUNT(*) OVER() "
            "FROM ranked r JOIN summary s ON s.stock_code=r.stock_code "
            "JOIN v2_decision_events latest ON latest.id=r.id "
            "LEFT JOIN stocks st ON st.code=r.stock_code "
            f"WHERE {' AND '.join(filters)} "
            "ORDER BY s.max_stage_rank DESC, s.last_seen_at DESC, s.event_count DESC "
            "LIMIT ? OFFSET ?",
            tuple((*params, page_size, (page - 1) * page_size)),
        )
        return {
            "items": [self._history_row(row) for row in rows],
            "total": int(rows[0][12]) if rows else 0,
            "page": page,
            "page_size": page_size,
            "trade_date": day,
            "scope": scope,
        }

    async def timeline(
        self,
        stock_code: str,
        *,
        trade_date: str | None = None,
    ) -> dict:
        day = self._trade_date(trade_date)
        start_at, end_at = self._trade_day_bounds(day)
        placeholders = ",".join("?" for _ in self.EVENT_TYPES)
        code = stock_code.strip().upper()
        rows = await self._query(
            "SELECT event_id, event_type, stock_code, exchange_time, old_state, "
            "new_state, reason_code, payload_json, strategy_version "
            "FROM v2_decision_events WHERE stock_code=? "
            "AND exchange_time>=? AND exchange_time<? "
            f"AND event_type IN ({placeholders}) "
            "ORDER BY exchange_time ASC, id ASC LIMIT 1000",
            (code, start_at, end_at, *self.EVENT_TYPES),
        )
        return {
            "items": [self._timeline_row(row) for row in rows],
            "count": len(rows),
            "stock_code": code,
            "trade_date": day,
        }

    async def _query(self, sql: str, params: tuple) -> list:
        return await asyncio.to_thread(self._db.execute_query, sql, params)

    @staticmethod
    def _trade_date(value: str | None) -> str:
        day = value or datetime.now(ZoneInfo("Asia/Hong_Kong")).date().isoformat()
        try:
            return datetime.strptime(day, "%Y-%m-%d").date().isoformat()
        except ValueError as error:
            raise ValueError("交易日期必须是 YYYY-MM-DD") from error

    @staticmethod
    def _trade_day_bounds(day: str) -> tuple[str, str]:
        start = datetime.strptime(day, "%Y-%m-%d")
        return (
            f"{start.date().isoformat()}T00:00:00",
            f"{(start + timedelta(days=1)).date().isoformat()}T00:00:00",
        )

    @staticmethod
    def _history_cte(placeholders: str) -> str:
        return (
            "WITH filtered AS (SELECT e.id, e.stock_code, e.exchange_time, "
            "e.event_type, e.new_state, e.reason_code, e.strategy_version, "
            "CASE COALESCE(e.new_state, '') WHEN 'CONFIRMED' THEN 4 "
            "WHEN 'WATCHING' THEN 3 WHEN 'SETUP' THEN 2 "
            "WHEN 'INVALIDATED' THEN 1 ELSE 0 END AS stage_rank, "
            "CASE WHEN e.event_type='CANDIDATE_REJECTED' THEN 0 ELSE 1 END AS meaningful "
            "FROM v2_decision_events e "
            f"WHERE e.event_type IN ({placeholders}) "
            "AND e.exchange_time>=? AND e.exchange_time<?), "
            "ranked AS (SELECT filtered.*, ROW_NUMBER() OVER (PARTITION BY stock_code "
            "ORDER BY exchange_time DESC, id DESC) AS row_number FROM filtered), "
            "summary AS (SELECT stock_code, MIN(exchange_time) AS first_seen_at, "
            "MAX(exchange_time) AS last_seen_at, COUNT(*) AS event_count, "
            "MAX(stage_rank) AS max_stage_rank, "
            "COUNT(DISTINCT strategy_version) AS strategy_version_count, "
            "SUM(meaningful) AS meaningful_events FROM filtered GROUP BY stock_code)"
        )

    @staticmethod
    def _history_row(row: tuple) -> dict:
        payload = json.loads(row[11] or "{}")
        feature = payload.get("feature_snapshot") or {}
        score = payload.get("candidate_score") or {}
        stages = {
            0: "EVALUATED", 1: "INVALIDATED", 2: "SETUP",
            3: "WATCHING", 4: "CONFIRMED",
        }
        return {
            "stock_code": row[0], "stock_name": row[1],
            "first_seen_at": row[2], "last_seen_at": row[3],
            "event_count": int(row[4]),
            "max_stage": stages.get(int(row[5]), "EVALUATED"),
            "latest_score": score.get("total"),
            "strategy_version_count": int(row[6]),
            "latest_event_type": row[7], "latest_status": row[8],
            "latest_reason_code": row[9], "latest_strategy_version": row[10],
            "quote": feature.get("quote"),
            "capital_memory": feature.get("capital_memory"),
        }

    @staticmethod
    def _timeline_row(row: tuple) -> dict:
        payload = json.loads(row[7] or "{}")
        score = payload.get("candidate_score") or {}
        feature = payload.get("feature_snapshot") or {}
        memory = feature.get("capital_memory") or {}
        return {
            "event_id": row[0], "event_type": row[1], "stock_code": row[2],
            "exchange_time": row[3], "old_state": row[4], "new_state": row[5],
            "reason_code": row[6], "strategy_version": row[8],
            "score": score.get("total"), "capital_state": memory.get("state"),
            "day_main_net": memory.get("day_main_net"),
        }
