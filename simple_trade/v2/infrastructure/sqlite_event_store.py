"""V2 决策事件 SQLite 适配器。"""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
import json
import sqlite3
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ...database.core.db_manager import DatabaseManager
from ..config.defaults import DEFAULT_WRITE_TIMEOUT_SECONDS
from ..domain.decisions import DecisionEvent, StrategyState
from ..domain.enums import EventType
from ..domain.serialization import canonical_json, require_aware, require_stock_code
from .db_write import submit_write
from .sqlite_state_store import save_state_cursor
from .sqlite_position_state_store import save_position_state_cursor
from ..domain.positions import PositionState


class EventStoreDatabasePort(Protocol):
    write_queue: object

    def execute_query(self, query: str, params: tuple | None = None) -> list: ...

    def transaction(self): ...


class SqliteEventStore:
    def __init__(
        self,
        db: "DatabaseManager | EventStoreDatabasePort",
        write_timeout: float = DEFAULT_WRITE_TIMEOUT_SECONDS,
    ) -> None:
        self._db = db
        self._write_timeout = write_timeout

    async def append(self, event: DecisionEvent) -> bool:
        return await submit_write(
            self._db,
            self._append_sync,
            event,
            timeout=self._write_timeout,
        )

    async def append_with_state(
        self,
        event: DecisionEvent,
        state: StrategyState,
        expected_version: int,
    ) -> bool:
        if state.last_event_id != event.event_id:
            raise ValueError("state.last_event_id 必须等于 event.event_id")
        if state.stock_code != event.stock_code:
            raise ValueError("state 与 event 的 stock_code 不一致")
        if state.strategy_version != event.strategy_version:
            raise ValueError("state 与 event 的 strategy_version 不一致")
        return await submit_write(
            self._db,
            self._append_with_state_sync,
            event,
            state,
            expected_version,
            timeout=self._write_timeout,
        )

    async def append_with_position_state(
        self,
        event: DecisionEvent,
        state: PositionState,
        expected_version: int,
    ) -> bool:
        if state.last_event_id != event.event_id:
            raise ValueError("position state.last_event_id 必须等于 event.event_id")
        if state.stock_code != event.stock_code:
            raise ValueError("position state 与 event 的 stock_code 不一致")
        if state.strategy_version != event.strategy_version:
            raise ValueError("position state 与 event 的 strategy_version 不一致")
        return await submit_write(
            self._db,
            self._append_with_position_state_sync,
            event,
            state,
            expected_version,
            timeout=self._write_timeout,
        )

    async def load(
        self,
        stock_code: str,
        strategy_version: str,
    ) -> list[DecisionEvent]:
        code = require_stock_code(stock_code)
        rows = await asyncio.to_thread(
            self._db.execute_query,
            self._select_sql(
                "WHERE stock_code=? AND strategy_version=? ORDER BY exchange_time, id"
            ),
            (code, strategy_version),
        )
        return [self._from_row(row) for row in rows]

    async def stream(
        self,
        start_at: datetime,
        end_at: datetime,
    ) -> AsyncIterator[DecisionEvent]:
        require_aware(start_at, "start_at")
        require_aware(end_at, "end_at")
        if end_at < start_at:
            raise ValueError("end_at 不能早于 start_at")
        rows = await asyncio.to_thread(
            self._db.execute_query,
            self._select_sql(
                "WHERE exchange_time>=? AND exchange_time<=? ORDER BY exchange_time, id"
            ),
            (start_at.isoformat(), end_at.isoformat()),
        )
        for row in rows:
            yield self._from_row(row)

    def _append_sync(self, event: DecisionEvent) -> bool:
        with self._db.transaction() as cursor:
            return self._insert_event_cursor(cursor, event)

    def _append_with_state_sync(
        self,
        event: DecisionEvent,
        state: StrategyState,
        expected_version: int,
    ) -> bool:
        with self._db.transaction() as cursor:
            inserted = self._insert_event_cursor(cursor, event)
            if not inserted:
                return False
            save_state_cursor(cursor, state, expected_version)
            return True

    def _append_with_position_state_sync(
        self,
        event: DecisionEvent,
        state: PositionState,
        expected_version: int,
    ) -> bool:
        with self._db.transaction() as cursor:
            inserted = self._insert_event_cursor(cursor, event)
            if not inserted:
                return False
            save_position_state_cursor(cursor, state, expected_version)
            return True

    @staticmethod
    def _insert_event_cursor(cursor: sqlite3.Cursor, event: DecisionEvent) -> bool:
        cursor.execute(
            "INSERT OR IGNORE INTO v2_decision_events "
            "(event_id, event_type, schema_version, strategy_version, stock_code, "
            "exchange_time, received_time, sequence, correlation_id, source, old_state, "
            "new_state, reason_code, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.event_id,
                event.event_type.value,
                event.schema_version,
                event.strategy_version,
                event.stock_code,
                event.exchange_time.isoformat(),
                event.received_time.isoformat(),
                event.sequence,
                event.correlation_id,
                event.source,
                event.old_state,
                event.new_state,
                event.reason_code,
                canonical_json(event.payload),
            ),
        )
        return cursor.rowcount == 1

    @staticmethod
    def _select_sql(where_clause: str) -> str:
        return (
            "SELECT event_id, event_type, schema_version, strategy_version, stock_code, "
            "exchange_time, received_time, sequence, correlation_id, source, old_state, "
            "new_state, reason_code, payload_json FROM v2_decision_events "
            + where_clause
        )

    @staticmethod
    def _from_row(row: tuple) -> DecisionEvent:
        return DecisionEvent(
            event_id=row[0],
            event_type=EventType(row[1]),
            schema_version=int(row[2]),
            strategy_version=row[3],
            stock_code=row[4],
            exchange_time=datetime.fromisoformat(row[5]),
            received_time=datetime.fromisoformat(row[6]),
            sequence=row[7],
            correlation_id=row[8],
            source=row[9],
            old_state=row[10],
            new_state=row[11],
            reason_code=row[12],
            payload=json.loads(row[13] or "{}"),
        )
