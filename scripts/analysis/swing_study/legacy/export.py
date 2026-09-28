"""Bounded SQLite read transaction; no subscriptions or production mutations."""
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
import sqlite3
import sys
import time


def main() -> None:
    conn = sqlite3.connect('file:/data/futu_trade_data/trade.db?mode=ro', uri=True, timeout=5)
    conn.execute('PRAGMA query_only=ON')
    started = time.monotonic()
    conn.set_progress_handler(lambda: time.monotonic()-started > 120, 10000)
    conn.execute('BEGIN')
    events = []
    codes: set[str] = set()
    for row in conn.execute(
        'SELECT id,trade_date,stock_code,source,final_action,timestamp,created_at,raw_detail '
        "FROM signal_pipeline WHERE trade_date>='2026-07-14' AND trade_date<'2026-09-24' "
        "AND source='capital_trend' AND stock_code LIKE 'HK.%' ORDER BY trade_date,id"):
        detail = json.loads(row[-1] or '{}')
        label = str(detail.get('plate_name') or '')
        # Broad evidence export; exact theme classification occurs locally at event time.
        if label:
            codes.add(row[2])
        events.append([*row[:-1], detail])
        if len(events) > 100000:
            raise ValueError('event bound exceeded')
    # Keep unlabeled follow-up/terminal records for the same stocks, not just favorable labels.
    events = [row for row in events if row[2] in codes]
    if len(codes) > 250:
        raise ValueError('stock bound exceeded')
    minutes, daily = [], []
    for code in sorted(codes):
        minutes.extend([code, *r] for r in conn.execute(
            'SELECT trade_date,minute,price,high,low,buy_amt,sell_amt,volume FROM ticker_minute '
            "WHERE stock_code=? AND trade_date>='2026-07-14' AND trade_date<'2026-09-24' "
            'ORDER BY trade_date,minute', (code,)))
        daily.extend([code, *r] for r in conn.execute(
            'SELECT time_key,close_price,high_price,low_price,volume,turnover,created_at,id '
            "FROM kline_data WHERE stock_code=? AND time_key>='2026-05-01' AND time_key<'2026-09-24' "
            'ORDER BY time_key,id', (code,)))
        if len(minutes) > 2000000 or len(daily) > 100000:
            raise ValueError('price row bound exceeded')
    archives = list(conn.execute(
        'SELECT trade_date,ticker_version,capital_version FROM ticker_minute_archive_meta '
        "WHERE trade_date>='2026-07-14' AND trade_date<'2026-09-24' ORDER BY trade_date"))
    names = dict(conn.execute("SELECT code,name FROM stocks WHERE market='HK'"))
    conn.rollback()
    data = {'schema': 1, 'kind': 'LEGACY_SWING_DATA', 'source': 'PRODUCTION_READ_ONLY',
            'exported_at': datetime.now(timezone.utc).isoformat(), 'events': events,
            'minutes': minutes, 'daily': daily, 'archives': archives,
            'names': {code: names.get(code, '') for code in codes},
            'minute_semantics': 'ARITHMETIC_MEAN_OF_TRADES_NOT_CLOSE',
            'source_counts': dict(Counter(row[3] for row in events))}
    sys.stdout.buffer.write(gzip.compress(json.dumps(data, ensure_ascii=True, allow_nan=False).encode(), mtime=0))


if __name__ == '__main__':
    main()
