#!/usr/bin/env python3
"""只查阅文集团的完整资金流+K线"""
import sqlite3

conn = sqlite3.connect('simple_trade/data/trade.db')
conn.row_factory = sqlite3.Row

code, name = 'HK.00772', '阅文集团'

print(f"=== {code} {name} 资金流日线 (最近15天) ===")
cur = conn.execute("""
    SELECT date, net_inflow, net_inflow_ratio
    FROM capital_flow_daily
    WHERE stock_code = ?
    ORDER BY date DESC
    LIMIT 15
""", (code,))
for r in cur.fetchall():
    net = r['net_inflow'] or 0
    ratio = r['net_inflow_ratio'] or 0
    bar = '+' if net > 0 else '-'
    net_m = net / 10000
    print(f"  {r['date']} | {bar} 净流入: {net_m:>10.1f}万 | 比率: {ratio*100:>+7.2f}%")

print(f"\n=== {code} {name} 大单累积 ===")
cur = conn.execute("""
    SELECT trade_date, super_large_buy_amt, super_large_sell_amt,
           large_buy_amt, large_sell_amt
    FROM daily_order_accumulator
    WHERE stock_code = ?
    ORDER BY trade_date DESC
    LIMIT 10
""", (code,))
for r in cur.fetchall():
    sb = (r['super_large_buy_amt'] or 0) - (r['super_large_sell_amt'] or 0)
    lb = (r['large_buy_amt'] or 0) - (r['large_sell_amt'] or 0)
    main_net = sb + lb
    print(f"  {r['trade_date']} | 超大单净:{sb/10000:>10.1f}万 | 大单净:{lb/10000:>10.1f}万 | 主力合计:{main_net/10000:>10.1f}万")

print(f"\n=== {code} {name} K线走势 (最近15天) ===")
cur = conn.execute("""
    SELECT time_key, open_price, close_price, high_price, low_price,
           volume, turnover, turnover_rate
    FROM kline_data
    WHERE stock_code = ?
    ORDER BY time_key DESC
    LIMIT 15
""", (code,))
for r in cur.fetchall():
    o = r['open_price'] or 0
    c = r['close_price'] or 0
    chg = ((c - o) / o * 100) if o else 0
    bar = 'Y' if chg > 0 else 'X' if chg < 0 else '='
    vol_w = (r['volume'] or 0) / 10000
    to_w = (r['turnover'] or 0) / 10000
    print(f"  {r['time_key'][:10]} | O:{o:>7.2f} C:{c:>7.2f} H:{r['high_price']:>7.2f} L:{r['low_price']:>7.2f} | {bar} {chg:>+6.2f}% | Vol:{vol_w:>8.1f}w | TR:{r['turnover_rate'] or 0:.2f}%")

conn.close()
