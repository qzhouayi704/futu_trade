"""Read persisted ticker rows needed to rebuild V2 intraday capital state."""

import asyncio
from datetime import datetime, timedelta, timezone
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
        local_midnight = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        receipt_start = min(
            local_midnight.astimezone(timezone.utc),
            us_time.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc),
        )
        receipt_end_ms = int(as_of.timestamp() * 1000)
        recent_start_ms = int(cutoff.timestamp() * 1000)
        receipt_start_ms = int(receipt_start.timestamp() * 1000)
        rows = await asyncio.to_thread(
            self._db.execute_query,
            "WITH selected AS ("
            "SELECT id, stock_code, trade_time, price, volume, turnover, direction, sequence "
            "FROM ticker_data WHERE timestamp BETWEEN ? AND ? AND direction IN ('BUY','SELL') "
            "UNION "
            "SELECT id, stock_code, trade_time, price, volume, turnover, direction, sequence "
            "FROM ticker_data WHERE timestamp BETWEEN ? AND ? AND turnover>=? "
            "AND direction IN ('BUY','SELL')) "
            "SELECT id, stock_code, trade_time, price, volume, turnover, direction, sequence "
            "FROM selected ORDER BY id LIMIT ?",
            (
                recent_start_ms,
                receipt_end_ms,
                receipt_start_ms,
                receipt_end_ms,
                threshold,
                self._row_limit + 1,
            ),
        )
        if len(rows) > self._row_limit:
            raise TickerReplayLimitExceeded(f"V2 ticker replay exceeds {self._row_limit} rows")
        selected: list[tuple[datetime, int, dict]] = []
        for row in rows:
            stock_code = str(row[1])
            trade_time = market_datetime(row[2], stock_code)
            market_now = market_datetime(as_of, stock_code)
            if trade_time is None or market_now is None:
                continue
            market_open = market_now.replace(hour=0, minute=0, second=0, microsecond=0)
            turnover = float(row[5] or 0.0)
            if not market_open <= trade_time <= market_now:
                continue
            if trade_time < cutoff.astimezone(trade_time.tzinfo) and turnover < threshold:
                continue
            selected.append((
                trade_time,
                int(row[0]),
                {
                    "stock_code": stock_code,
                    "time": trade_time.isoformat(),
                    "price": row[3],
                    "volume": row[4],
                    "turnover": row[5],
                    "direction": row[6],
                    # Futu sequence restarts across requests and is not a stable replay key.
                    "sequence": None,
                },
            ))
        selected.sort(key=lambda item: (item[0], item[1]))
        if len(selected) > self._row_limit:
            raise TickerReplayLimitExceeded(f"V2 ticker replay exceeds {self._row_limit} rows")
        return tuple(item[2] for item in selected)
