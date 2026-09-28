"""Bounded, read-only production export; executable over SSH stdin."""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import json
import re
import sqlite3
import sys
import time


def main() -> None:
    conn = sqlite3.connect('file:/data/futu_trade_data/trade.db?mode=ro', uri=True, timeout=5)
    conn.execute('PRAGMA query_only=ON')
    began = time.monotonic()
    conn.set_progress_handler(lambda: time.monotonic()-began > 120, 10000)
    conn.execute('BEGIN')
    names = dict(conn.execute("SELECT code,name FROM stocks WHERE market='HK'"))
    exclude = re.compile(r'ETF|Global\s*X|两倍|三倍|反向|盈富基金|安硕|南方恒|恒生指数|华夏恒生', re.I)
    events = []
    for eid, kind, code, exchange, received, state, version, raw in conn.execute(
        "SELECT event_id,event_type,stock_code,exchange_time,received_time,new_state,strategy_version,payload_json "
        "FROM v2_decision_events WHERE exchange_time>='2026-09-01' AND exchange_time<'2026-09-24' "
        "AND event_type IN ('CANDIDATE_ENTERED','CANDIDATE_UPDATED','BUY_CONFIRMED') ORDER BY exchange_time,id"
    ):
        if not re.fullmatch(r'HK\.\d{5}', code) or int(code[3:]) >= 10000 or exclude.search(names.get(code,'')):
            continue
        payload = json.loads(raw)
        fs = payload.get('feature_snapshot') or {}
        quote = fs.get('quote') or {}
        market = fs.get('market_context') or {}
        position = fs.get('price_position') or {}
        if not quote.get('last_price') or state not in {'SETUP','WATCHING','CONFIRMED'}:
            continue
        events.append([eid,kind,code,exchange,received,state,version,payload.get('alert_eligible') is True,
                       quote['last_price'],quote.get('prev_close'),
                       market.get('sector_code') or quote.get('sector_code') or '',
                       position.get('daily_percentile'),position.get('atr_percent')])
        if len(events) > 25000:
            raise ValueError('event bound exceeded')
    codes = sorted({row[2] for row in events})
    minutes, daily = [], []
    for code in codes:
        # All subsequent dates, even when the stock never re-entered the candidate pool.
        minutes.extend([code,*row] for row in conn.execute(
            'SELECT trade_date,minute,price,high,low,buy_amt,sell_amt,volume FROM ticker_minute '
            "WHERE stock_code=? AND trade_date>='2026-09-01' AND trade_date<'2026-09-24' ORDER BY trade_date,minute",(code,)))
        daily.extend([code,*row] for row in conn.execute(
            'SELECT time_key,open_price,close_price,high_price,low_price,turnover,created_at,id FROM kline_data '
            "WHERE stock_code=? AND time_key>='2026-05-01' AND time_key<'2026-09-24' ORDER BY time_key,id",(code,)))
        if len(minutes) > 2500000:
            raise ValueError('minute bound exceeded')
    archives = list(conn.execute("SELECT trade_date,ticker_version,capital_version FROM ticker_minute_archive_meta "
                                 "WHERE trade_date>='2026-09-01' AND trade_date<'2026-09-24' ORDER BY trade_date"))
    conn.rollback()
    data = {'schema':1,'source':'PRODUCTION_READ_ONLY','exported_at':datetime.now(timezone.utc).isoformat(),
            'start':'2026-09-01','end_exclusive':'2026-09-24','names':{code:names.get(code,'') for code in codes},
            'events':events,'minutes':minutes,'daily':daily,'archives':archives,
            'minute_semantics':'ARITHMETIC_MEAN_OF_TRADES_NOT_CLOSE'}
    sys.stdout.buffer.write(gzip.compress(json.dumps(data,ensure_ascii=True,allow_nan=False).encode(),mtime=0))


if __name__ == '__main__':
    main()
