#!/usr/bin/env python3
"""用富途API调取资金流数据，对比数据库中的错误值"""

import sys
sys.path.insert(0, '.')

from futu import OpenQuoteContext, RET_OK
from datetime import date, timedelta

# Connect to Futu
ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

# Test with a few stocks from our backtest
test_stocks = ['HK.03738', 'HK.06681', 'HK.02617', 'HK.03317', 'HK.01384']

end_date = date.today().strftime('%Y-%m-%d')
start_date = (date.today() - timedelta(days=10)).strftime('%Y-%m-%d')

print(f"=== 富途API get_capital_flow (DAY) {start_date} ~ {end_date} ===\n")

for stock_code in test_stocks:
    ret, data = ctx.get_capital_flow(stock_code, period_type='DAY', start=start_date, end=end_date)
    if ret == RET_OK and data is not None and len(data) > 0:
        print(f"--- {stock_code} ---")
        print(f"  Columns: {list(data.columns)}")
        for _, row in data.iterrows():
            flow_time = row.get('capital_flow_item_time', '')
            in_flow = row.get('in_flow', 0)  # 总净流入
            main_in = row.get('main_in_flow', 0)  # 主力净流入
            super_in = row.get('super_in_flow', 0)
            big_in = row.get('big_in_flow', 0)
            mid_in = row.get('mid_in_flow', 0)
            sml_in = row.get('sml_in_flow', 0)
            # 计算真实 ratio: 主力净流入 / (|主力净流入| + |中小单净流入|)
            total_abs = abs(main_in) + abs(mid_in) + abs(sml_in)
            real_ratio = main_in / total_abs if total_abs > 0 else 0
            print(f"  {flow_time[:10]} | in_flow={in_flow:>12.0f} | main={main_in:>12.0f} | "
                  f"super={super_in:>10.0f} | big={big_in:>10.0f} | mid={mid_in:>10.0f} | sml={sml_in:>10.0f} | "
                  f"real_ratio={real_ratio:>6.3f}")
        print()
    else:
        print(f"--- {stock_code}: FAILED (ret={ret}) ---\n")

ctx.close()
