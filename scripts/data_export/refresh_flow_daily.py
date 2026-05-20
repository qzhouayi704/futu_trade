#!/usr/bin/env python3
"""快速刷新 capital_flow_daily - 1秒间隔 + 限流自动重试"""

import sqlite3
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, '.')

db_path = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'
conn = sqlite3.connect(db_path)

from futu import OpenQuoteContext, RET_OK
from simple_trade.utils.converters import safe_float

# Get stocks that still need data (skip ones already refreshed by quick test)
cur = conn.execute("SELECT DISTINCT stock_code FROM kline_data")
all_codes = [r[0] for r in cur.fetchall()]

# Skip stocks already with good data
cur = conn.execute("""
    SELECT DISTINCT stock_code FROM capital_flow_daily 
    WHERE net_inflow_ratio NOT IN (-0.5, 0.5, 0)
""")
done_codes = set(r[0] for r in cur.fetchall())
remaining = [c for c in all_codes if c not in done_codes]
print(f"Total: {len(all_codes)} | Already done: {len(done_codes)} | Remaining: {len(remaining)}", flush=True)

ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
print("Connected", flush=True)

end_date = date.today().strftime('%Y-%m-%d')
start_date = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')

success = 0
failed = 0
total_rows = 0

for i, stock_code in enumerate(remaining):
    retries = 0
    while retries < 3:
        try:
            ret, data = ctx.get_capital_flow(stock_code, period_type='DAY', start=start_date, end=end_date)
            if ret == RET_OK and data is not None and len(data) > 0:
                for _, row in data.iterrows():
                    flow_time = str(row.get('capital_flow_item_time', ''))[:10]
                    main_net = safe_float(row.get('main_in_flow'))
                    mid_net = safe_float(row.get('mid_in_flow'))
                    sml_net = safe_float(row.get('sml_in_flow'))
                    net_inflow = safe_float(row.get('in_flow'))
                    total_abs = abs(main_net) + abs(mid_net) + abs(sml_net)
                    ratio = main_net / total_abs if total_abs > 0 else 0
                    if flow_time:
                        conn.execute("""
                            INSERT OR REPLACE INTO capital_flow_daily
                            (stock_code, date, net_inflow, net_inflow_ratio)
                            VALUES (?, ?, ?, ?)
                        """, (stock_code, flow_time, net_inflow, ratio))
                        total_rows += 1
                conn.commit()
                success += 1
                break
            elif 'frequency' in str(ret).lower() or 'limit' in str(ret).lower():
                retries += 1
                time.sleep(5)
            else:
                failed += 1
                break
        except Exception as e:
            if 'frequency' in str(e).lower() or 'limit' in str(e).lower():
                retries += 1
                time.sleep(5)
            else:
                failed += 1
                break

    if (i + 1) % 20 == 0:
        print(f"  [{i+1}/{len(remaining)}] ok={success} fail={failed} rows={total_rows}", flush=True)
    time.sleep(1)

ctx.close()
conn.close()

print(f"\nDone! ok={success} fail={failed} rows={total_rows}", flush=True)
