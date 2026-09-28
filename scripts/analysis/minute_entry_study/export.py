"""Read-only bounded export, executable through SSH stdin."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import gzip
import json
import re
import sqlite3
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2026-09-01')
    parser.add_argument('--end', default='2026-09-24')
    parser.add_argument('--db', default='/data/futu_trade_data/trade.db')
    parser.add_argument('--today-focus', action='store_true')
    args = parser.parse_args()
    now = datetime.now(timezone(timedelta(hours=8)))
    if args.today_focus:
        args.start = now.date().isoformat()
        args.end = (now.date()+timedelta(days=1)).isoformat()
    if not 0 < (date.fromisoformat(args.end) - date.fromisoformat(args.start)).days <= 31:
        raise ValueError('range must be 1..31 calendar days')
    conn = sqlite3.connect('file:' + args.db + '?mode=ro', uri=True, timeout=5)
    conn.execute('PRAGMA query_only=ON')
    began = time.monotonic()
    conn.set_progress_handler(lambda: time.monotonic() - began > 90, 10000)
    conn.execute('BEGIN')
    names = dict(conn.execute("SELECT code,name FROM stocks WHERE market='HK'"))
    excluded = re.compile(r'ETF|Global\s*X|两倍|三倍|反向|盈富基金|安硕|南方恒|恒生指数|华夏恒生', re.I)
    events = []
    keys = set()
    for eid, kind, code, exchange, received, state, reason, version, raw in conn.execute(
        "SELECT event_id,event_type,stock_code,exchange_time,received_time,new_state,"
        "reason_code,strategy_version,payload_json FROM v2_decision_events "
        "WHERE exchange_time>=? AND exchange_time<? AND event_type IN "
        "('CANDIDATE_ENTERED','CANDIDATE_UPDATED','CANDIDATE_INVALIDATED','BUY_CONFIRMED','BUY_INVALIDATED') "
        "ORDER BY exchange_time,id", (args.start, args.end)
    ):
        if not re.fullmatch(r'HK\.\d{5}', code) or int(code[3:]) >= 10000 or excluded.search(names.get(code, '')):
            continue
        if args.today_focus and code not in {'HK.00699','HK.00100'}:
            continue
        payload = json.loads(raw)
        fs = payload.get('feature_snapshot') or {}
        quote = fs.get('quote') or {}
        if not quote.get('last_price'):
            continue
        events.append([eid, kind, code, exchange, received, state, reason, version,
                       payload.get('alert_eligible') is True, fs,
                       (payload.get('universe') or {}).get('reason_codes', [])])
        keys.add((code, exchange[:10]))
        if len(events) > 25000:
            raise ValueError('event limit exceeded')
    minutes = []
    for code, day in sorted(keys):
        if args.today_focus:
            rows = conn.execute(
                "WITH ranked AS (SELECT price,volume,turnover,direction,"
                "CASE WHEN datetime(trade_time) IS NOT NULL THEN substr(replace(trade_time,'T',' '),12,5) "
                "ELSE substr(datetime(timestamp/1000,'unixepoch','+8 hours'),12,5) END m,"
                "ROW_NUMBER() OVER (PARTITION BY stock_code,CASE WHEN datetime(trade_time) IS NOT NULL "
                "THEN trade_time ELSE 'legacy:'||id END,price,volume,direction "
                "ORDER BY CASE WHEN trade_date=? THEN 0 ELSE 1 END,id) rn "
                "FROM ticker_data WHERE stock_code=? AND "
                "(date(trade_time)=? OR (date(trade_time) IS NULL AND trade_date=?))) "
                "SELECT m,AVG(price),MAX(price),MIN(price),"
                "SUM(CASE WHEN direction='BUY' THEN turnover ELSE 0 END),"
                "SUM(CASE WHEN direction='SELL' THEN turnover ELSE 0 END),SUM(volume) "
                "FROM ranked WHERE rn=1 AND m>= '09:30' AND m<? GROUP BY m ORDER BY m",
                (day,code,day,day,now.strftime('%H:%M'))).fetchall()
        else:
            rows = conn.execute(
                'SELECT minute,price,high,low,buy_amt,sell_amt,volume FROM ticker_minute '
                'WHERE stock_code=? AND trade_date=? ORDER BY minute', (code, day)).fetchall()
        minutes.extend([code, day, *row] for row in rows)
        if len(minutes) > 1000000:
            raise ValueError('minute limit exceeded')
    prior_start = (date.fromisoformat(args.start) - timedelta(days=100)).isoformat()
    daily = []
    for code in sorted({key[0] for key in keys}):
        daily.extend([code, *row] for row in conn.execute(
            'SELECT substr(time_key,1,10),close_price,high_price,low_price,turnover '
            'FROM kline_data WHERE stock_code=? AND time_key>=? AND time_key<? ORDER BY time_key,id',
            (code, prior_start, args.end)))
    archives = list(conn.execute('SELECT trade_date,ticker_version,capital_version,updated_at '
                                'FROM ticker_minute_archive_meta WHERE trade_date>=? AND trade_date<?',
                                (args.start, args.end)))
    conn.rollback()
    payload = {'schema': 1, 'origin': 'PRODUCTION_READ_ONLY', 'start': args.start, 'end': args.end,
               'exported_at': datetime.now(timezone.utc).isoformat(), 'as_of': now.isoformat(),
               'partial_day': args.today_focus,
               'minute_semantics': 'ARITHMETIC_MEAN_OF_TRADES_NOT_CLOSE',
               'event_columns': ['id','kind','code','exchange','received','state','reason','version','eligible','features','universe_reasons'],
               'minute_columns': ['code','day','minute','mean','high','low','buy','sell','volume'],
               'daily_columns': ['code','day','close','high','low','turnover'],
               'names': {code: names.get(code, '') for code, _ in keys},
               'archives': archives, 'events': events, 'minutes': minutes, 'daily': daily}
    sys.stdout.buffer.write(gzip.compress(json.dumps(payload, ensure_ascii=True, allow_nan=False).encode(), mtime=0))


if __name__ == '__main__':
    main()
