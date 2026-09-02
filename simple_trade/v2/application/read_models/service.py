"""Precomputed SQLite-backed read models for the V2 workbench."""

import asyncio
from dataclasses import asdict, is_dataclass
import json
from typing import Protocol

from ...domain.serialization import to_primitive
from .cohorts import build_shadow_acceptance
from .distribution import histogram, summary


class ReadDatabasePort(Protocol):
    def execute_query(self, query: str, params: tuple | None = None) -> list: ...


class V2ReadModelService:
    def __init__(self, db: ReadDatabasePort, runtime=None) -> None:
        self._db = db
        self._runtime = runtime

    async def cockpit(self) -> dict:
        candidates, positions, decisions, distribution = await asyncio.gather(
            self.candidates(limit=8), self.positions(), self.decisions(limit=12),
            self.outcome_distribution(),
        )
        return {
            "mode": self._runtime_mode(),
            "strategy_version": self._strategy_version(),
            "summary": {
                "confirmed_candidates": sum(
                    item["status"] == "CONFIRMED" for item in candidates["items"]
                ),
                "open_positions": len(positions["items"]),
                "actionable_positions": sum(
                    item["status"] in {"PROFIT_READY", "STALLED", "EXIT_RISK", "ROTATION_READY"}
                    for item in positions["items"]
                ),
                "evaluated_signals": distribution["sample_count"],
                "reached_5_ratio": distribution["milestones"]["reached_5_ratio"],
            },
            "candidates": candidates["items"],
            "positions": positions["items"],
            "decisions": decisions["items"],
        }

    async def candidates(self, limit: int = 50, stock_code: str | None = None) -> dict:
        conditions: list[str] = []
        params: list[object] = []
        strategy_version = self._strategy_version()
        if strategy_version:
            conditions.append("s.strategy_version=?")
            params.append(strategy_version)
        if stock_code:
            conditions.append("s.stock_code=?")
            params.append(stock_code.strip().upper())
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = await self._query(
            "SELECT s.stock_code, COALESCE(st.name, ''), s.status, s.version, "
            "s.confirmed_price, s.peak_price, s.updated_at, s.metadata_json, "
            "e.reason_code, e.payload_json, e.exchange_time "
            "FROM v2_strategy_states s "
            "LEFT JOIN v2_decision_events e ON e.event_id=s.last_event_id "
            "LEFT JOIN stocks st ON st.code=s.stock_code "
            f"{where} ORDER BY CASE s.status "
            "WHEN 'CONFIRMED' THEN 0 WHEN 'WATCHING' THEN 1 "
            "WHEN 'SETUP' THEN 2 ELSE 3 END, s.updated_at DESC LIMIT ?",
            tuple(params),
        )
        items = [self._candidate_row(row) for row in rows]
        return {"items": items, "count": len(items)}

    async def positions(self) -> dict:
        strategy_version = self._strategy_version()
        version_filter = " AND p.strategy_version=?" if strategy_version else ""
        params = (strategy_version,) if strategy_version else ()
        rows = await self._query(
            "SELECT p.stock_code, COALESCE(st.name, ''), p.status, p.opened_at, "
            "p.cost_price, p.peak_price, p.trough_price, p.mfe_pct, p.mae_pct, "
            "p.last_high_at, p.stalled_since, p.profit_ready_since, p.flow_peak, "
            "p.metadata_json, p.updated_at, e.reason_code, e.payload_json "
            "FROM v2_position_states p "
            "LEFT JOIN v2_decision_events e ON e.event_id=p.last_event_id "
            "LEFT JOIN stocks st ON st.code=p.stock_code "
            "WHERE p.status NOT IN ('FLAT','CLOSED')"
            f"{version_filter} ORDER BY p.updated_at DESC",
            params,
        )
        items = [self._position_row(row) for row in rows]
        return {"items": items, "count": len(items)}

    async def decisions(self, limit: int = 100, event_id: str | None = None) -> dict:
        where = "WHERE event_id=?" if event_id else ""
        params = (event_id, limit) if event_id else (limit,)
        rows = await self._query(
            "SELECT event_id, event_type, stock_code, exchange_time, old_state, "
            "new_state, reason_code, payload_json, strategy_version "
            f"FROM v2_decision_events {where} ORDER BY exchange_time DESC, id DESC LIMIT ?",
            params,
        )
        items = [self._decision_row(row) for row in rows]
        return {"items": items, "count": len(items)}

    async def outcome_distribution(self) -> dict:
        rows = await self._query(
            "SELECT o.decision_event_id, o.stock_code, COALESCE(st.name, ''), "
            "e.event_type, o.signal_time, o.signal_price, o.mfe_pct, o.mae_pct, "
            "o.close_return_pct, o.next_day_return_pct, o.reached_1_5, o.reached_3, "
            "o.reached_5, o.time_to_1_5_seconds, o.time_to_3_seconds, "
            "o.time_to_5_seconds, o.time_to_peak_seconds, "
            "o.hold_control_return_pct, o.rotation_return_pct "
            "FROM v2_outcomes o JOIN v2_decision_events e "
            "ON e.event_id=o.decision_event_id LEFT JOIN stocks st ON st.code=o.stock_code "
            "WHERE e.event_type IN ('BUY_CONFIRMED','ROTATION_PROPOSED') "
            "ORDER BY o.signal_time DESC LIMIT 2000"
        )
        mfe = [float(row[6]) for row in rows if row[6] is not None]
        mae = [float(row[7]) for row in rows if row[7] is not None]
        closes = [float(row[8]) for row in rows if row[8] is not None]
        rotations = [
            float(row[18]) - float(row[17]) for row in rows
            if row[17] is not None and row[18] is not None
        ]
        count = len(rows)
        return {
            "sample_count": count,
            "mfe": {**summary(mfe), "histogram": histogram(mfe)},
            "mae": summary(mae),
            "close_return": {**summary(closes), "histogram": histogram(closes)},
            "rotation_advantage": summary(rotations),
            "milestones": {
                "reached_1_5_ratio": self._ratio(rows, 10),
                "reached_3_ratio": self._ratio(rows, 11),
                "reached_5_ratio": self._ratio(rows, 12),
            },
            "items": [self._outcome_row(row) for row in rows[:200]],
        }

    async def shadow_acceptance(self, days: int = 10) -> dict:
        rows = await self._query(
            "SELECT o.decision_event_id, e.event_type, e.reason_code, o.signal_time, "
            "o.stock_code, o.mfe_pct, o.mae_pct, o.close_return_pct, "
            "o.next_day_return_pct, o.reached_1_5, o.reached_3, o.reached_5, "
            "o.time_to_1_5_seconds, o.hold_control_return_pct, "
            "o.rotation_return_pct, e.payload_json "
            "FROM v2_outcomes o JOIN v2_decision_events e "
            "ON e.event_id=o.decision_event_id "
            "WHERE e.event_type IN "
            "('CANDIDATE_UPDATED','BUY_CONFIRMED','ROTATION_PROPOSED') "
            "ORDER BY o.signal_time DESC LIMIT 10000"
        )
        return build_shadow_acceptance(
            [self._acceptance_row(row) for row in rows], target_days=days
        )

    async def runtime(self) -> dict:
        if self._runtime is None:
            return {"enabled": False, "started": False, "mode": "disabled"}
        snapshot = self._runtime.snapshot()
        return to_primitive(snapshot) if is_dataclass(snapshot) else asdict(snapshot)

    async def health(self) -> dict:
        runtime = await self.runtime()
        bus = runtime.get("event_bus", {})
        tasks = runtime.get("tasks", [])
        return {
            "status": "running" if runtime.get("started") else "disabled",
            "mode": runtime.get("mode", "disabled"),
            "event_queue": {
                "size": bus.get("queue_size", 0),
                "capacity": bus.get("queue_capacity", 0),
                "dropped": bus.get("dropped", 0),
            },
            "tasks": tasks,
            "execution_enabled": False,
        }

    async def _query(self, sql: str, params: tuple | None = None) -> list:
        return await asyncio.to_thread(self._db.execute_query, sql, params or ())

    def _runtime_mode(self) -> str:
        return self._runtime.config.mode.value if self._runtime is not None else "disabled"

    def _strategy_version(self) -> str | None:
        return self._runtime.config.strategy_version if self._runtime is not None else None

    @staticmethod
    def _candidate_row(row: tuple) -> dict:
        payload = json.loads(row[9] or "{}")
        score = payload.get("candidate_score") or {}
        portfolio = payload.get("strategy_portfolio") or {}
        feature = payload.get("feature_snapshot") or {}
        return {
            "stock_code": row[0], "stock_name": row[1], "status": row[2],
            "version": row[3], "confirmed_price": row[4], "peak_price": row[5],
            "updated_at": row[6], "reason_code": row[8],
            "score": score.get("total"), "quality": score.get("quality"),
            "portfolio_score": portfolio.get("ranking_score"),
            "strategy_sources": portfolio.get("strategy_sources", []),
            "consensus_count": portfolio.get("consensus_count", 0),
            "strategy_nominations": portfolio.get("nominations", []),
            "alert_eligible": payload.get("alert_eligible", True),
            "market_context": feature.get("market_context"),
            "price_position": feature.get("price_position"),
            "price_acceptance": feature.get("price_acceptance"),
            "capital_memory": feature.get("capital_memory"),
            "capital_windows": feature.get("tick_windows", []),
            "quote": feature.get("quote"),
        }

    @staticmethod
    def _position_row(row: tuple) -> dict:
        metadata = json.loads(row[13] or "{}")
        payload = json.loads(row[16] or "{}")
        return {
            "stock_code": row[0], "stock_name": row[1], "status": row[2],
            "opened_at": row[3], "cost_price": row[4], "peak_price": row[5],
            "trough_price": row[6], "mfe_pct": row[7], "mae_pct": row[8],
            "last_high_at": row[9], "stalled_since": row[10],
            "profit_ready_since": row[11], "flow_peak": row[12],
            "updated_at": row[14], "reason_code": row[15],
            "last_action": metadata.get("last_action"),
            "position": payload.get("position"),
            "efficiency": payload.get("efficiency"),
            "rotation": payload.get("rotation"),
        }

    @staticmethod
    def _decision_row(row: tuple) -> dict:
        return {
            "event_id": row[0], "event_type": row[1], "stock_code": row[2],
            "exchange_time": row[3], "old_state": row[4], "new_state": row[5],
            "reason_code": row[6], "payload": json.loads(row[7] or "{}"),
            "strategy_version": row[8],
        }

    @staticmethod
    def _outcome_row(row: tuple) -> dict:
        return {
            "event_id": row[0], "stock_code": row[1], "stock_name": row[2],
            "event_type": row[3], "signal_time": row[4], "signal_price": row[5],
            "mfe_pct": row[6], "mae_pct": row[7], "close_return_pct": row[8],
            "next_day_return_pct": row[9], "reached_1_5": bool(row[10]),
            "reached_3": bool(row[11]), "reached_5": bool(row[12]),
            "time_to_1_5_seconds": row[13], "time_to_3_seconds": row[14],
            "time_to_5_seconds": row[15], "time_to_peak_seconds": row[16],
            "hold_control_return_pct": row[17], "rotation_return_pct": row[18],
        }

    @staticmethod
    def _acceptance_row(row: tuple) -> dict:
        return {
            "event_id": row[0], "event_type": row[1], "reason_code": row[2],
            "signal_time": row[3], "stock_code": row[4], "mfe_pct": row[5],
            "mae_pct": row[6], "close_return_pct": row[7],
            "next_day_return_pct": row[8], "reached_1_5": bool(row[9]),
            "reached_3": bool(row[10]), "reached_5": bool(row[11]),
            "time_to_1_5_seconds": row[12], "hold_control_return_pct": row[13],
            "rotation_return_pct": row[14], "payload": json.loads(row[15] or "{}"),
        }

    @staticmethod
    def _ratio(rows: list[tuple], index: int) -> float:
        return round(sum(bool(row[index]) for row in rows) / len(rows), 4) if rows else 0.0
