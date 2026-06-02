#!/usr/bin/env python3
"""查询 HK.00772 和 HK.03888 的资金流+K线数据"""
import sqlite3

db_path = 'simple_trade/data/trade.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

stocks = [
    ('HK.00772', '阅文集团'),
    ('HK.03888', '金山软件'),
]

for code, name in stocks:
    print(f"\n{'='*70}")
    print(f"  {code} {name}")
    print(f"{'='*70}")
    
    # 1. 资金流日线
    print(f"\n  [资金流日线 - 最近15天]")
    cur = conn.execute("""
        SELECT date, net_inflow, net_inflow_ratio
        FROM capital_flow_daily
        WHERE stock_code = ?
        ORDER BY date DESC
        LIMIT 15
    """, (code,))
    flow_rows = cur.fetchall()
    if not flow_rows:
        print("  No capital flow data")
    else:
        for r in flow_rows:
            net = r['net_inflow'] or 0
            ratio = r['net_inflow_ratio'] or 0
            bar = '+' if net > 0 else '-'
            net_m = net / 10000  # 转换为万
            print(f"  {r['date']} | {bar} 净流入: {net_m:>10.1f}万 | 比率: {ratio*100:>+7.2f}%")
    
    # 2. 大单数据
    print(f"\n  [大单累积 - 最近10天]")
    cur = conn.execute("""
        SELECT trade_date, super_large_buy_amt, super_large_sell_amt,
               large_buy_amt, large_sell_amt
        FROM daily_order_accumulator
        WHERE stock_code = ?
        ORDER BY trade_date DESC
        LIMIT 10
    """, (code,))
    order_rows = cur.fetchall()
    if not order_rows:
        print("  No order accumulator data")
    else:
        for r in order_rows:
            sb = (r['super_large_buy_amt'] or 0) - (r['super_large_sell_amt'] or 0)
            lb = (r['large_buy_amt'] or 0) - (r['large_sell_amt'] or 0)
            main_net = sb + lb
            print(f"  {r['trade_date']} | 超大单净:{sb/10000:>10.1f}万 | 大单净:{lb/10000:>10.1f}万 | 主力合计:{main_net/10000:>10.1f}万")
    
    # 3. K线
    print(f"\n  [K线走势 - 最近15天]")
    cur = conn.execute("""
        SELECT time_key, open_price, close_price, high_price, low_price,
               volume, turnover, turnover_rate
        FROM kline_data
        WHERE stock_code = ?
        ORDER BY time_key DESC
        LIMIT 15
    """, (code,))
    kline_rows = cur.fetchall()
    if not kline_rows:
        print("  No kline data")
    else:
        for r in kline_rows:
            o = r['open_price'] or 0
            c = r['close_price'] or 0
            chg = ((c - o) / o * 100) if o else 0
            bar = '▲' if chg > 0 else '▼' if chg < 0 else '='
            vol_w = (r['volume'] or 0) / 10000
            to_w = (r['turnover'] or 0) / 10000
            print(f"  {r['time_key'][:10]} | O:{o:>7.2f} C:{c:>7.2f} H:{r['high_price']:>7.2f} L:{r['low_price']:>7.2f} | {bar} {chg:>+6.2f}% | 量:{vol_w:>8.1f}万 | 额:{to_w:>10.1f}万 | TR:{r['turnover_rate'] or 0:.2f}%")

    # 4. 趋势分析
    print(f"\n  [趋势分析]")
    if flow_rows:
        net_3 = sum((r['net_inflow'] or 0) for r in flow_rows[:3]) / 10000
        net_5 = sum((r['net_inflow'] or 0) for r in flow_rows[:5]) / 10000
        
        consecutive_inflow = 0
        for r in flow_rows:
            if (r['net_inflow'] or 0) > 0:
                consecutive_inflow += 1
            else:
                break
        
        print(f"  近3日累计净流入: {net_3:>10.1f}万")
        print(f"  近5日累计净流入: {net_5:>10.1f}万")
        print(f"  连续净流入天数:  {consecutive_inflow}")
        
        # 流入趋势：近3日 vs 前3日
        if len(flow_rows) >= 6:
            recent3 = sum((r['net_inflow'] or 0) for r in flow_rows[:3])
            prev3 = sum((r['net_inflow'] or 0) for r in flow_rows[3:6])
            if prev3 != 0:
                trend = (recent3 - prev3) / abs(prev3) * 100
                print(f"  资金流趋势(近3 vs 前3): {trend:>+.1f}% {'加速流入' if trend > 0 else '减速/转出'}")
    
    if kline_rows:
        # 计算近5日涨跌幅
        if len(kline_rows) >= 5:
            c_today = kline_rows[0]['close_price']
            c_5ago = kline_rows[4]['close_price']
            pct5 = ((c_today - c_5ago) / c_5ago * 100) if c_5ago else 0
            print(f"  近5日涨跌幅:  {pct5:>+.2f}%")
        
        # 均量比较
        if len(kline_rows) >= 2:
            vol_today = kline_rows[0]['volume'] or 0
            vol_avg5 = sum((r['volume'] or 0) for r in kline_rows[:5]) / min(5, len(kline_rows))
            vol_ratio = vol_today / vol_avg5 if vol_avg5 else 0
            print(f"  最新日量比(vs 5日均量): {vol_ratio:.2f}")

# 5. capital_flow_cache 实时缓存
print(f"\n{'='*70}")
print(f"  实时资金流缓存 (capital_flow_cache)")
print(f"{'='*70}")
for code, name in stocks:
    cur = conn.execute("""
        SELECT * FROM capital_flow_cache WHERE stock_code = ? ORDER BY rowid DESC LIMIT 3
    """, (code,))
    rows = cur.fetchall()
    if rows:
        cols = [d[0] for d in cur.description]
        print(f"\n  --- {code} {name} ---")
        print(f"  Columns: {cols}")
        for r in rows:
            vals = {c: r[c] for c in cols}
            print(f"  {vals}")
    else:
        print(f"\n  --- {code} {name}: No cache data ---")

conn.close()
