"""V2 策略状态 SQLite 适配器。"""

import asyncio
from datetime import datetime
import json
import sqlite3
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ...database.core.db_manager import DatabaseManager
from ..config.defaults import DEFAULT_WRITE_TIMEOUT_SECONDS
from ..domain.decisions import StrategyState
from ..domain.enums import StrategyStatus
from ..domain.serialization import canonical_json, require_stock_code
from .db_write import submit_write


class StateStoreDatabasePort(Protocol):
    write_queue: object

    def execute_query(self, query: str, params: tuple | None = None) -> list: ...

    def transaction(self): ...


class StateConflictError(RuntimeError):
    """状态版本与预期不一致。"""


def save_state_cursor(
    cursor: sqlite3.Cursor,
    state: StrategyState,
    expected_version: int,
) -> None:
    row = cursor.execute(
        "SELECT version FROM v2_strategy_states "
        "WHERE strategy_version=? AND stock_code=?",
        (state.strategy_version, state.stock_code),
    ).fetchone()
    current_version = int(row[0]) if row else 0
    if current_version != expected_version:
        raise StateConflictError(
            f"状态版本冲突: current={current_version}, expected={expected_version}"
        )
    if state.version != expected_version + 1:
        raise ValueError(
            f"新状态版本必须为 expected_version + 1: state={state.version}, "
            f"expected={expected_version}"
        )

    values = (
        state.status.value,
        state.version,
        state.last_event_id,
        state.confirmed_price,
        state.peak_price,
        state.last_sequence,
        canonical_json(state.metadata),
        state.updated_at.isoformat(),
        state.strategy_version,
        state.stock_code,
    )
    if row:
        cursor.execute(
            "UPDATE v2_strategy_states SET status=?, version=?, last_event_id=?, "
            "confirmed_price=?, peak_price=?, last_sequence=?, metadata_json=?, updated_at=? "
            "WHERE strategy_version=? AND stock_code=?",
            values,
        )
    else:
        cursor.execute(
            "INSERT INTO v2_strategy_states "
            "(status, version, last_event_id, confirmed_price, peak_price, last_sequence, "
            "metadata_json, updated_at, strategy_version, stock_code) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )


class SqliteStateStore:
    def __init__(
        self,
        db: "DatabaseManager | StateStoreDatabasePort",
        write_timeout: float = DEFAULT_WRITE_TIMEOUT_SECONDS,
    ) -> None:
        self._db = db
        self._write_timeout = write_timeout

    async def get(self, stock_code: str, strategy_version: str) -> StrategyState | None:
        code = require_stock_code(stock_code)
        rows = await asyncio.to_thread(
            self._db.execute_query,
            "SELECT stock_code, strategy_version, status, version, last_event_id, "
            "updated_at, confirmed_price, peak_price, last_sequence, metadata_json "
            "FROM v2_strategy_states WHERE strategy_version=? AND stock_code=?",
            (strategy_version, code),
        )
        if not rows:
            return None
        return self._from_row(rows[0])

    async def save(self, state: StrategyState, expected_version: int) -> None:
        await submit_write(
            self._db,
            self._save_sync,
            state,
            expected_version,
            timeout=self._write_timeout,
        )

    def _save_sync(self, state: StrategyState, expected_version: int) -> None:
        with self._db.transaction() as cursor:
            save_state_cursor(cursor, state, expected_version)

    @staticmethod
    def _from_row(row: tuple) -> StrategyState:
        return StrategyState(
            stock_code=row[0],
            strategy_version=row[1],
            status=StrategyStatus(row[2]),
            version=int(row[3]),
            last_event_id=row[4],
            updated_at=datetime.fromisoformat(row[5]),
            confirmed_price=row[6],
            peak_price=row[7],
            last_sequence=row[8],
            metadata=json.loads(row[9] or "{}"),
        )
