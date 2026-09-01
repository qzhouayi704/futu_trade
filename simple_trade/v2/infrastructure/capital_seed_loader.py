"""Restore the latest persisted tick-capital snapshot into typed V2 facts."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ...database.core.db_manager import DatabaseManager

from ..domain.enums import DataQuality
from ..domain.market import TickAggregate


class CapitalSeedDatabasePort(Protocol):
    def execute_query(self, query: str, params: tuple | None = None) -> list: ...


class CapitalSeedLoader:
    def __init__(
        self,
        db: "DatabaseManager | CapitalSeedDatabasePort",
        *,
        window_seconds: int = 600,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._db = db
        self._window_seconds = window_seconds

    async def load(self, trade_date: str) -> tuple[TickAggregate, ...]:
        rows = await asyncio.to_thread(
            self._db.execute_query,
            "SELECT stock_code, timestamp, window_main_net, super_large_buy, "
            "super_large_sell, large_buy, large_sell, big_order_buy_ratio, "
            "cum_main_net, cum_peak, cum_trough, big_buy_count, big_sell_count, "
            "last_seq FROM tick_capital_flow WHERE id IN ("
            "SELECT MAX(id) FROM tick_capital_flow WHERE trade_date=? GROUP BY stock_code)",
            (trade_date,),
        )
        return tuple(self._from_row(row) for row in rows)

    def _from_row(self, row: tuple) -> TickAggregate:
        as_of = self._parse_time(row[1])
        window_net = float(row[2] or 0.0)
        total_buy = float(row[3] or 0.0) + float(row[5] or 0.0)
        total_sell = float(row[4] or 0.0) + float(row[6] or 0.0)
        buy_count = int(row[11] or 0)
        sell_count = int(row[12] or 0)
        last_sequence = int(row[13] or 0) or None
        ratio = float(row[7]) if row[7] is not None else None
        if ratio is None and total_buy + total_sell > 0:
            ratio = total_buy / (total_buy + total_sell)
        return TickAggregate(
            stock_code=str(row[0]),
            as_of=as_of,
            window_seconds=self._window_seconds,
            buy_amount=max(window_net, 0.0),
            sell_amount=max(-window_net, 0.0),
            main_net=window_net,
            big_buy_count=buy_count,
            big_sell_count=sell_count,
            independent_buy_events=buy_count,
            independent_sell_events=sell_count,
            buy_sell_ratio=ratio,
            cumulative_main_net=float(row[8] or 0.0),
            cumulative_peak=float(row[9] or 0.0),
            cumulative_trough=float(row[10] or 0.0),
            last_sequence=last_sequence,
            sample_count=buy_count + sell_count,
            quality=DataQuality.DEGRADED,
        )

    @staticmethod
    def _parse_time(value: object) -> datetime:
        hk_tz = timezone(timedelta(hours=8))
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(str(value).replace("T", " ", 1))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=hk_tz)
        return parsed
