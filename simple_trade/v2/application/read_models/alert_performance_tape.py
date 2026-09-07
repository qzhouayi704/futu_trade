"""Bounded stock/date queries for exact post-signal raw trade performance."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from ....utils.trade_time import market_datetime
from ...infrastructure.db_read import strict_reader


# Futu persists naive Hong Kong wall time; older rows may include an offset.
HK_TRADE_JD = (
    "CASE WHEN substr(t.trade_time,-6,1) IN ('+','-') "
    "OR upper(substr(t.trade_time,-1))='Z' THEN julianday(t.trade_time) "
    "ELSE julianday(t.trade_time,'-8 hours') END"
)


@dataclass(frozen=True, slots=True)
class TapePerformance:
    last_price: float
    high_price: float
    low_price: float
    first_time: str
    last_time: str
    sample_count: int


class AlertPerformanceTapeReader:
    BATCH_SIZE = 20

    def __init__(self, db) -> None:
        self._db = strict_reader(db)

    async def read(self, alerts: list[dict], as_of: datetime) -> dict[str, TapePerformance]:
        requests = []
        for alert in alerts:
            code = alert["stock_code"]
            start = market_datetime(alert["signal_time"], code)
            if not code.startswith("HK.") or start is None or start > as_of:
                continue
            end = min(as_of, start.replace(hour=23, minute=59, second=59, microsecond=999999))
            requests.append((
                alert["event_id"], code, start.isoformat(), end.isoformat(),
                (start.date() - timedelta(days=1)).isoformat(),
                (start.date() + timedelta(days=1)).isoformat(),
            ))
        result = {}
        for offset in range(0, len(requests), self.BATCH_SIZE):
            batch = requests[offset:offset + self.BATCH_SIZE]
            placeholders = ",".join("(?,?,?,?,?,?)" for _ in batch)
            query = (
                "WITH bounds(event_id,code,start_at,end_at,first_day,last_day) AS "
                f"(VALUES {placeholders}), tape AS ("
                "SELECT b.event_id,t.price,t.trade_time,"
                "ROW_NUMBER() OVER (PARTITION BY b.event_id ORDER BY "
                f"{HK_TRADE_JD},t.id) AS first_rank,"
                "ROW_NUMBER() OVER (PARTITION BY b.event_id ORDER BY "
                f"{HK_TRADE_JD} DESC,t.id DESC) AS last_rank "
                "FROM bounds b JOIN ticker_data t ON t.stock_code=b.code "
                "AND t.trade_date BETWEEN b.first_day AND b.last_day "
                f"WHERE t.price>0 AND {HK_TRADE_JD}>=julianday(b.start_at) "
                f"AND {HK_TRADE_JD}<=julianday(b.end_at)) "
                "SELECT event_id,MAX(CASE WHEN last_rank=1 THEN price END),"
                "MAX(price),MIN(price),MAX(CASE WHEN first_rank=1 THEN trade_time END),"
                "MAX(CASE WHEN last_rank=1 THEN trade_time END),COUNT(*) "
                "FROM tape GROUP BY event_id"
            )
            params = tuple(value for request in batch for value in request)
            rows = await asyncio.to_thread(self._db.execute_query, query, params)
            for row in rows:
                first = market_datetime(row[4])
                last = market_datetime(row[5])
                if first is None or last is None:
                    continue
                result[str(row[0])] = TapePerformance(
                    last_price=float(row[1]), high_price=float(row[2]), low_price=float(row[3]),
                    first_time=first.isoformat(), last_time=last.isoformat(), sample_count=int(row[6]),
                )
        return result
