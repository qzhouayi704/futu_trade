"""Authorized aggregate-only HK legacy stage inventory; never exports rows/codes."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import gzip
import json
import sqlite3
import sys
import time


HK = timezone(timedelta(hours=8))
MAX_GROUPS = 300
STAGES = ('FIRST', 'CONFIRMED', 'STRENGTHENED', 'SECOND_WATCH', 'INVALIDATED',
          'EXPIRED', 'REJECTED', 'TRAIL_EXIT', 'WATCH_TRAIL_EXIT')


@dataclass(frozen=True)
class StageCount:
    trade_date: str
    stage: str
    event_count: int
    stock_count: int


@dataclass(frozen=True)
class StageProbe:
    observed_at: str
    start_date: str
    end_date: str
    counts: tuple[StageCount, ...]
    elapsed_seconds: float
    schema: int = 1
    kind: str = 'HK_LEGACY_STAGE_AGGREGATES'
    source: str = 'PRODUCTION_SQLITE_READ_ONLY'
    scope: str = 'DATABASE_HK_CAPITAL_TREND_DATE_STAGE_COUNTS_ONLY'
    read_only: bool = True
    truncated: bool = False
    individual_records_exported: bool = False
    all_listed_stocks_coverage_certified: bool = False


def snapshot(connection: sqlite3.Connection, now: datetime) -> StageProbe:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('aware snapshot time required')
    now = now.astimezone(HK)
    start = max('2026-09-24', (now.date()-timedelta(days=14)).isoformat())
    end = now.date().isoformat()
    if end < start:
        raise ValueError('snapshot precedes approved date window')
    connection.execute('PRAGMA query_only=ON')
    started = time.monotonic()
    connection.set_progress_handler(lambda: time.monotonic()-started > 25, 10000)
    connection.execute('BEGIN')
    try:
        # Classify inside SQLite: no stock code, raw JSON, price or individual ID
        # can cross the transport boundary, including malformed/free-text stages.
        rows = connection.execute(
            "WITH scoped AS (SELECT trade_date,stock_code,json_valid(raw_detail) AS valid, "
            "json_extract(CASE WHEN json_valid(raw_detail) THEN raw_detail ELSE '{}' END, '$.inflow_stage') AS stage "
            "FROM signal_pipeline WHERE source='capital_trend' AND stock_code LIKE 'HK.%' "
            "AND trade_date BETWEEN ? AND ?), classified AS (SELECT trade_date,stock_code, "
            "CASE WHEN COALESCE(valid,0)=0 THEN 'INVALID_JSON' WHEN stage IS NULL THEN 'NO_STAGE' "
            "WHEN typeof(stage)<>'text' THEN 'INVALID_STAGE_TYPE' WHEN trim(stage)='' THEN 'NO_STAGE' "
            f"WHEN stage IN ({','.join('?' for _ in STAGES)}) THEN stage ELSE 'OTHER_STAGE' END AS stage "
            'FROM scoped) SELECT trade_date,stage,COUNT(*),COUNT(DISTINCT stock_code) FROM classified '
            'GROUP BY trade_date,stage ORDER BY trade_date,stage LIMIT ?', (start, end, *STAGES, MAX_GROUPS+1),
        ).fetchall()
        if len(rows) > MAX_GROUPS:
            raise ValueError('aggregate group bound exceeded; refusing partial counts')
        counts = tuple(StageCount(*row) for row in rows)
    finally:
        connection.rollback()
    return StageProbe(now.isoformat(), start, end, counts, time.monotonic()-started)


def main() -> None:
    connection = sqlite3.connect('file:/data/futu_trade_data/trade.db?mode=ro', uri=True, timeout=3)
    try:
        result = snapshot(connection, datetime.now(HK))
    finally:
        connection.close()
    raw = json.dumps(asdict(result), ensure_ascii=True, allow_nan=False).encode()
    if len(raw) > 128*1024:
        raise ValueError('aggregate output byte bound exceeded')
    sys.stdout.buffer.write(gzip.compress(raw, mtime=0))


if __name__ == '__main__':
    main()
