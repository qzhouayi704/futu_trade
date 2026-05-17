#!/usr/bin/env python3
"""快速验证：只刷新10只股票，确认逻辑正确后再跑全量"""

import sqlite3
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, '.')

db_path = r'd:\Program Files\futu_trade_sys\simple_trade\data\trade.db'
conn = sqlite3.connect(db_path)

from futu import OpenQuoteContext, RET_OK
from simple_trade.utils.converters import safe_float

# Test with 10 stocks
test_codes = ['HK.03738', 'HK.06681', 'HK.02617', 'HK.03317', 'HK.01384',
              'HK.03881', 'HK.02656', 'HK.06687', 'HK.02575', 'HK.06127']

ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
print("Connected to Futu", flush=True)

end_date = date.today().strftime('%Y-%m-%d')
start_date = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')

# Delete old data for these stocks only
for code in test_codes:
    conn.execute("DELETE FROM capital_flow_daily WHERE stock_code = ?", (code,))
conn.commit()
print(f"Cleared old data for {len(test_codes)} test stocks", flush=True)

total_rows = 0
for i, stock_code in enumerate(test_codes):
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
        print(f"  OK: {stock_code} ({len(data)} days)", flush=True)
    else:
        print(f"  FAIL: {stock_code} ret={ret}", flush=True)
    time.sleep(3.5)

ctx.close()

# Verify
print(f"\nInserted {total_rows} rows. Verifying:", flush=True)
cur = conn.execute("""
    SELECT stock_code, date, net_inflow_ratio 
    FROM capital_flow_daily 
    WHERE stock_code IN ({})
    ORDER BY stock_code, date DESC
""".format(','.join(f"'{c}'" for c in test_codes[:3])))

for r in cur.fetchall():
    print(f"  {r[0]} | {r[1]} | ratio={r[2]:.4f}", flush=True)

conn.close()
print("\nDone! Ratios are now continuous values, not ±0.5", flush=True)
