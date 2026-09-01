"""SQLite outcome projection with serialized writes."""

import asyncio
from datetime import datetime
import json
from typing import Protocol

from ...config.defaults import DEFAULT_WRITE_TIMEOUT_SECONDS
from ...domain.outcomes import OutcomeRecord
from ..db_write import submit_write


class OutcomeDatabasePort(Protocol):
    write_queue: object

    def execute_query(self, query: str, params: tuple | None = None) -> list: ...

    def transaction(self): ...


class SqliteOutcomeStore:
    def __init__(
        self,
        db: OutcomeDatabasePort,
        write_timeout: float = DEFAULT_WRITE_TIMEOUT_SECONDS,
    ) -> None:
        self._db = db
        self._write_timeout = write_timeout

    async def upsert(self, outcome: OutcomeRecord) -> bool:
        return await submit_write(
            self._db, self._upsert_sync, outcome, timeout=self._write_timeout
        )

    async def load_active(self, strategy_version: str) -> tuple[OutcomeRecord, ...]:
        rows = await asyncio.to_thread(
            self._db.execute_query,
            "SELECT o.decision_event_id, o.stock_code, o.strategy_version, o.signal_time, "
            "signal_price, mfe_pct, mae_pct, close_return_pct, next_day_return_pct, "
            "time_to_1_5_seconds, time_to_3_seconds, time_to_5_seconds, "
            "time_to_peak_seconds, hold_control_return_pct, rotation_return_pct, "
            "evaluated_at, e.stock_code, e.payload_json, e.event_type "
            "FROM v2_outcomes o JOIN v2_decision_events e "
            "ON e.event_id=o.decision_event_id WHERE o.strategy_version=? "
            "AND o.next_day_return_pct IS NULL ORDER BY o.signal_time",
            (strategy_version,),
        )
        return tuple(self._from_row(row) for row in rows)

    def _upsert_sync(self, outcome: OutcomeRecord) -> bool:
        with self._db.transaction() as cursor:
            cursor.execute(
                "INSERT INTO v2_outcomes (decision_event_id, stock_code, strategy_version, "
                "signal_time, signal_price, mfe_pct, mae_pct, close_return_pct, "
                "next_day_return_pct, reached_1_5, reached_3, reached_5, "
                "time_to_1_5_seconds, time_to_3_seconds, time_to_5_seconds, "
                "time_to_peak_seconds, hold_control_return_pct, rotation_return_pct, "
                "evaluated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(decision_event_id) DO UPDATE SET "
                "mfe_pct=excluded.mfe_pct, mae_pct=excluded.mae_pct, "
                "close_return_pct=excluded.close_return_pct, "
                "next_day_return_pct=excluded.next_day_return_pct, "
                "reached_1_5=excluded.reached_1_5, reached_3=excluded.reached_3, "
                "reached_5=excluded.reached_5, "
                "time_to_1_5_seconds=excluded.time_to_1_5_seconds, "
                "time_to_3_seconds=excluded.time_to_3_seconds, "
                "time_to_5_seconds=excluded.time_to_5_seconds, "
                "time_to_peak_seconds=excluded.time_to_peak_seconds, "
                "hold_control_return_pct=excluded.hold_control_return_pct, "
                "rotation_return_pct=excluded.rotation_return_pct, "
                "evaluated_at=excluded.evaluated_at",
                (
                    outcome.decision_event_id,
                    outcome.stock_code,
                    outcome.strategy_version,
                    outcome.signal_time.isoformat(),
                    outcome.signal_price,
                    outcome.mfe_pct,
                    outcome.mae_pct,
                    outcome.close_return_pct,
                    outcome.next_day_return_pct,
                    int(outcome.reached_1_5),
                    int(outcome.reached_3),
                    int(outcome.reached_5),
                    outcome.time_to_1_5_seconds,
                    outcome.time_to_3_seconds,
                    outcome.time_to_5_seconds,
                    outcome.time_to_peak_seconds,
                    outcome.hold_control_return_pct,
                    outcome.rotation_return_pct,
                    outcome.evaluated_at.isoformat() if outcome.evaluated_at else None,
                ),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _from_row(row: tuple) -> OutcomeRecord:
        payload = json.loads(row[17] or "{}")
        position = payload.get("position") if row[18] == "ROTATION_PROPOSED" else None
        control_price = position.get("current_price") if isinstance(position, dict) else None
        return OutcomeRecord(
            decision_event_id=row[0], stock_code=row[1], strategy_version=row[2],
            signal_time=datetime.fromisoformat(row[3]), signal_price=float(row[4]),
            mfe_pct=float(row[5] or 0), mae_pct=float(row[6] or 0),
            close_return_pct=row[7], next_day_return_pct=row[8],
            time_to_1_5_seconds=row[9], time_to_3_seconds=row[10],
            time_to_5_seconds=row[11], time_to_peak_seconds=row[12],
            hold_control_return_pct=row[13], rotation_return_pct=row[14],
            evaluated_at=datetime.fromisoformat(row[15]) if row[15] else None,
            control_stock_code=row[16] if row[18] == "ROTATION_PROPOSED" else None,
            control_signal_price=float(control_price) if control_price is not None else None,
        )
