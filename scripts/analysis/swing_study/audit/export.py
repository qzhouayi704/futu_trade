"""Bounded summary export; no market subscription, API request or DB writes."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import gzip
import json
import sqlite3
import sys
import time


START = '2026-06-15'
END = '2026-09-24'


def main() -> None:
    conn = sqlite3.connect('file:/data/futu_trade_data/trade.db?mode=ro',uri=True,timeout=5)
    conn.execute('PRAGMA query_only=ON')
    began = time.monotonic()
    conn.set_progress_handler(lambda:time.monotonic()-began > 120,10000)
    conn.execute('BEGIN')
    names = dict(conn.execute("SELECT code,name FROM stocks WHERE market='HK'"))
    regular = "((minute>='09:30' AND minute<'12:00') OR (minute>='13:00' AND minute<'16:00'))"
    valid = '(price>0 AND high>=low AND low>0 AND price>=low-0.00000001 AND price<=high+0.00000001 AND volume>=0)'
    coverage = list(conn.execute(
        'SELECT stock_code,trade_date,COUNT(*),GROUP_CONCAT(CASE WHEN '+regular+' AND '+valid+' THEN minute END),'
        'SUM(volume),SUM(CASE WHEN '+regular+' THEN volume ELSE 0 END),'
        'SUM(CASE WHEN NOT '+valid+' OR price IS NULL OR high IS NULL OR low IS NULL THEN 1 ELSE 0 END),'
        'MIN(low),MAX(high) FROM ticker_minute WHERE trade_date>=? AND trade_date<? '
        "AND stock_code LIKE 'HK.%' GROUP BY stock_code,trade_date ORDER BY stock_code,trade_date",(START,END)))
    if len(coverage) > 100000:
        raise ValueError('stock-day export limit')
    daily = list(conn.execute(
        'SELECT stock_code,time_key,close_price,high_price,low_price,volume,turnover,created_at FROM kline_data '
        "WHERE stock_code LIKE 'HK.%' AND time_key>='2026-05-01' AND time_key<? ORDER BY stock_code,time_key,id",(END,)))
    if len(daily) > 350000:
        raise ValueError('daily export limit')
    memberships = list(conn.execute(
        'SELECT s.code,p.plate_name,p.plate_code,sp.created_at,p.created_at,p.updated_at,p.is_target,p.is_enabled '
        'FROM stock_plates sp JOIN stocks s ON s.id=sp.stock_id JOIN plates p ON p.id=sp.plate_id '
        "WHERE s.market='HK' ORDER BY s.code,p.plate_name"))
    archives = list(conn.execute('SELECT trade_date,ticker_version,capital_version,ticker_source_max_id,'
                                 'capital_source_max_id,updated_at FROM ticker_minute_archive_meta '
                                 'WHERE trade_date>=? AND trade_date<? ORDER BY trade_date',(START,END)))
    candidates = []
    event_counts = Counter()
    for kind,code,exchange,received,state,created,source,raw in conn.execute(
        'SELECT event_type,stock_code,exchange_time,received_time,new_state,created_at,source,payload_json '
        "FROM v2_decision_events WHERE exchange_time>=? AND exchange_time<? AND stock_code LIKE 'HK.%' "
        "AND event_type IN ('CANDIDATE_ENTERED','CANDIDATE_UPDATED','BUY_CONFIRMED') ORDER BY exchange_time,id",(START,END)):
        p = json.loads(raw)
        fs = p.get('feature_snapshot') or {}
        quote = fs.get('quote') or {}
        sector = (fs.get('market_context') or {}).get('sector_code') or quote.get('sector_code') or ''
        event_counts[(exchange[:10],kind)] += 1
        candidates.append([code,exchange,received,state,kind,sector,created,source,
                           quote.get('volume'),quote.get('turnover')])
        if len(candidates) > 25000:
            raise ValueError('candidate bound')
    # Old signal tables are reported independently; no relabeling as V2 events.
    legacy = []
    legacy_keys = Counter()
    legacy_themed = 0
    legacy_samples = []
    legacy_count = 0
    for day,code,source,action,stamp,created,raw in conn.execute(
        'SELECT trade_date,stock_code,source,final_action,timestamp,created_at,raw_detail FROM signal_pipeline '
        "WHERE trade_date>=? AND trade_date<? AND stock_code LIKE 'HK.%' ORDER BY trade_date,id",(START,END)):
        legacy.append([day,code,source,action,stamp,created])
        legacy_count += 1
        if legacy_count > 200000:
            raise ValueError('legacy bound')
        try:
            detail = json.loads(raw or '{}')
        except (ValueError,TypeError):
            detail = {}
        if isinstance(detail,dict):
            legacy_keys.update(detail.keys())
            legacy_themed += any(detail.get(key) for key in ('sector','sector_code','sector_name','plate','plate_name','plate_code','feature_snapshot','universe'))
            if len(legacy_samples) < 8 and day < '2026-09-01':
                legacy_samples.append([day,code,source,detail])
    old_entry = list(conn.execute('SELECT trade_date,stock_code,time,light,label,created_at FROM entry_timing_signals '
                                  "WHERE trade_date>=? AND trade_date<? AND stock_code LIKE 'HK.%'",(START,END)))
    raw_days = list(conn.execute('SELECT trade_date,COUNT(*),COUNT(DISTINCT stock_code),MAX(id) FROM ticker_data '
                                'WHERE trade_date>=? AND trade_date<? GROUP BY trade_date',('2026-09-17',END)))
    # Narrow verification, identical trade-time and cross-date dedup semantics to the archiver.
    raw_focus = []
    for code in ('HK.00699','HK.00100','HK.03317'):
        raw_focus.extend([code,*row] for row in conn.execute(
            "WITH ranked AS (SELECT price,volume,direction,trade_time,"
            "substr(replace(trade_time,'T',' '),12,5) m,date(trade_time) d,"
            "ROW_NUMBER() OVER(PARTITION BY stock_code,trade_time,price,volume,direction "
            "ORDER BY CASE WHEN trade_date=date(trade_time) THEN 0 ELSE 1 END,id) rn "
            "FROM ticker_data WHERE stock_code=? AND date(trade_time)>='2026-09-17' AND date(trade_time)<?) "
            "SELECT d,m,COUNT(*),SUM(volume) FROM ranked WHERE rn=1 GROUP BY d,m ORDER BY d,m",(code,END)))
    inventory = []
    for table,col in [('entry_timing_signals','trade_date'),('signal_pipeline','trade_date'),
                      ('capital_flow_signals','created_at'),('trade_signals','created_at'),
                      ('daily_active_stocks','check_date'),('kline_5min_data','time_key'),
                      ('rt_data','trade_date'),('subscription_snapshot','updated_at')]:
        inventory.append([table,*conn.execute('SELECT MIN('+col+'),MAX('+col+'),COUNT(*) FROM '+table).fetchone()])
    daily_active = list(conn.execute('SELECT check_date,COUNT(*),SUM(is_active) FROM daily_active_stocks '
                                     "WHERE check_date>=? AND check_date<? AND market='HK' GROUP BY check_date",(START,END)))
    conn.rollback()
    payload = {'schema':1,'kind':'HISTORICAL_DATA_AUDIT','source':'PRODUCTION_READ_ONLY',
               'exported_at':datetime.now(timezone.utc).isoformat(),'start':START,'end_exclusive':END,
               'names':names,'coverage':coverage,'daily':daily,'memberships':memberships,'archives':archives,
               'candidates':candidates,'v2_event_counts':[[*key,value] for key,value in sorted(event_counts.items())],
               'legacy':legacy,'legacy_detail_keys':dict(legacy_keys),'legacy_top_level_theme_count':legacy_themed,
               'legacy_samples':legacy_samples,'old_entry':old_entry,'raw_days':raw_days,'raw_focus':raw_focus,
               'inventory':inventory,'daily_active_counts':daily_active,'export_seconds':time.monotonic()-began}
    sys.stdout.buffer.write(gzip.compress(json.dumps(payload,ensure_ascii=True,allow_nan=False).encode(),mtime=0))


if __name__ == '__main__':
    main()
