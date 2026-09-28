"""Supplementary event-time theme evidence found in the legacy pipeline."""
import gzip
import json
import sqlite3
import sys
import time
from datetime import datetime,timezone


def main() -> None:
    c = sqlite3.connect('file:/data/futu_trade_data/trade.db?mode=ro',uri=True,timeout=5)
    c.execute('PRAGMA query_only=ON')
    began = time.monotonic()
    c.set_progress_handler(lambda:time.monotonic()-began > 60,10000)
    rows = []
    scanned = 0
    for eid,day,code,source,action,when,created,raw in c.execute(
        'SELECT id,trade_date,stock_code,source,final_action,timestamp,created_at,raw_detail FROM signal_pipeline '
        "WHERE trade_date>='2026-06-15' AND trade_date<'2026-09-24' AND stock_code LIKE 'HK.%' ORDER BY trade_date,id"):
        scanned += 1
        if scanned > 200000:
            raise ValueError('scan bound exceeded')
        try:
            detail = json.loads(raw or '{}')
        except (ValueError,TypeError):
            continue
        if not isinstance(detail,dict):
            continue
        label = detail.get('plate_name') or detail.get('sector_code') or detail.get('sector_name')
        if label:
            rows.append([eid,day,code,source,action,when,created,str(label),detail])
    payload = {'schema':1,'kind':'LEGACY_THEME_EVIDENCE','source':'PRODUCTION_READ_ONLY',
               'exported_at':datetime.now(timezone.utc).isoformat(),'scanned':scanned,'theme_events':rows}
    sys.stdout.buffer.write(gzip.compress(json.dumps(payload,ensure_ascii=True,allow_nan=False).encode(),mtime=0))


if __name__ == '__main__':
    main()
