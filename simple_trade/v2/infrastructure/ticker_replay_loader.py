"""Read persisted ticker rows needed to rebuild V2 intraday capital state."""

import asyncio
from datetime import datetime, timedelta
from math import isfinite
from typing import Protocol

from ...utils.trade_time import market_datetime
from .db_read import strict_reader


class TickerReplayLimitExceeded(RuntimeError):
    """A truncated replay cannot be treated as a restored trading state."""


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
        if window_seconds <= 0 or not isfinite(minimum_large_turnover) or minimum_large_turnover <= 0 or row_limit <= 0:
            raise ValueError("ticker replay limits must be positive")
        self._db = strict_reader(db, timeout_seconds=30.0)
        self._window_seconds = window_seconds
        self._minimum_large_turnover = minimum_large_turnover
        self._row_limit = row_limit

    async def load(
        self, trade_date: str, as_of: datetime, *, minimum_large_turnover: float | None = None,
    ) -> tuple[dict, ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("replay as_of must include a timezone")
        as_of = market_datetime(as_of)
        if as_of.date().isoformat() != trade_date:
            raise ValueError("replay date must match the market date")
        threshold = self._minimum_large_turnover if minimum_large_turnover is None else minimum_large_turnover
        if not isfinite(threshold) or threshold <= 0:
            raise ValueError("replay threshold must be positive")
        cutoff = as_of - timedelta(seconds=self._window_seconds)
        us_time = market_datetime(as_of, "US.")
        us_midnight = us_time.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() if us_time else None
        us_offset = f"{-int(us_time.utcoffset().total_seconds() / 60):+d} minutes" if us_time else None
        trade_jd = (
            "CASE WHEN substr(trade_time,-6,1) IN ('+','-') "
            "OR upper(substr(trade_time,-1))='Z' THEN julianday(trade_time) "
            "WHEN stock_code LIKE 'US.%' THEN julianday(trade_time, (SELECT us_offset FROM settings)) "
            "ELSE julianday(trade_time,'-8 hours') END"
        )
        rows = await asyncio.to_thread(
            self._db.execute_query,
            "WITH settings(us_offset) AS (VALUES (?)) "
            "SELECT stock_code, trade_time, price, volume, turnover, direction, sequence "
            "FROM ticker_data WHERE trade_date BETWEEN ? AND ? AND direction IN ('BUY','SELL') "
            f"AND {trade_jd}>=julianday(CASE WHEN stock_code LIKE 'US.%' THEN ? ELSE ? END) "
            f"AND {trade_jd}<=julianday(?) "
            f"AND ({trade_jd}>=julianday(?) OR turnover>=?) "
            f"ORDER BY {trade_jd}, id LIMIT ?",
            (
                us_offset,
                (as_of.date() - timedelta(days=1)).isoformat(),
                (as_of.date() + timedelta(days=1)).isoformat(),
                us_midnight,
                as_of.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                as_of.isoformat(), cutoff.isoformat(), threshold, self._row_limit + 1,
            ),
        )
        if len(rows) > self._row_limit:
            raise TickerReplayLimitExceeded(f"V2 ticker replay exceeds {self._row_limit} rows")
        return tuple(
            {
                "stock_code": str(row[0]),
                "time": market_datetime(row[1], str(row[0])).isoformat(),
                "price": row[2],
                "volume": row[3],
                "turnover": row[4],
                "direction": row[5],
                # Futu sequence restarts across requests and is not a stable replay key.
                "sequence": None,
            }
            for row in rows
        )
