"""Read persisted ticker rows needed to rebuild V2 intraday capital state."""

import asyncio
from datetime import datetime
from typing import Protocol


class TickerReplayDatabasePort(Protocol):
    def execute_query(self, query: str, params: tuple | None = None) -> list: ...


class TickerReplayLoader:
    def __init__(
        self,
        db: TickerReplayDatabasePort,
        *,
        window_seconds: int = 3600,
        minimum_large_turnover: float = 100_000.0,
        row_limit: int = 500_000,
    ) -> None:
        if window_seconds <= 0 or minimum_large_turnover <= 0 or row_limit <= 0:
            raise ValueError("ticker replay limits must be positive")
        self._db = db
        self._window_seconds = window_seconds
        self._minimum_large_turnover = minimum_large_turnover
        self._row_limit = row_limit

    async def load(self, trade_date: str, as_of: datetime) -> tuple[dict, ...]:
        cutoff_ms = int((as_of.timestamp() - self._window_seconds) * 1000)
        rows = await asyncio.to_thread(
            self._db.execute_query,
            "SELECT stock_code, trade_time, price, volume, turnover, direction, sequence "
            "FROM ticker_data WHERE trade_date=? AND direction IN ('BUY','SELL') "
            "AND (timestamp>=? OR turnover>=?) "
            "ORDER BY trade_time, id LIMIT ?",
            (
                trade_date,
                cutoff_ms,
                self._minimum_large_turnover,
                self._row_limit,
            ),
        )
        return tuple(
            {
                "stock_code": str(row[0]),
                "time": row[1],
                "price": row[2],
                "volume": row[3],
                "turnover": row[4],
                "direction": row[5],
                # Futu sequence restarts across requests and is not a stable replay key.
                "sequence": None,
            }
            for row in rows
        )
