"""Executed over the existing SSH transport; bounded read-only SELECTs only."""
from datetime import datetime, timedelta, timezone
import gzip
import json
import sqlite3
import sys
import time


CODES = ('HK.00100', 'HK.00699', 'HK.03317')
TABLES = ('signal_pipeline', 'ticker_data', 'ticker_minute', 'kline_data', 'subscription_snapshot')


def snapshot(connection: sqlite3.Connection, now: datetime) -> dict:
    connection.execute('PRAGMA query_only=ON')
    started = time.monotonic()
    connection.set_progress_handler(lambda: time.monotonic()-started > 25, 10000)
    start = max('2026-09-24', (now.date()-timedelta(days=14)).isoformat())
    end = now.date().isoformat()
    connection.execute('BEGIN')
    try:
        columns = {table: [r[1] for r in connection.execute(f'PRAGMA table_info({table})')] for table in TABLES}
        signals = list(connection.execute(
            'SELECT id,trade_date,stock_code,source,final_action,timestamp,created_at,raw_detail '
            "FROM signal_pipeline WHERE source='capital_trend' AND stock_code IN (?,?,?) "
            'AND trade_date BETWEEN ? AND ? ORDER BY id LIMIT 5001', (*CODES, start, end)))
        if len(signals) > 5000:
            raise ValueError('signal row bound exceeded; not exporting partial evidence')
        minutes = list(connection.execute(
            'SELECT stock_code,trade_date,COUNT(*),MIN(minute),MAX(minute) FROM ticker_minute '
            'WHERE stock_code IN (?,?,?) AND trade_date BETWEEN ? AND ? '
            "AND ((minute>='09:30' AND minute<'12:00') OR (minute>='13:00' AND minute<'16:00')) "
            'GROUP BY stock_code,trade_date ORDER BY stock_code,trade_date', (*CODES, start, end)))
        ticks, daily = [], []
        for code in CODES:
            ticks.extend(connection.execute(
                'SELECT id,stock_code,trade_date,trade_time,timestamp,created_at,sequence FROM ticker_data '
                'WHERE stock_code=? AND trade_date BETWEEN ? AND ? ORDER BY id DESC LIMIT 200', (code, start, end)))
            daily.extend(connection.execute(
                'SELECT id,stock_code,time_key,created_at FROM kline_data '
                'WHERE stock_code=? AND time_key<? ORDER BY time_key DESC LIMIT 22', (code, end)))
        subscriptions = connection.execute('SELECT COUNT(*) FROM subscription_snapshot').fetchone()[0]
    finally:
        connection.rollback()
    return {'schema': 1, 'kind': 'FORWARD_SOURCE_INTAKE', 'source': 'PRODUCTION_SQLITE_READ_ONLY',
        'scope': 'FOCUS_CODES_ONLY', 'observed_at': now.isoformat(), 'start_date': start, 'end_date': end,
        'codes': CODES, 'columns': columns, 'signals': signals, 'ticks': ticks, 'minutes': minutes,
        'daily': daily, 'subscription_snapshot_rows': subscriptions, 'read_only': True, 'truncated': False,
        'tick_sample_limit_per_code': 200, 'tick_sample_complete_history': False,
        'daily_sample_limit_per_code': 22, 'elapsed_seconds': time.monotonic()-started}


def main() -> None:
    connection = sqlite3.connect('file:/data/futu_trade_data/trade.db?mode=ro', uri=True, timeout=3)
    try:
        data = snapshot(connection, datetime.now(timezone(timedelta(hours=8))))
    finally:
        connection.close()
    raw = json.dumps(data, ensure_ascii=True, allow_nan=False).encode()
    if len(raw) > 8*1024*1024:
        raise ValueError('source byte bound exceeded')
    sys.stdout.buffer.write(gzip.compress(raw, mtime=0))


if __name__ == '__main__':
    main()
