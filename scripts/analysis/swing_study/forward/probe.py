"""Small, deadline-bounded read-only production evidence inventory over SSH."""
from datetime import datetime, timedelta, timezone
import gzip
import json
import sqlite3
import sys
import time


def main() -> None:
    now = datetime.now(timezone(timedelta(hours=8)))
    conn = sqlite3.connect('file:/data/futu_trade_data/trade.db?mode=ro', uri=True, timeout=5)
    conn.execute('PRAGMA query_only=ON')
    started = time.monotonic()
    conn.set_progress_handler(lambda: time.monotonic()-started > 30, 10000)
    conn.execute('BEGIN')
    archives = list(conn.execute(
        'SELECT trade_date,ticker_version,capital_version,updated_at FROM ticker_minute_archive_meta '
        "WHERE trade_date>='2026-09-23' ORDER BY trade_date LIMIT 150"))
    minute_days = list(conn.execute(
        'SELECT trade_date,COUNT(*),COUNT(DISTINCT stock_code),MAX(minute) FROM ticker_minute '
        "WHERE trade_date>='2026-09-23' AND stock_code LIKE 'HK.%' GROUP BY trade_date ORDER BY trade_date LIMIT 150"))
    raw_latest = conn.execute('SELECT trade_date,trade_time FROM ticker_data ORDER BY id DESC LIMIT 1').fetchone()
    signals = list(conn.execute(
        'SELECT trade_date,source,COUNT(*),MAX(timestamp) FROM signal_pipeline '
        "WHERE trade_date>='2026-09-23' AND source='capital_trend' AND stock_code LIKE 'HK.%' "
        'GROUP BY trade_date,source ORDER BY trade_date LIMIT 150'))
    snapshots = conn.execute('SELECT COUNT(*),MAX(updated_at) FROM subscription_snapshot').fetchone()
    five_minutes = conn.execute('SELECT COUNT(*),MAX(time_key) FROM kline_5min_data').fetchone()
    v2 = conn.execute(
        'SELECT MAX(exchange_time),MAX(received_time) FROM v2_decision_events '
        "WHERE exchange_time>='2026-09-23' AND stock_code LIKE 'HK.%'").fetchone()
    conn.rollback()
    data = {'schema': 1, 'kind': 'FORWARD_READINESS_PROBE', 'source': 'PRODUCTION_SQLITE_READ_ONLY',
            'observed_at': now.isoformat(), 'archives': archives, 'minute_days': minute_days,
            'raw_latest_inserted': raw_latest, 'legacy_days': signals, 'v2_latest': v2,
            'subscription_snapshot': snapshots, 'five_minute_cache': five_minutes,
            'read_only': True, 'elapsed_seconds': time.monotonic()-started,
            'limitations': ['date metadata and any archived rows do not certify stock-path completeness',
                            'latest inserted raw tick may not be the latest exchange timestamp',
                            'no broker API, environment, service startup or configuration inspected or changed']}
    sys.stdout.buffer.write(gzip.compress(json.dumps(data, ensure_ascii=True, allow_nan=False).encode(), mtime=0))


if __name__ == '__main__':
    main()
