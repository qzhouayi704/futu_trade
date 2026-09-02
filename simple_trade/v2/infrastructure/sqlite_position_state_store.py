"""SQLite persistence for restart-safe V2 position analytics state."""

import asyncio
from datetime import datetime
import json
import sqlite3
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ...database.core.db_manager import DatabaseManager
from ..config.defaults import DEFAULT_WRITE_TIMEOUT_SECONDS
from ..domain.enums import PositionStatus
from ..domain.positions import PositionState
from ..domain.serialization import canonical_json, require_stock_code
from .db_write import submit_write
from .sqlite_state_store import StateConflictError


class PositionStateDatabasePort(Protocol):
    write_queue: object

    def execute_query(self, query: str, params: tuple | None = None) -> list: ...

    def transaction(self): ...


def save_position_state_cursor(
    cursor: sqlite3.Cursor,
    state: PositionState,
    expected_version: int,
) -> None:
    row = cursor.execute(
        "SELECT version FROM v2_position_states "
        "WHERE strategy_version=? AND stock_code=?",
        (state.strategy_version, state.stock_code),
    ).fetchone()
    current_version = int(row[0]) if row else 0
    if current_version != expected_version:
        raise StateConflictError(
            f"持仓状态版本冲突: current={current_version}, expected={expected_version}"
        )
    if state.version != expected_version + 1:
        raise ValueError("新持仓状态版本必须为 expected_version + 1")
    values = (
        state.status.value,
        state.version,
        state.last_event_id,
        state.opened_at.isoformat(),
        state.cost_price,
        state.peak_price,
        state.trough_price,
        state.mfe_pct,
        state.mae_pct,
        state.last_high_at.isoformat(),
        state.stalled_since.isoformat() if state.stalled_since else None,
        state.profit_ready_since.isoformat() if state.profit_ready_since else None,
        state.flow_peak,
        canonical_json(state.metadata),
        state.updated_at.isoformat(),
        state.strategy_version,
        state.stock_code,
    )
    if row:
        cursor.execute(
            "UPDATE v2_position_states SET status=?, version=?, last_event_id=?, "
            "opened_at=?, cost_price=?, peak_price=?, trough_price=?, mfe_pct=?, mae_pct=?, "
            "last_high_at=?, stalled_since=?, profit_ready_since=?, flow_peak=?, "
            "metadata_json=?, updated_at=? WHERE strategy_version=? AND stock_code=?",
            values,
        )
    else:
        cursor.execute(
            "INSERT INTO v2_position_states "
            "(status, version, last_event_id, opened_at, cost_price, peak_price, "
            "trough_price, mfe_pct, mae_pct, last_high_at, stalled_since, "
            "profit_ready_since, flow_peak, metadata_json, updated_at, "
            "strategy_version, stock_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )


class SqlitePositionStateStore:
    def __init__(
        self,
        db: "DatabaseManager | PositionStateDatabasePort",
        write_timeout: float = DEFAULT_WRITE_TIMEOUT_SECONDS,
    ) -> None:
        self._db = db
        self._write_timeout = write_timeout

    async def get(self, stock_code: str, strategy_version: str) -> PositionState | None:
        code = require_stock_code(stock_code)
        rows = await asyncio.to_thread(
            self._db.execute_query,
            self._select_sql("WHERE strategy_version=? AND stock_code=?"),
            (strategy_version, code),
        )
        return self._from_row(rows[0]) if rows else None

    async def list_open(self, strategy_version: str) -> tuple[PositionState, ...]:
        rows = await asyncio.to_thread(
            self._db.execute_query,
            self._select_sql("WHERE strategy_version=? AND status<>?"),
            (strategy_version, PositionStatus.CLOSED.value),
        )
        return tuple(self._from_row(row) for row in rows)

    async def list_latest_open(self) -> tuple[PositionState, ...]:
        rows = await asyncio.to_thread(
            self._db.execute_query,
            self._select_sql(""),
        )
        latest: dict[str, PositionState] = {}
        for row in rows:
            state = self._from_row(row)
            prior = latest.get(state.stock_code)
            if prior is None or state.updated_at > prior.updated_at:
                latest[state.stock_code] = state
        return tuple(
            state for state in latest.values()
            if state.status is not PositionStatus.CLOSED
        )

    async def save(self, state: PositionState, expected_version: int) -> None:
        await submit_write(
            self._db,
            self._save_sync,
            state,
            expected_version,
            timeout=self._write_timeout,
        )

    def _save_sync(self, state: PositionState, expected_version: int) -> None:
        with self._db.transaction() as cursor:
            save_position_state_cursor(cursor, state, expected_version)

    @staticmethod
    def _select_sql(where: str) -> str:
        return (
            "SELECT stock_code, strategy_version, status, version, last_event_id, "
            "updated_at, opened_at, cost_price, peak_price, trough_price, mfe_pct, "
            "mae_pct, last_high_at, stalled_since, profit_ready_since, flow_peak, "
            "metadata_json FROM v2_position_states " + where
        )

    @staticmethod
    def _from_row(row: tuple) -> PositionState:
        return PositionState(
            stock_code=row[0],
            strategy_version=row[1],
            status=PositionStatus(row[2]),
            version=int(row[3]),
            last_event_id=row[4],
            updated_at=datetime.fromisoformat(row[5]),
            opened_at=datetime.fromisoformat(row[6]),
            cost_price=float(row[7]),
            peak_price=float(row[8]),
            trough_price=float(row[9]),
            mfe_pct=float(row[10]),
            mae_pct=float(row[11]),
            last_high_at=datetime.fromisoformat(row[12]),
            stalled_since=datetime.fromisoformat(row[13]) if row[13] else None,
            profit_ready_since=datetime.fromisoformat(row[14]) if row[14] else None,
            flow_peak=float(row[15]),
            metadata=json.loads(row[16] or "{}"),
        )
